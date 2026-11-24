"""Record a subtitled demo video of the real system working.

    pip install playwright==1.48.0          # once; it drives the Chrome already on this laptop
    python scripts/kafka_topics.py --reset  # empty alerts, so the live part starts from zero
    python scripts/spark_run.py stream_events > stream.log   # separate terminal, wait for "streaming started"
    python -m uvicorn api.main:app --port 8000               # separate terminal
    python scripts/record_demo.py --log stream.log --out C:/Users/Admin/Videos/supplychain-x-demo

Nothing is faked: Chrome drives the dashboard, and during the recording this script starts the replay
producer and the live GDACS producer, so the alerts arriving on screen are produced right then by
Kafka + Spark. Lines from the Spark job's log appear in a small panel.

Chrome streams its screen frames to this script (DevTools screencast) and ffmpeg (must be on PATH) joins
them into <out>.mp4; the subtitles are drawn in the page, so they are in the picture. <out>.srt has them
as a separate file too.
"""
import argparse
import re
import base64
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
W, H = 1440, 900

OVERLAY = """
(() => {
  const css = `
    #rec-cap { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 99999;
      max-width: 1100px; padding: 10px 22px; border-radius: 12px; background: rgba(0,0,0,.82);
      color: #fff; font: 500 21px/1.4 Inter, Segoe UI, sans-serif; text-align: center;
      box-shadow: 0 8px 30px rgba(0,0,0,.5); transition: opacity .25s; }
    #rec-cap:empty { opacity: 0; }
    #rec-log { position: fixed; left: 18px; bottom: 110px; z-index: 99998; width: 470px; padding: 10px 12px;
      border-radius: 10px; background: rgba(6,10,10,.92); border: 1px solid rgba(43,228,167,.35);
      color: #9ef0cf; font: 12px/1.45 Consolas, monospace; white-space: pre-wrap; display: none; }
    #rec-log b { color: #fff; font-weight: 600; }
    #rec-card { position: fixed; inset: 0; z-index: 100000; display: none; place-items: center;
      background: #0b0e0e; color: #e8eeec; font-family: Inter, Segoe UI, sans-serif; text-align: center; }
    #rec-card h1 { font-size: 54px; font-weight: 500; margin: 0 0 14px; letter-spacing: -.02em; }
    #rec-card p { font-size: 22px; color: #9aa8a4; margin: 8px 0; }
    #rec-card .acc { color: #2be4a7; }`;
  const add = () => {
    if (document.getElementById('rec-cap')) return;
    const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);
    for (const id of ['rec-cap', 'rec-log', 'rec-card']) {
      const d = document.createElement('div'); d.id = id; document.body.appendChild(d);
    }
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
  try { localStorage.setItem('scx-welcome', '1'); } catch (e) {}
})();
"""


class Recorder:
    def __init__(self, page, srt_path):
        self.page, self.t0, self.subs, self.srt = page, time.monotonic(), [], srt_path

    def say(self, text, secs):
        """Show a subtitle for `secs` seconds (the page keeps running meanwhile)."""
        start = time.monotonic() - self.t0
        self.page.evaluate("t => { document.getElementById('rec-cap').textContent = t; }", text)
        pump(self.page, int(secs * 1000))
        self.subs.append((start, time.monotonic() - self.t0, text))

    def clear(self):
        self.page.evaluate("() => { document.getElementById('rec-cap').textContent = ''; }")

    def card(self, html, secs):
        self.page.evaluate("h => { const c = document.getElementById('rec-card'); c.innerHTML = h; c.style.display = 'grid'; }", html)
        pump(self.page, int(secs * 1000))
        self.page.evaluate("() => { document.getElementById('rec-card').style.display = 'none'; }")

    def write_srt(self):
        def ts(s):
            ms = int(round(s * 1000))
            return "{:02d}:{:02d}:{:02d},{:03d}".format(ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)
        with open(self.srt, "w", encoding="utf-8") as f:
            for i, (a, b, t) in enumerate(self.subs, 1):
                f.write("{}\n{} --> {}\n{}\n\n".format(i, ts(a), ts(b), t))


def show_log(page, log_path, last=7):
    """Copy the newest Spark batch lines into the on-screen log panel."""
    try:
        lines = [l.rstrip() for l in Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.startswith(("batch", "   ALERT", "streaming started"))]
    except OSError:
        lines = []
    text = "\n".join(l[:78] for l in lines[-last:]) or "waiting for Spark..."
    page.evaluate("""t => { const el = document.getElementById('rec-log'); el.style.display = 'block';
                     el.innerHTML = '<b>Spark Structured Streaming - live log</b>\\n' +
                       t.replace(/&/g, '&amp;').replace(/</g, '&lt;'); }""", text)


def say_with_log(rec, page, log_path, text, secs):
    """A subtitle that stays up while the log panel refreshes every second."""
    start = time.monotonic() - rec.t0
    page.evaluate("t => { document.getElementById('rec-cap').textContent = t; }", text)
    end = time.monotonic() + secs
    while time.monotonic() < end:
        show_log(page, log_path)
        pump(page, 1000)
    rec.subs.append((start, time.monotonic() - rec.t0, text))


class Screencast:
    """Frames = JPEG screenshots taken back to back whenever the script waits (~5 per second), each with
    the time it was taken. Raw DevTools screenshots: Playwright's own page.screenshot() waits for fonts and
    takes ~3 s here, and Chrome's screencast stream barely sends frames in headless mode."""

    def __init__(self, page, folder):
        folder.mkdir(parents=True)
        self.folder, self.frames, self.gap = folder, [], 0  # gap: seconds to rest between frames
        self.cdp = page.context.new_cdp_session(page)

    def grab(self):
        shot = self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 80, "optimizeForSpeed": True})
        f = self.folder / "{:06d}.jpg".format(len(self.frames))
        f.write_bytes(base64.b64decode(shot["data"]))
        self.frames.append((time.monotonic(), f))


CAST = None


def pump(page, ms):
    """Wait `ms` milliseconds while filming the page."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        if CAST:
            CAST.grab()
            if CAST.gap:
                page.wait_for_timeout(max(1, min(CAST.gap, end - time.monotonic()) * 1000))
        else:
            page.wait_for_timeout(40)


def encode(frames, folder, mp4, t0):
    """Frames only arrive when the page changes, so each one is shown until the next (ffmpeg concat list)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        sys.exit("ffmpeg not found on PATH - the frames are in " + str(folder))
    lines = []
    for (t, f), nxt in zip(frames, frames[1:] + [(frames[-1][0] + 0.5, None)]):
        lines += ["file '{}'".format(f.as_posix()), "duration {:.3f}".format(max(nxt[0] - t, 0.001))]
    lines.append("file '{}'".format(frames[-1][1].as_posix()))  # concat needs the last file twice
    lst = folder / "frames.txt"
    lst.write_text("\n".join(lines), encoding="utf-8")
    subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-vf", "fps=25,scale={}:{}".format(W, H), "-c:v", "libx264", "-preset", "medium", "-crf", "22",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(mp4)], check=True)
    return mp4


BATCH = re.compile(r"^batch \d+: (\d+) events, (\d+) rejected(?: -> DLQ, (\d+) alerts)?")


def batches(log_path):
    """Every 'batch N: ...' line Spark has printed so far, parsed."""
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [m for m in (BATCH.match(l) for l in text.splitlines()) if m]


def totals(ms):
    """events, rejected, alerts and non-empty batches over some batch lines."""
    ev = sum(int(m.group(1)) for m in ms)
    return ev, sum(int(m.group(2)) for m in ms), sum(int(m.group(3) or 0) for m in ms), sum(1 for m in ms if int(m.group(1)))


def follow(rec, page, log_path, proc, mark, captions, done_pattern, limit=240):
    """Keep narrating (the captions in turn, then live progress numbers) until the producer has finished AND Spark's
    log shows at least as many processed events as it sent - or `limit` seconds pass."""
    t_end, sent, i = time.monotonic() + limit, None, 0
    while True:
        if i < len(captions):
            text = captions[i]
        else:  # out of scripted captions: report real progress from Spark's log instead
            ev, _, al, _ = totals(batches(log_path)[mark:])
            text = "Spark has processed {:,} of {} events so far - {} alerts.".format(
                ev, "{:,}".format(sent) if sent else "the", al)
        say_with_log(rec, page, log_path, text, 10)
        i += 1
        if sent is None and proc.poll() is not None:
            m = re.search(done_pattern, proc.stdout.read() or "")
            sent = int(m.group(1)) if m else 0
        if sent is not None and (totals(batches(log_path)[mark:])[0] >= sent or time.monotonic() > t_end):
            return sent
        if time.monotonic() > t_end + 120:  # producer itself hangs: stop waiting
            proc.kill()
            return sent


def warm_up(log_path):
    """Spark's first batch after idling is slow (~1 min). Send one real week of 2019 first and wait for it,
    so the filmed part runs at normal speed. Those events don't overlap the filmed replay (Sep-Oct)."""
    mark = len(batches(log_path))
    subprocess.run([PY, "-m", "ingestion.replay_producer", "--from", "2019-08-25", "--to", "2019-08-31",
                    "--speed", "864000"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    t = time.monotonic()
    while totals(batches(log_path)[mark:])[0] == 0 and time.monotonic() - t < 240:
        time.sleep(2)
    print("spark warmed up in {:.0f} s".format(time.monotonic() - t))


def dot_xy(page, iso3):
    """Screen position of one of a country's dots on the map."""
    return page.evaluate("""iso => { const e = [...state.dotIndex].find(([k, v]) => v === iso); if (!e) return null;
                              const [gx, gy] = e[0].split(',').map(Number), b = document.querySelector('#map').getBoundingClientRect();
                              return [b.left + gx * state.step, b.top + gy * state.step]; }""", iso3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, help="stdout of the running stream_events job")
    ap.add_argument("--out", default=str(ROOT / "demo"), help="output path without extension")
    ap.add_argument("--url", default="http://localhost:8000/")
    ap.add_argument("--no-warmup", dest="warmup", action="store_false", help="skip warming Spark up first")
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / (out.name + "_raw")
    shutil.rmtree(tmp, ignore_errors=True)

    if args.warmup:
        warm_up(args.log)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False, args=["--headless=new"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, color_scheme="dark")
        ctx.add_init_script(OVERLAY)
        page = ctx.new_page()
        page.goto(args.url, wait_until="domcontentloaded")
        page.wait_for_selector("#rec-card", state="attached")
        # film only once the dashboard has loaded: while it builds the map, screenshots take seconds each
        page.wait_for_function("document.querySelector('#map-title').textContent.includes('HAGIBIS')", timeout=60000)
        page.wait_for_timeout(4000)
        page.evaluate("() => { document.getElementById('rec-card').style.display = 'grid'; }")
        global CAST
        CAST = Screencast(page, tmp)
        frames = CAST.frames
        rec = Recorder(page, out.with_suffix(".srt"))  # subtitle times count from the first frame

        # 0. title
        rec.card("<div><h1>SUPPLYCHAIN-<span class='acc'>X</span></h1>"
                 "<p>Supply-chain disruption intelligence on a big-data stack</p>"
                 "<p>HDFS · Spark · Kafka · Spark Structured Streaming · Neo4j · PostgreSQL · FastAPI</p>"
                 "<p class='acc' style='margin-top:30px'>A real recording - everything you see is running on one laptop</p></div>", 6)

        # 1. Hagibis cascade
        page.wait_for_function("document.querySelector('#map-title').textContent.includes('HAGIBIS')", timeout=60000)
        page.click("#tb-replay")
        rec.say("Typhoon Hagibis, October 2019. The global alert system GDACS rated it only Green (minor).", 5)
        rec.say("Our own port weather data found 162 km/h gusts in Tokyo - so the engine raised its severity from 0.3 to 0.8.", 6)
        rec.say("The impact spreads hop by hop along real 2023 trade links: 19 countries depend on what Japan sends them.", 6)

        # 2. hover a country
        xy = dot_xy(page, "THA")
        if xy:
            page.mouse.move(*xy, steps=15)
        rec.say("Hover a country: its impact score and the supply chain that connects it to Japan.", 5)
        page.mouse.move(W - 40, 120)

        # 3. explainable score
        page.locator(".matrix-card").scroll_into_view_if_needed()
        pump(page, 1500)
        page.locator("#matrix .cell").first.click()
        rec.say("Every number is explainable: click any dot to see the five factors and the formula with the real values.", 7)
        page.keyboard.press("Escape")
        page.mouse.click(W - 30, 30)
        page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
        pump(page, 800)

        # 4. graph view
        xy = dot_xy(page, "JPN")
        page.mouse.click(*xy)
        page.wait_for_selector("#gr-svg .node")
        rec.say("Click any country for its supply network, straight from the Neo4j graph: who Japan buys from, and who depends on Japan.", 7)
        page.locator("#gr-svg .node", has_text="China").first.click()
        pump(page, 600)
        rec.say("Click a neighbour to walk the graph - now China, the most central country in our network.", 5)
        page.keyboard.press("Escape")

        # 5. what-if simulator
        page.click(".seg[data-mode=sim]")
        pump(page, 500)
        page.click("[data-preset=CHN]")
        rec.say("The what-if simulator: what if China is disrupted? Severity 0.8, for 14 days.", 4)
        page.click("#run")
        page.wait_for_function("document.querySelector('#event-name').textContent.includes('Simulation')", timeout=30000)
        rec.say("Every other economy we track is hit at the first hop - India gets 58% of its electronics from China.", 7)

        # 6. live pipeline - narration follows what Spark's log really shows, numbers read from it
        page.locator(".live-card").scroll_into_view_if_needed()
        pump(page, 800)
        rec.say("Now the live pipeline. Disaster events go into Kafka; Spark Structured Streaming checks, enriches and turns them into alerts.", 6)
        CAST.gap = 0.25  # fewer frames while Spark works: the laptop runs both
        mark = len(batches(args.log))
        replay = subprocess.Popen([PY, "-m", "ingestion.replay_producer", "--from", "2019-09-01", "--to", "2019-10-31",
                                   "--speed", "86400", "--bad", "3"], cwd=ROOT, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True)
        sent = follow(rec, page, args.log, replay, mark, [
            "Replaying 869 real disasters from Sep-Oct 2019 into Kafka - one day of history per second.",
            "3 broken messages were slipped in on purpose: Spark should send them to a dead-letter queue.",
            "Each Spark batch writes its alerts to PostgreSQL; the dashboard asks for new ones every 5 seconds.",
            "Ports near each event and the countries that depend on it are added to every alert."], r"done: (\d+) events")
        ev, rej, al, nb = totals(batches(args.log)[mark:])
        say_with_log(rec, page, args.log, "Checked in Spark's log: {:,} of {:,} replayed events processed in {} batches, {} broken messages "
                     "caught, {} alerts.".format(ev, sent or ev, nb, rej, al), 8)

        mark = len(batches(args.log))
        live = subprocess.Popen([PY, "-m", "ingestion.live_gdacs", "--once"], cwd=ROOT, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True)
        sent = follow(rec, page, args.log, live, mark, [
            "And now today's real disasters: the live producer asks GDACS for this week's events.",
            "Serious live events are also scored by the impact engine, like the historical ones.",
            "Same Kafka topic, same Spark job, same alerts table - live data needs no special path."], r"(\d+) new or updated events sent")
        ev, rej, al, nb = totals(batches(args.log)[mark:])
        say_with_log(rec, page, args.log, "Checked in Spark's log: {:,} live events from GDACS this week, {} alerts.".format(ev, al), 8)
        CAST.gap = 0
        page.evaluate("() => { document.getElementById('rec-log').style.display = 'none'; }")
        aid = page.evaluate("() => (live.items.find(a => a.scored && a.severity !== 'LOW') || live.items.find(a => a.scored) || {}).id")
        if aid:
            page.locator("[data-alert='{}']".format(aid)).click()
            pump(page, 1500)
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            rec.say("Click an alert to see its cascade on the map: " + page.locator("#map-title").text_content(), 7)

        # 7. ML card
        page.locator(".anoms-card").scroll_into_view_if_needed()
        pump(page, 800)
        rec.say("Machine learning: an Isolation Forest flags unusual drops in yearly trade, linked to the selected event.", 6)
        page.click("#an-only")
        pump(page, 1200)
        rec.say("Across all years the strangest drops are sanctions and wars - Russian fuel in 2023, Ukrainian cereals in 2022 - not storms.", 7)
        page.click("#an-only")
        rec.clear()

        # 8. results card
        rec.card("<div style='max-width:1000px'><h1>What we found</h1>"
                 "<p>Spark ran the same job <span class='acc'>2x faster</span> than Hadoop MapReduce</p>"
                 "<p>One storage node switched off: <span class='acc'>0 blocks lost</span>, every row read back</p>"
                 "<p>Streaming job killed mid-stream: resumed with <span class='acc'>no event lost or counted twice</span></p>"
                 "<p>Tested against real disruptions: trade dependency helps - but no score variant is proven better</p>"
                 "<p style='margin-top:30px'>github.com/Abhxym/supplychain-x</p></div>", 9)
        rec.write_srt()
        pump(page, 500)
        ctx.close()
        browser.close()

    mp4 = encode(frames, tmp, out.with_suffix(".mp4"), rec.t0)
    shutil.rmtree(tmp, ignore_errors=True)
    print("mp4:", mp4, "{:.1f} MB".format(mp4.stat().st_size / 1e6), "| subtitles:", out.with_suffix(".srt"))


if __name__ == "__main__":
    main()

// SUPPLYCHAIN-X - Disruption Intelligence dashboard
//
// The map is a dot matrix: every land pixel on a 5px grid becomes a small square. Countries in a
// cascade heat up wave by wave (teal -> yellow -> orange -> red by impact score) with a soft glow
// underneath; supply links, markers and callouts sit on an SVG layer on top.

const WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
const HOP = 1100;               // ms between cascade waves
const C = { teal: "#2be4a7", yellow: "#f5d76e", orange: "#ff8a3d", red: "#ff4d5a", cyan: "#5ad1ff",
            text: "#e8eeec", muted: "#7c8a86" };
const heat = d3.scaleLinear().domain([0.08, 0.2, 0.32, 0.45]).range([C.teal, C.yellow, C.orange, C.red]).clamp(true);
const FALLBACK = { SGP: [103.82, 1.35], HKG: [114.17, 22.3], BHR: [50.55, 26.07], MLT: [14.4, 35.9],
                   MUS: [57.55, -20.3], BRB: [-59.55, 13.15], MDV: [73.5, 4.2] };

const state = { countries: new Map(), lonlat: new Map(), features: [], featureByIso: new Map(),
                dotsByIso: new Map(), baseDots: [[], [], []], dotIndex: new Map(), step: 5,
                levels: new Map(), result: null, events: [], stats: null, activeId: null, sim: [],
                showArcs: true, showMarkers: true, showValues: false, animStart: 0, raf: null };
const $ = s => document.querySelector(s);
const fmt = d3.format(",");
const short = v => v >= 10000 ? d3.format(".3s")(v) : fmt(v);
const pct = v => Math.round(v * 100) + "%";

const canvas = $("#dots");
const ctx = canvas.getContext("2d");
const overlay = d3.select("#overlay");
let projection, W = 0, H = 0;

// ================================================================ boot
async function init() {
  const [world, countries, stats, events] = await Promise.all([
    d3.json(WORLD),
    fetch("/api/countries").then(r => r.json()),
    fetch("/api/stats").then(r => r.json()),
    fetch("/api/events?limit=600").then(r => r.json()),
  ]);
  state.stats = stats;
  state.events = events;
  countries.forEach(c => state.countries.set(c.iso3, c));
  const byNumeric = new Map(countries.filter(c => c.numeric).map(c => [c.numeric, c.iso3]));
  state.features = topojson.feature(world, world.objects.countries).features
    .filter(f => f.id !== "010")
    .map(f => Object.assign(f, { iso3: byNumeric.get(f.id) }));
  state.features.forEach(f => {
    if (!f.iso3) return;
    state.featureByIso.set(f.iso3, f);
    state.lonlat.set(f.iso3, mainCentroid(f));
  });
  countries.forEach(c => {
    if (state.lonlat.has(c.iso3)) return;
    if (FALLBACK[c.iso3]) state.lonlat.set(c.iso3, FALLBACK[c.iso3]);
    else if (c.port_lon != null) state.lonlat.set(c.iso3, [c.port_lon, c.port_lat]);
  });

  $("#sub").textContent = `Data based on ${fmt(stats.total_events)} events · ${stats.scored} scored`;
  $("#graph-size").textContent = `${countries.length} countries`;
  $("#country-list").innerHTML = countries.map(c => `<option value="${c.name} (${c.iso3})"></option>`).join("");

  layoutMap();
  drawHero();
  drawAlertCards();
  bindUI();
  bindHelp();
  new ResizeObserver(() => { layoutMap(); if (state.result) render(state.result, false); }).observe($("#map"));
  window.addEventListener("resize", () => { drawHero(); if (state.result) { drawMatrix(state.result); markWeek(state.result); } });

  const start = events.find(e => e.event_id === "TC-1000611") || events[0];  // Typhoon Hagibis
  if (start) openEvent(start.event_id);
}

function mainCentroid(f) {
  if (f.geometry.type !== "MultiPolygon") return d3.geoCentroid(f);
  const polys = f.geometry.coordinates.map(c => ({ type: "Polygon", coordinates: c }));
  return d3.geoCentroid(d3.greatest(polys, p => d3.geoArea(p)));
}

// ================================================================ dot-matrix map
function layoutMap() {
  const box = $("#map").getBoundingClientRect();
  if (!box.width || !box.height || (box.width === W && box.height === H)) return;
  W = box.width; H = box.height;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  overlay.attr("viewBox", `0 0 ${W} ${H}`);
  // leave room for the title chip above and the toolbar below
  projection = d3.geoNaturalEarth1()
    .fitExtent([[20, 52], [W - 20, H - 76]], { type: "FeatureCollection", features: state.features });
  buildDots();
}

const noise = (x, y) => { const s = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453; return s - Math.floor(s); };

function buildDots() {
  const step = W < 640 ? 4 : 5;
  const path = d3.geoPath(projection);
  const boxes = state.features.map(f => path.bounds(f));
  state.step = step;
  state.dotsByIso = new Map();
  state.baseDots = [[], [], []];
  state.dotIndex = new Map();
  for (let y = step / 2; y < H; y += step) {
    for (let x = step / 2; x < W; x += step) {
      let hit = -1;
      for (let i = 0; i < boxes.length; i++) {
        const b = boxes[i];
        if (x < b[0][0] || x > b[1][0] || y < b[0][1] || y > b[1][1]) continue;
        const ll = projection.invert([x, y]);
        if (ll && d3.geoContains(state.features[i], ll)) { hit = i; break; }
      }
      if (hit < 0) continue;
      const iso3 = state.features[hit].iso3;
      const d = { x, y, n: noise(x, y) };
      // three brightness buckets give the land a textured, terrain-like look
      state.baseDots[d.n < 0.45 ? 0 : d.n < 0.85 ? 1 : 2].push(d);
      if (iso3) {
        if (!state.dotsByIso.has(iso3)) state.dotsByIso.set(iso3, []);
        state.dotsByIso.get(iso3).push(d);
        state.dotIndex.set(Math.round(x / step) + "," + Math.round(y / step), iso3);
      }
    }
  }
}

const progress = (lvl, t) => lvl.src ? Math.min(1, t / 500) : Math.max(0, Math.min(1, (t - lvl.hop * HOP) / 700));

function drawFrame(t) {
  ctx.clearRect(0, 0, W, H);
  const s = state.step;

  // glow underneath countries in the cascade
  if (state.levels.size) {
    const path = d3.geoPath(projection, ctx);
    ctx.save();
    ctx.filter = `blur(${Math.max(8, s * 3)}px)`;
    ctx.globalCompositeOperation = "lighter";
    for (const [iso3, lvl] of state.levels) {
      const p = progress(lvl, t);
      const f = state.featureByIso.get(iso3);
      if (!p || !f) continue;
      ctx.globalAlpha = 0.33 * p * (lvl.src ? 1 : Math.min(1, 0.4 + lvl.score * 1.6));
      ctx.fillStyle = lvl.src ? C.red : heat(lvl.score);
      ctx.beginPath(); path(f); ctx.fill();
    }
    ctx.restore();
  }

  // base land
  const alphas = [0.09, 0.16, 0.26];
  ctx.fillStyle = C.teal;
  state.baseDots.forEach((bucket, i) => {
    ctx.globalAlpha = alphas[i];
    for (const d of bucket) ctx.fillRect(d.x - s * 0.18, d.y - s * 0.18, s * 0.36, s * 0.36);
  });

  // countries in the cascade, heating up wave by wave
  for (const [iso3, lvl] of state.levels) {
    const dots = state.dotsByIso.get(iso3);
    const p = progress(lvl, t);
    if (!dots || !p) continue;
    ctx.fillStyle = lvl.src ? C.red : heat(lvl.score);
    const size = s * (0.36 + 0.16 * p);
    for (const d of dots) {
      ctx.globalAlpha = p * (0.55 + 0.45 * d.n);
      ctx.fillRect(d.x - size / 2, d.y - size / 2, size, size);
    }
  }
  ctx.globalAlpha = 1;
}

function animate(on) {
  cancelAnimationFrame(state.raf);
  const maxHop = state.result ? state.result.summary.max_hop : 0;
  const end = (maxHop + 1) * HOP + 600;
  if (!on) { drawFrame(1e9); return; }
  state.animStart = performance.now();
  const step = now => {
    const t = now - state.animStart;
    drawFrame(t);
    if (t < end) state.raf = requestAnimationFrame(step);
  };
  state.raf = requestAnimationFrame(step);
}

// ================================================================ render a cascade
const xy = iso3 => { const ll = state.lonlat.get(iso3); return ll ? projection(ll) : null; };

function render(r, animated = true) {
  state.result = r;
  state.levels = new Map();
  r.sources.forEach(s => state.levels.set(s.iso3, { src: true, hop: 0, score: 1 }));
  r.affected.forEach(a => state.levels.set(a.iso3, { src: false, hop: a.hop, score: a.score }));
  animate(animated);
  drawOverlay(r, animated);
  drawStack(r, animated);
  drawGauges(r);
  drawMatrix(r);
  drawInsight(r);
  markWeek(r);
  const ev = r.event;
  $("#map-title").textContent = ev ? `${ev.title} · ${ev.start_ts.slice(0, 10)}`
                                   : `What if ${r.sources.map(s => s.name).join(" + ")} is disrupted?`;
  $("#hops-v").textContent = r.summary.max_hop;
  $("#tb-count").textContent = `${r.summary.countries} countries`;
  drawAnomalies();
}

// ================================================================ unusual trade drops (Phase 6)
// Flows Isolation Forest flagged as strange falls (ml/anomalies.py). "Only hit country" keeps the drops
// where the hit country is the supplier or the importer; countries in the cascade are highlighted.
const money = v => "$" + d3.format(".2s")(v).replace("G", "B");
const esc = s => String(s ?? "").replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

// one decimal near 0% and near -100%; every flow listed is still above zero, so never show "-100%"
const pctChange = c => { const p = Math.max(c * 100, -99.9); return (Math.abs(p) < 10 || Math.abs(p) > 99 ? p.toFixed(1) : Math.round(p)) + "%"; };

// Comtrade's official names are long ("China, Hong Kong SAR"); short ones keep each row on one line
const SHORT = { RUS: "Russia", HKG: "Hong Kong", ARE: "UAE", KOR: "S. Korea", USA: "USA", GBR: "UK",
                IRN: "Iran", TUR: "Türkiye", NLD: "Netherlands", SAU: "Saudi Arabia", VNM: "Vietnam" };
const shortName = (iso, name) => SHORT[iso] || name || iso;

async function drawAnomalies() {
  const r = state.result;
  const only = $("#an-only").getAttribute("aria-pressed") === "true";
  const hit = r ? r.sources.map(s => s.iso3) : [];
  const key = only + hit.join(",");
  if (key === state.anomKey) return;              // render() also runs on resize - don't refetch
  state.anomKey = key;
  const qs = only && hit.length ? "&countries=" + hit.join(",") : "";
  const res = await fetch("/api/anomalies?limit=8" + qs).catch(() => null);
  const data = res && res.ok ? await res.json() : null;
  if (key !== state.anomKey) return;              // a newer event was picked meanwhile
  if (!data) {
    // 404: the API process is older than this page; 500: the table is missing
    $("#an-sub").textContent = "";
    $("#anoms").innerHTML = `<div class="an-empty">${res && res.status === 404
      ? "This API server is older than the page - restart <code>uvicorn api.main:app</code> to load <code>/api/anomalies</code>."
      : "No anomaly data - run <code>python -m ml.anomalies</code>, then reload."}</div>`;
    state.anomKey = null;                         // try again on the next event
    return;
  }

  // every cascade contains all 20 importers, so only the hit country is worth highlighting
  const isHit = new Set(hit);
  const names = hit.map(i => shortName(i, state.countries.get(i)?.name)).join(" + ");
  $("#an-sub").textContent = only ? `${fmt(data.total)} involve ${names}` : `top ${data.items.length} of ${fmt(data.total)}`;
  const who = (iso, name) => isHit.has(iso) ? `<b>${esc(shortName(iso, name))}</b>` : esc(shortName(iso, name));
  $("#anoms").innerHTML = data.items.length ? data.items.map(a => `
    <div class="an-row" title="${money(a.value_before)} → ${money(a.value_after)} · supplier's share ${a.share_change > 0 ? "+" : ""}${(a.share_change * 100).toFixed(1)} pts · anomaly score ${a.score.toFixed(2)}">
      <span class="who">${who(a.importer, a.importer_name)}<span class="arrow">&larr;</span>${who(a.supplier, a.supplier_name)}</span>
      <span class="chg"><span class="an-bar"><i style="width:${Math.min(100, -a.change * 100).toFixed(0)}%"></i></span>${pctChange(a.change)}</span>
      <span class="what">${esc(a.product)} · ${a.year}</span>
    </div>`).join("")
    : `<div class="an-empty">No unusual yearly drop involves ${esc(names)}. Annual trade totals average out short
       disruptions - a two-week port closure rarely shows up in a whole year of trade.</div>`;
}

function curve([x1, y1], [x2, y2]) {
  const dx = x2 - x1, dy = y2 - y1, d = Math.hypot(dx, dy);
  return `M${x1},${y1} Q${(x1 + x2) / 2 - dy * 0.2},${(y1 + y2) / 2 + dx * 0.2 - d * 0.1} ${x2},${y2}`;
}

function drawOverlay(r, animated) {
  const t = animated ? 1 : 0;
  overlay.selectAll("*").remove();
  overlay.append("defs").append("filter").attr("id", "glow")
    .attr("x", "-50%").attr("y", "-50%").attr("width", "200%").attr("height", "200%")
    .html('<feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>');

  // supply links used by the cascades
  const links = new Map();
  r.affected.forEach(a => a.chains.slice(0, 2).forEach(ch => {
    for (let i = 0; i < ch.path.length - 1; i++) {
      const k = ch.path[i] + ">" + ch.path[i + 1];
      if (!links.has(k) || ch.shares[i] > links.get(k).share)
        links.set(k, { a: ch.path[i], b: ch.path[i + 1], hop: i + 1, share: ch.shares[i], score: a.score });
    }
  }));
  const arcs = [...links.values()].filter(l => xy(l.a) && xy(l.b)).sort((p, q) => p.hop - q.hop);
  overlay.append("g").attr("class", "arcs").attr("opacity", state.showArcs ? 1 : 0)
    .selectAll("path").data(arcs).join("path")
    .attr("class", "arc").attr("filter", "url(#glow)")
    .attr("d", l => curve(xy(l.a), xy(l.b)))
    .attr("stroke", l => heat(l.score))
    .attr("stroke-width", l => 0.6 + l.share * 2.6)
    .attr("stroke-opacity", l => l.hop === 1 ? 0.75 : 0.5)
    .each(function (l, i) {
      const len = this.getTotalLength();
      d3.select(this).attr("stroke-dasharray", `${len} ${len}`).attr("stroke-dashoffset", t ? len : 0)
        .transition().delay(((l.hop - 1) * HOP + 200 + i * 10) * t).duration(1000 * t).ease(d3.easeCubicOut)
        .attr("stroke-dashoffset", 0);
    });

  const marks = overlay.append("g").attr("class", "marks").attr("opacity", state.showMarkers ? 1 : 0);

  // hit countries: pulse + warning marker
  r.sources.filter(s => xy(s.iso3)).forEach(s => {
    const [x, y] = xy(s.iso3);
    marks.append("circle").attr("class", "pulse").attr("cx", x).attr("cy", y).attr("r", 12).attr("stroke-width", 1.5);
    const g = marks.append("g").attr("transform", `translate(${x},${y})`);
    g.append("circle").attr("r", 11).attr("class", "marker-bg");
    g.append("path").attr("d", "M0,-5.5 L5.5,4.5 L-5.5,4.5 Z").attr("fill", C.red);
    g.append("rect").attr("x", -0.6).attr("y", -2.4).attr("width", 1.2).attr("height", 3.6).attr("fill", "#0b0e0e");
  });

  // the three hardest-hit countries get an orange marker
  r.affected.slice(0, 3).filter(a => xy(a.iso3)).forEach((a, i) => {
    const [x, y] = xy(a.iso3);
    const g = marks.append("g").attr("transform", `translate(${x},${y})`).attr("opacity", t ? 0 : 1);
    g.append("circle").attr("r", 9).attr("class", "marker-bg");
    g.append("circle").attr("r", 5).attr("fill", C.orange);
    g.append("text").attr("y", 3).attr("text-anchor", "middle").attr("font-size", 8).attr("font-weight", 700)
      .attr("fill", "#0b0e0e").text("!");
    if (t) g.transition().delay(a.hop * HOP + 500 + i * 120).duration(400).attr("opacity", 1);
  });

  // weather callout next to the hit country, like an incident chip
  const w = r.weather_evidence && d3.greatest(r.weather_evidence, e => e.gust_kmh);
  const src = r.sources.find(s => xy(s.iso3));
  if (w && src) {
    const [x, y] = xy(src.iso3);
    const label = `${w.gust_kmh} km/h gusts · ${w.port} · ${w.date.slice(5)}`;
    const c = marks.append("g").attr("class", "callout").attr("opacity", t ? 0 : 1);
    const leader = c.append("path");
    const pill = c.append("rect");
    const icon = c.append("path").attr("d", "M0,-4.5 L4.5,3.5 L-4.5,3.5 Z").attr("fill", C.red);
    const text = c.append("text").text(label);
    const width = text.node().getComputedTextLength() + 40;  // measure, don't guess
    const right = x - width - 30 < 10;  // not enough room on the left -> put it on the right
    const cx = Math.max(10, Math.min(W - width - 10, right ? x + 26 : x - width - 26));
    const cy = Math.max(60, y - 48);
    leader.attr("d", `M${right ? cx : cx + width},${cy + 13} L${x},${y}`)
      .attr("stroke", "rgba(255,77,90,.5)").attr("fill", "none").attr("stroke-dasharray", "2 3");
    pill.attr("x", cx).attr("y", cy).attr("width", width).attr("height", 26).attr("rx", 13);
    icon.attr("transform", `translate(${cx + 14},${cy + 13})`);
    text.attr("x", cx + 26).attr("y", cy + 17);
    if (t) c.transition().delay(600).duration(400).attr("opacity", 1);
  }
}

// ================================================================ side pieces
function drawStack(r, animated) {
  const top = r.affected.slice(0, 5);
  $("#stack").innerHTML = `
    <div class="head"><span>Most affected<button class="info" data-info="affected" aria-label="What is this?">i</button></span><span class="warn">
      <svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1L11 10H1Z" fill="${C.orange}"/></svg>${r.summary.countries}</span></div>
    ${top.map((a, i) => `<div class="person" style="animation-delay:${animated ? a.hop * HOP + 300 + i * 90 : 0}ms"
        title="${a.chains[0].path.join(" → ")} · ${a.chains[0].product}">
      <span class="av" style="border-color:${heat(a.score)}">${a.iso3}</span>
      <span class="nm">${a.name}</span><span class="sc" style="color:${heat(a.score)}">${a.score.toFixed(2)}</span></div>`).join("")}`;
}

function gauge(el, { label, value, max, text, sub, color, info }) {
  const cx = 66, cy = 60, R = 46, a0 = -Math.PI * 0.75, a1 = Math.PI * 0.75;
  const frac = Math.max(0, Math.min(1, value / max));
  const arc = d3.arc().innerRadius(R - 1.5).outerRadius(R + 1.5).cornerRadius(2);
  const ang = a0 + (a1 - a0) * frac;
  const ticks = d3.range(0, 41).map(i => {
    const a = a0 + (a1 - a0) * i / 40 - Math.PI / 2;
    const r1 = R + 7, r2 = R + (i % 5 ? 10 : 13);
    const on = i / 40 <= frac;
    return `<line x1="${cx + r1 * Math.cos(a)}" y1="${cy + r1 * Math.sin(a)}" x2="${cx + r2 * Math.cos(a)}" y2="${cy + r2 * Math.sin(a)}"
      stroke="${on ? color : "rgba(255,255,255,.12)"}" stroke-width="1" opacity="${on ? 0.8 : 1}"/>`;
  }).join("");
  const nx = cx + (R - 8) * Math.cos(ang - Math.PI / 2), ny = cy + (R - 8) * Math.sin(ang - Math.PI / 2);
  el.innerHTML = `
    <svg viewBox="0 0 132 112" role="img" aria-label="${label}: ${text}">
      <path d="${arc({ startAngle: a0, endAngle: a1 })}" transform="translate(${cx},${cy})" fill="rgba(255,255,255,.08)"/>
      <path d="${arc({ startAngle: a0, endAngle: ang })}" transform="translate(${cx},${cy})" fill="${color}"/>
      ${ticks}
      <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${C.text}" stroke-width="1.5" stroke-linecap="round"/>
      <circle cx="${cx}" cy="${cy}" r="3" fill="${C.text}"/>
    </svg>
    <div class="g-l">${label}<button class="info" data-info="${info}" aria-label="What is this?">i</button></div>
    <div class="g-v">${text}<small>${sub}</small></div>`;
}

function drawGauges(r) {
  const el = $("#gauges");
  el.innerHTML = '<div class="gauge"></div><div class="gauge"></div><div class="gauge"></div>';
  const [a, b, c] = el.querySelectorAll(".gauge");
  const peak = d3.max(r.affected, x => x.score) || 0;
  const p = r.parameters;
  const raised = p.severity_used > p.severity_in;
  gauge(a, { label: "Countries in cascade", value: r.summary.countries, max: state.countries.size,
             text: r.summary.countries, sub: "/ " + state.countries.size, color: C.teal, info: "g1" });
  gauge(b, { label: "Peak impact score", value: peak, max: 0.5, text: peak.toFixed(2), sub: "/ 1.0", color: heat(peak),
             info: "g2" });
  gauge(c, { label: raised ? "Severity (weather-raised)" : "Severity used", value: p.severity_used, max: 1,
             text: p.severity_used.toFixed(2), sub: raised ? "was " + p.severity_in.toFixed(2) : "/ 1.0",
             color: raised ? C.cyan : C.orange, info: "g3" });
}

function drawInsight(r) {
  const p = r.parameters, ev = r.event, top = r.affected[0];
  const w = r.weather_evidence.length && d3.greatest(r.weather_evidence, e => e.gust_kmh);
  let html;
  if (ev && p.severity_used > p.severity_in && w) {
    html = `<span class="tag">Why this matters</span><br>GDACS rated this <b>${ev.alert_level}</b>. Our port weather data recorded
      <b>${w.gust_kmh} km/h</b> at ${w.port} on ${w.date}, so the engine raised severity from
      <b>${p.severity_in.toFixed(2)}</b> to <b>${p.severity_used.toFixed(2)}</b>.`;
  } else if (top) {
    const ch = top.chains[0];
    const via = ch.hop > 1 ? " (via " + ch.path.slice(1, -1).join(", ") + ")" : "";
    html = `<span class="tag">Hardest hit</span><br><b>${top.name}</b> gets <b>${pct(ch.shares[ch.shares.length - 1])}</b> of its
      ${ch.product.toLowerCase()} from ${ch.path[ch.path.length - 2]}${via}.
      ${r.summary.countries} countries feel it within ${r.summary.max_hop} hop${r.summary.max_hop > 1 ? "s" : ""}.`;
  } else {
    html = `<span class="tag">No cascade</span><br>No country relies on this one for ≥ ${pct(p.min_share)} of a product.`;
  }
  $("#insight").innerHTML = html;
}

// ================================================================ hero charts
function drawHero() {
  const st = state.stats;
  if (!st) return;
  // weekly intensity: thin bars, weeks with orange/red events tipped in orange
  const hist = d3.select("#hist");
  const hw = hist.node().clientWidth, hh = hist.node().clientHeight;
  hist.attr("viewBox", `0 0 ${hw} ${hh}`).selectAll("*").remove();
  const x = d3.scaleBand().domain(st.weekly.map(d => d.week)).range([0, hw]).padding(0.35);
  const y = d3.scaleLinear().domain([0, d3.max(st.weekly, d => d.all)]).range([hh - 2, 6]);
  hist.append("g").selectAll("rect").data(st.weekly).join("rect")
    .attr("x", d => x(d.week)).attr("width", Math.max(0.8, x.bandwidth()))
    .attr("y", d => y(d.all)).attr("height", d => hh - 2 - y(d.all))
    .attr("fill", C.teal).attr("opacity", 0.55)
    .append("title").text(d => `week of ${d.week}: ${d.all} events, ${d.serious} orange/red`);
  hist.append("g").selectAll("circle").data(st.weekly.filter(d => d.serious)).join("circle")
    .attr("cx", d => x(d.week) + x.bandwidth() / 2).attr("cy", d => y(d.all) - 3)
    .attr("r", d => Math.min(2.4, 0.9 + d.serious * 0.35)).attr("fill", C.orange);
  hist.append("g").attr("id", "week-mark");
  $("#hist-min").textContent = `${d3.min(st.weekly, d => d.all)} / week`;
  $("#hist-max").textContent = `${d3.max(st.weekly, d => d.all)} / week`;

  // severe port-weather days per month as spikes
  const sp = d3.select("#spikes");
  const sw = sp.node().clientWidth, sh = sp.node().clientHeight;
  sp.attr("viewBox", `0 0 ${sw} ${sh}`).selectAll("*").remove();
  const m = st.monthly_severe;
  const xs = d3.scalePoint().domain(m.map(d => d.month)).range([6, sw - 6]);
  const ys = d3.scaleLinear().domain([0, d3.max(m, d => d.days)]).range([sh - 2, 14]);
  const half = Math.max(3, (sw / m.length) * 0.9);
  const grad = sp.append("defs").append("linearGradient").attr("id", "spk").attr("x1", 0).attr("x2", 0).attr("y1", 0).attr("y2", 1);
  grad.append("stop").attr("offset", 0).attr("stop-color", C.text).attr("stop-opacity", 0.55);
  grad.append("stop").attr("offset", 1).attr("stop-color", C.teal).attr("stop-opacity", 0.05);
  sp.append("line").attr("x1", 0).attr("x2", sw).attr("y1", sh - 2).attr("y2", sh - 2).attr("stroke", "rgba(255,255,255,.12)");
  sp.append("g").selectAll("path").data(m.filter(d => d.days)).join("path")
    .attr("d", d => `M${xs(d.month) - half},${sh - 2} L${xs(d.month)},${ys(d.days)} L${xs(d.month) + half},${sh - 2} Z`)
    .attr("fill", "url(#spk)").attr("stroke", "rgba(232,238,236,.5)").attr("stroke-width", 0.8)
    .append("title").text(d => `${d.month}: ${d.days} severe days`);
  const peaks = [...m].sort((a, b) => b.days - a.days).slice(0, 3);
  sp.append("g").selectAll("path").data(peaks).join("path")
    .attr("transform", d => `translate(${xs(d.month)},${ys(d.days) - 7})`)
    .attr("d", "M0,3 L-3.5,-3 L3.5,-3 Z").attr("fill", C.text);
  $("#spike-max").textContent = `peak ${peaks[0].days} days · ${peaks[0].month}`;
}

function markWeek(r) {
  const g = d3.select("#week-mark");
  g.selectAll("*").remove();
  if (!r.event || !state.stats) return;
  const d = new Date(r.event.start_ts.slice(0, 10) + "T00:00:00Z");
  const monday = new Date(d - ((d.getUTCDay() + 6) % 7) * 864e5).toISOString().slice(0, 10);
  const hist = d3.select("#hist");
  const hw = hist.node().clientWidth, hh = hist.node().clientHeight;
  const x = d3.scaleBand().domain(state.stats.weekly.map(w => w.week)).range([0, hw]).padding(0.35);
  if (x(monday) == null) return;
  const cx = x(monday) + x.bandwidth() / 2;
  g.append("line").attr("x1", cx).attr("x2", cx).attr("y1", 0).attr("y2", hh).attr("stroke", C.red).attr("stroke-width", 1.2);
  g.append("circle").attr("cx", cx).attr("cy", 3).attr("r", 3).attr("fill", C.red);
}

// ================================================================ matrix + alert cards
function drawMatrix(r) {
  const svg = d3.select("#matrix");
  const w = svg.node().clientWidth, h = svg.node().clientHeight;
  svg.attr("viewBox", `0 0 ${w} ${h}`).selectAll("*").remove();
  // industry x country cells from every chain's industries
  const cells = new Map();
  r.affected.forEach(a => a.chains.forEach(ch => ch.industries.forEach(ind => {
    const k = ind + "|" + a.iso3;
    // keep the chain behind each cell, so a click can explain where the number comes from
    if (!cells.has(k) || ch.score > cells.get(k).score)
      cells.set(k, { ind, iso3: a.iso3, name: a.name, score: ch.score, product: ch.product, chain: ch });
  })));
  const totals = d3.rollup([...cells.values()], v => d3.sum(v, c => c.score), c => c.ind);
  const rows = [...totals.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(d => d[0]);
  const cols = r.affected.slice(0, Math.max(6, Math.min(18, Math.floor((w - 160) / 34)))).map(a => a.iso3);
  $("#mx-sub").textContent = rows.length ? `${rows.length} industries × ${cols.length} countries` : "no cascade";
  if (!rows.length) return;

  const left = 150, bottom = 20, top = 6;
  const x = d3.scalePoint().domain(cols).range([left + 12, w - 12]);
  const y = d3.scalePoint().domain(rows).range([top + 8, h - bottom - 10]);
  // faint dot field, like a sensor grid
  const field = svg.append("g").attr("fill", "rgba(255,255,255,.09)");
  for (let gx = left; gx < w - 4; gx += 9) for (let gy = top; gy < h - bottom; gy += 9)
    field.append("rect").attr("x", gx).attr("y", gy).attr("width", 1.2).attr("height", 1.2);
  svg.append("g").selectAll("text").data(rows).join("text")
    .attr("x", 0).attr("y", d => y(d) + 4).attr("fill", C.muted).attr("font-size", 11).text(d => d);
  svg.append("g").selectAll("text").data(cols).join("text")
    .attr("x", d => x(d)).attr("y", h - 4).attr("text-anchor", "middle").attr("fill", C.muted).attr("font-size", 10).text(d => d);

  const data = [...cells.values()].filter(c => rows.includes(c.ind) && cols.includes(c.iso3));
  const radius = c => 2.5 + c.score * 13;
  svg.append("g").selectAll("circle").data(data).join("circle")
    .attr("class", "cell")
    .attr("cx", c => x(c.iso3)).attr("cy", c => y(c.ind)).attr("r", 0)
    .attr("fill", c => heat(c.score)).attr("fill-opacity", 0.9)
    .attr("tabindex", 0).attr("role", "button")
    .attr("aria-label", c => `${c.name}, ${c.ind}: impact ${c.score.toFixed(2)}. Open breakdown`)
    .on("click", (e, c) => { e.stopPropagation(); showCell(c, e); })
    .on("keydown", (e, c) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); showCell(c, e); } })
    .transition().delay((_, i) => 200 + i * 15).duration(400).attr("r", radius);

  // "Values" switch: print every score next to its dot
  if (state.showValues) {
    svg.append("g").selectAll("text").data(data).join("text")
      .attr("x", c => x(c.iso3)).attr("y", c => y(c.ind) - radius(c) - 3)
      .attr("text-anchor", "middle").attr("font-size", 9).attr("fill", C.text).attr("pointer-events", "none")
      .text(c => c.score.toFixed(2));
  }

  // label the hottest cell, like an incident chip (not needed when every value is printed)
  const hot = !state.showValues && d3.greatest(data, c => c.score);
  if (hot) {
    const label = `${hot.iso3} · ${hot.ind}  ${hot.score.toFixed(2)}`;
    const lw = label.length * 6 + 22;
    const lx = Math.min(w - lw - 4, x(hot.iso3) + 14), ly = Math.max(2, y(hot.ind) - 30);
    const g = svg.append("g").attr("pointer-events", "none");  // the chip must not block clicks on dots under it
    g.append("rect").attr("x", lx).attr("y", ly).attr("width", lw).attr("height", 22).attr("rx", 11)
      .attr("fill", "rgba(16,21,21,.95)").attr("stroke", "rgba(255,138,61,.5)");
    g.append("circle").attr("cx", lx + 11).attr("cy", ly + 11).attr("r", 3.5).attr("fill", C.orange);
    g.append("text").attr("x", lx + 20).attr("y", ly + 15).attr("fill", C.text).attr("font-size", 11).text(label);
  }
}

function drawAlertCards() {
  const s = state.stats;
  const icon = {
    Green: `<svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 1l6 2.5v4C14 11 11.4 14 8 15 4.6 14 2 11 2 7.5v-4z" fill="${C.teal}"/><path d="M5.3 8l2 2 3.5-4" stroke="#0b0e0e" stroke-width="1.6" fill="none"/></svg>`,
    Orange: `<svg width="14" height="14" viewBox="0 0 16 16"><circle cx="8" cy="8" r="6.5" fill="${C.orange}"/><rect x="7.2" y="4" width="1.6" height="5" fill="#0b0e0e"/><rect x="7.2" y="10.4" width="1.6" height="1.6" fill="#0b0e0e"/></svg>`,
    Red: `<svg width="14" height="14" viewBox="0 0 16 16"><path d="M8 1.5L15 14H1z" fill="${C.red}"/><rect x="7.2" y="6" width="1.6" height="4" fill="#0b0e0e"/><rect x="7.2" y="11" width="1.6" height="1.5" fill="#0b0e0e"/></svg>`,
    wx: `<svg width="14" height="14" viewBox="0 0 16 16"><path d="M9.5 1L3 9h4l-1 6 6.5-8h-4z" fill="${C.cyan}"/></svg>`,
  };
  const cards = [
    { k: "Green", name: "Minor", v: s.levels.Green, of: s.total_events, l: "Green alerts" },
    { k: "Orange", name: "Serious", v: s.levels.Orange, of: s.total_events, l: "Orange alerts" },
    { k: "Red", name: "Severe", v: s.levels.Red, of: s.total_events, l: "Red alerts" },
    { k: "wx", name: "Weather-raised", v: s.weather_boosted, of: s.scored, l: "Severity raised by our data" },
  ];
  $("#alert-grid").innerHTML = cards.map(c => `
    <div class="acard">
      <div class="top"><span class="ico">${icon[c.k]}</span>${c.name}</div>
      <div><div class="lbl2">${c.l}</div><div class="big">${short(c.v)}<small>/ ${short(c.of)}</small></div></div>
    </div>`).join("");
}

// ================================================================ tooltip on the dot map
function hover(e) {
  const box = $("#map").getBoundingClientRect();
  const mx = e.clientX - box.left, my = e.clientY - box.top;
  const iso3 = state.dotIndex.get(Math.round(mx / state.step) + "," + Math.round(my / state.step));
  const tip = $("#tip");
  if (!iso3 || !state.result || e.target.closest(".stack, .toolbar, .map-title")) { tip.hidden = true; return; }
  const c = state.countries.get(iso3);
  const a = state.result.affected.find(x => x.iso3 === iso3);
  const src = state.result.sources.find(s => s.iso3 === iso3);
  let html = `<b>${(c && c.name) || iso3}</b>`;
  if (src) html += `<div class="row">directly hit${src.ports.length ? " · ports: " + src.ports.map(p => p.name).join(", ") : ""}</div>`;
  else if (a) html += `<div class="row">impact <b style="color:${heat(a.score)}">${a.score.toFixed(2)}</b> · ${a.hop} hop${a.hop > 1 ? "s" : ""}</div>` +
    a.chains.slice(0, 3).map(ch => `<div class="row">${ch.path.join(" → ")} · ${ch.product} ${pct(ch.dependency)}</div>`).join("");
  else html += `<div class="row">not in this cascade</div>`;
  tip.innerHTML = html;
  tip.hidden = false;
  tip.style.left = Math.min(mx + 14, W - tip.offsetWidth - 8) + "px";
  tip.style.top = Math.min(my + 14, H - tip.offsetHeight - 8) + "px";
}

// ================================================================ events + simulator
function renderEventList() {
  const q = ($("#pop-q").value || "").trim().toLowerCase();
  const list = state.events.filter(e => !q || (e.title + " " + (e.sources || []).join(" ")).toLowerCase().includes(q));
  $("#events").innerHTML = list.slice(0, 200).map(e => `
    <li data-id="${e.event_id}" class="${e.event_id === state.activeId ? "active" : ""}">
      <span class="t">${e.title}</span><span class="s">${e.max_score.toFixed(2)}</span>
      <span class="m"><span class="lvl ${e.alert_level}">${e.alert_level}</span>
        ${e.severity_used > e.severity_in ? '<span class="lvl wx">weather-raised</span>' : ""}
        ${e.start_ts.slice(0, 10)} · ${(e.sources || []).slice(0, 4).join(", ")}</span>
    </li>`).join("") || '<li class="muted">No matching events</li>';
}

function openPop(id, anchor) {
  document.querySelectorAll(".pop").forEach(p => { if (p.id !== id) p.hidden = true; });
  const pop = $("#" + id);
  const b = anchor.getBoundingClientRect();
  pop.hidden = false;
  pop.style.top = b.bottom + 8 + "px";
  pop.style.left = Math.max(12, Math.min(window.innerWidth - pop.offsetWidth - 12, b.left)) + "px";
}

async function openEvent(id) {
  state.activeId = id;
  const r = await fetch("/api/impact/" + id).then(x => x.json());
  $("#event-name").textContent = r.event.title;
  render(r);
}

function renderChips() {
  $("#sim-chips").innerHTML = state.sim.map(iso =>
    `<span class="chip">${(state.countries.get(iso) || {}).name || iso}<button data-rm="${iso}" aria-label="remove">×</button></span>`).join("");
}

async function runSim() {
  if (!state.sim.length) { $("#sim-country").focus(); return; }
  const btn = $("#run");
  btn.disabled = true; btn.textContent = "Following supply links…";
  try {
    const r = await fetch("/api/simulate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ countries: state.sim, severity: +$("#sev").value, duration_days: +$("#dur").value,
                             decay: +$("#decay").value, min_share: +$("#share").value }),
    }).then(x => x.json());
    state.activeId = null;
    $("#event-name").textContent = "Simulation: " + state.sim.join(" + ");
    $("#sim-pop").hidden = true;
    render(r);
  } finally {
    btn.disabled = false; btn.textContent = "Simulate cascade";
  }
}

function bindUI() {
  const closePops = () => document.querySelectorAll(".pop").forEach(p => { p.hidden = true; });
  $("#event-btn").addEventListener("click", e => {
    e.stopPropagation(); renderEventList(); openPop("event-pop", e.currentTarget); $("#pop-q").focus();
  });
  $("#pop-q").addEventListener("input", renderEventList);
  $("#an-only").addEventListener("click", e => {
    const b = e.currentTarget;
    b.setAttribute("aria-pressed", b.getAttribute("aria-pressed") === "true" ? "false" : "true");
    drawAnomalies();
  });
  $("#q").addEventListener("input", e => {
    $("#pop-q").value = e.target.value; renderEventList(); openPop("event-pop", $("#event-btn"));
  });
  $("#q").addEventListener("click", e => e.stopPropagation());
  $("#events").addEventListener("click", e => {
    const li = e.target.closest("li[data-id]");
    if (!li) return;
    closePops();
    document.querySelectorAll(".seg").forEach(s => s.classList.toggle("active", s.dataset.mode === "events"));
    openEvent(li.dataset.id);
  });
  document.querySelectorAll(".seg").forEach(b => b.addEventListener("click", e => {
    e.stopPropagation();
    document.querySelectorAll(".seg").forEach(s => s.classList.toggle("active", s === b));
    if (b.dataset.mode === "sim") openPop("sim-pop", b);
    else { renderEventList(); openPop("event-pop", $("#event-btn")); }
  }));
  document.addEventListener("click", e => { if (!e.target.closest(".pop")) closePops(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closePops(); });

  $("#sim-country").addEventListener("change", e => {
    const m = e.target.value.match(/\(([A-Z]{3})\)$/);
    if (m && !state.sim.includes(m[1])) { state.sim.push(m[1]); renderChips(); }
    e.target.value = "";
  });
  $("#sim-chips").addEventListener("click", e => {
    if (e.target.dataset.rm) { state.sim = state.sim.filter(x => x !== e.target.dataset.rm); renderChips(); }
  });
  document.querySelectorAll("[data-preset]").forEach(b => b.addEventListener("click", () => {
    state.sim = b.dataset.preset.split(","); renderChips();
  }));
  const out = (id, f) => {
    const el = $("#" + id), o = $("#" + id + "-out");
    const upd = () => { o.textContent = f(+el.value); };
    el.addEventListener("input", upd); upd();
  };
  out("sev", v => v.toFixed(2));
  out("dur", v => v + " days");
  out("decay", v => v.toFixed(2));
  out("share", v => Math.round(v * 100) + "%");
  $("#run").addEventListener("click", runSim);

  $("#tb-replay").addEventListener("click", () => state.result && render(state.result, true));
  $("#tb-arcs").addEventListener("click", e => {
    state.showArcs = !state.showArcs;
    e.currentTarget.classList.toggle("active", state.showArcs);
    overlay.select(".arcs").attr("opacity", state.showArcs ? 1 : 0);
  });
  $("#tb-labels").addEventListener("click", e => {
    state.showMarkers = !state.showMarkers;
    e.currentTarget.classList.toggle("active", state.showMarkers);
    overlay.selectAll(".marks").attr("opacity", state.showMarkers ? 1 : 0);
  });
  $("#map").addEventListener("mousemove", hover);
  $("#map").addEventListener("mouseleave", () => { $("#tip").hidden = true; });
}

// ================================================================ help for newcomers
// Plain-language explanations shown by the "i" buttons. Written for someone seeing this for the first time.
const INFO = {
  map: ["The cascade map",
    "Each dot is a piece of land. <b>Red</b> is where the disaster hit. Countries that <b>buy from it</b> light up, " +
    "coloured by how hard they're hit (teal = mild, red = severe). <b>Lines</b> are the trade links the impact travels along; " +
    "thicker means a bigger share of that country's supply. Hover any country for its details."],
  intensity: ["Disaster intensity",
    "How many disasters <b>GDACS</b> (the UN/EU disaster alert system) recorded each week, 2019–2023. " +
    "<b>Orange dots</b> mark weeks with serious (Orange or Red) events. The <b>red line</b> is the week of the event you're viewing."],
  severe: ["Severe port weather",
    "Days per month when one of our 45 major ports had <b>storm-force wind</b> (gusts ≥ 89 km/h) or <b>very heavy rain</b> " +
    "(≥ 115.6 mm), from Open-Meteo weather records. The triangles mark the three worst months."],
  affected: ["Most affected",
    "The countries hit hardest, ranked by <b>impact score</b> from 0 (no effect) to 1 (maximum). Hover a row to see the trade chain behind it."],
  g1: ["Countries in cascade",
    "How many countries the disruption reaches by following trade links, out of the 102 countries in our trade graph."],
  g2: ["Peak impact score",
    "The highest impact score of any affected country. The score adds up 5 factors - <b>severity</b>, <b>dependency</b>, " +
    "<b>trade value</b>, <b>how central</b> the country is in world trade, and <b>duration</b> - and fades by 40% with every hop."],
  g3: ["Severity",
    "How bad the event itself was, 0 to 1. The GDACS alert level sets the start (Green 0.3, Orange 0.6, Red 1.0). " +
    "<b>Cyan</b> means our own weather data found storm winds or extreme rain at a major port during the event and raised it."],
  matrix: ["Cascade by industry",
    "Rows are industries, columns are affected countries. A dot means that industry in that country depends on a product " +
    "the disruption cuts off. <b>Bigger and redder = higher impact.</b> <b>Click any dot</b> to see exactly why, and how the score was calculated."],
  alerts: ["Events by alert level",
    "All 48,802 disasters from 2019–2023, by GDACS alert level. <b>Weather-raised</b> counts the events where our own " +
    "port weather data showed it was worse than GDACS said, so the engine raised the severity."],
  anoms: ["Unusual trade drops",
    "Yearly import flows (importer &larr; supplier, one product) that fell in an <b>unusual</b> way, found by an " +
    "<b>Isolation Forest</b>: a machine-learning method that cuts the data at random and flags points that are cut off " +
    "after only a few cuts. No labels needed. Most of the strangest drops are <b>wars, sanctions and export bans</b>, " +
    "not weather - short disasters rarely show up in a whole year of trade. <b>Orange names</b> are in the current cascade."],
};

function showInfo(btn) {
  const [title, text] = INFO[btn.dataset.info] || ["", ""];
  const tip = $("#info-tip");
  tip.innerHTML = `<span class="t">${title}</span>${text}`;
  tip.hidden = false;
  const b = btn.getBoundingClientRect();
  const left = Math.min(window.innerWidth - tip.offsetWidth - 12, Math.max(12, b.left - 20));
  const below = b.bottom + 8 + tip.offsetHeight < window.innerHeight;
  tip.style.left = left + "px";
  tip.style.top = (below ? b.bottom + 8 : b.top - tip.offsetHeight - 8) + "px";
}
const hideInfo = () => { $("#info-tip").hidden = true; };

// ---------------------------------------------------------------- matrix cell breakdown
function showCell(c, e) {
  const r = state.result, ch = c.chain, k = ch.components;
  const w = r.parameters.weights, decay = r.parameters.decay;
  d3.selectAll("#matrix .cell").classed("sel", d => d === c);
  const names = iso => (state.countries.get(iso) || {}).name || iso;
  const steps = ch.path.map((iso, i) => i === 0 ? `<b>${names(iso)}</b>` : ` → <b>${names(iso)}</b> (${pct(ch.shares[i - 1])})`).join("");
  const why = ch.hop === 1
    ? `<b>${c.name}</b> gets <b>${pct(ch.shares[0])}</b> of its ${ch.product.toLowerCase()} from <b>${names(ch.path[0])}</b>, ` +
      `and ${ch.product.toLowerCase()} feeds its <b>${c.ind.toLowerCase()}</b> industry.`
    : `The shortage travels ${steps}. Multiplying the shares gives a dependency of <b>${pct(ch.dependency)}</b> on ` +
      `${names(ch.path[0])} for ${ch.product.toLowerCase()}, which feeds <b>${c.ind.toLowerCase()}</b>.`;
  const parts = [
    ["Severity", "severity", k.S], ["Dependency", "dependency", k.D], ["Trade value", "exposure", k.E],
    ["Centrality", "centrality", k.C], ["Duration", "duration", k.T],
  ];
  const rows = parts.map(([label, key, v]) => `
    <div class="comp"><span>${label} <span class="muted">×${w[key].toFixed(2)}</span></span>
      <span class="cbar"><i style="width:${Math.min(100, v * 100)}%;background:${C.teal}"></i></span><span class="v">${v.toFixed(2)}</span></div>`).join("");
  const sum = parts.reduce((s, [, key, v]) => s + w[key] * v, 0);
  const terms = parts.map(([, key, v]) => `${w[key].toFixed(2)}×${v.toFixed(2)}`).join(" + ");
  const pop = $("#cell-pop");
  pop.innerHTML = `
    <button class="x" aria-label="Close" onclick="document.getElementById('cell-pop').hidden = true">×</button>
    <div class="kicker">${ch.hop} hop${ch.hop > 1 ? "s" : ""} from the disaster</div>
    <h4>${c.name} · ${c.ind}</h4>
    <div style="font-size:24px;font-weight:300;color:${heat(c.score)}">${c.score.toFixed(2)} <span class="muted" style="font-size:12px">impact score</span></div>
    <p class="why">${why}</p>
    ${rows}
    <div class="formula-line">(${terms}) × ${decay}<sup>${ch.hop}</sup><br>= ${sum.toFixed(3)} × ${Math.pow(decay, ch.hop).toFixed(2)} = <b>${c.score.toFixed(2)}</b></div>`;
  pop.hidden = false;
  const box = e.target.getBoundingClientRect ? e.target.getBoundingClientRect() : { left: e.clientX, top: e.clientY, right: e.clientX };
  const left = Math.min(window.innerWidth - pop.offsetWidth - 12, Math.max(12, box.right + 12));
  const top = Math.max(12, Math.min(window.innerHeight - pop.offsetHeight - 12, box.top - pop.offsetHeight / 2));
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}

// ---------------------------------------------------------------- every value in a table
function openTable() {
  const r = state.result;
  if (!r) return;
  const names = iso => (state.countries.get(iso) || {}).name || iso;
  $("#tbl-title").textContent = $("#map-title").textContent;
  $("#tbl-help").innerHTML = `<b>Impact</b> (0–1) combines severity, dependency, trade value, centrality and duration, and fades by
    ${Math.round((1 - r.parameters.decay) * 100)}% per hop. <b>Dependency</b> is the share of this country's imports of that product
    that traces back to the hit country (shares multiplied along the chain). <b>Trade value</b> is the yearly value of the last link.`;
  const head = `<tr><th>#</th><th>Country</th><th>Hops</th><th>Impact</th><th>Strongest chain</th><th>Product</th>
    <th>Dependency</th><th>Trade value</th><th>Industries exposed</th></tr>`;
  const src = r.sources.map(s => `<tr><td></td><td><span class="dotc" style="background:${C.red}"></span>${s.name}</td>
    <td class="num">0</td><td class="num" style="color:${C.red}">hit</td><td colspan="5" class="ind">
    ${s.ports.length ? "Major ports: " + s.ports.map(p => p.name).join(", ") : "Directly hit"}</td></tr>`).join("");
  const rows = r.affected.map((a, i) => {
    const ch = a.chains[0];
    const inds = [...new Set(a.chains.flatMap(x => x.industries))].join(", ");
    return `<tr><td class="num">${i + 1}</td>
      <td><span class="dotc" style="background:${heat(a.score)}"></span>${a.name}</td>
      <td class="num">${a.hop}</td><td class="num" style="color:${heat(a.score)}">${a.score.toFixed(3)}</td>
      <td>${ch.path.map(names).join(" → ")}</td><td>${ch.product}</td>
      <td class="num">${pct(ch.dependency)}</td><td class="num">${d3.format("$.3s")(ch.value_usd || 0).replace("G", "B")}</td>
      <td class="ind">${inds}</td></tr>`;
  }).join("");
  $("#tbl").innerHTML = `<thead>${head}</thead><tbody>${src}${rows}</tbody>`;
  $("#table-modal").hidden = false;
}

// ---------------------------------------------------------------- welcome card + guided tour
const TOUR = [
  { sel: ".filters", title: "1. Pick what to look at",
    text: "Choose one of <b>556 real disasters</b> from 2019–2023, or switch to <b>Simulator</b> and knock out any country yourself." },
  { sel: "#map", title: "2. Watch the impact spread",
    text: "The <b>red</b> country is where it hit. Countries that buy from it light up in waves - the redder, the harder they're hit. " +
          "Lines are the trade links it travels along. <b>Hover</b> any country for details." },
  { sel: "#stack", title: "3. Who is hit hardest",
    text: "Ranked by <b>impact score</b> (0 to 1). It combines how bad the event was, how much the country depends on the " +
          "hit country, how much trade is at stake, how central it is, and how long it lasts." },
  { sel: ".toolbar", title: "4. How far it travelled",
    text: "<b>Hops</b> count the steps: 1 hop = direct buyers of the hit country, 2 hops = their buyers. " +
          "The impact fades at every hop. Press <b>↻</b> to replay the animation." },
  { sel: "#gauges", title: "5. The key numbers",
    text: "How many countries are affected, the highest impact score, and how severe the event was. " +
          "<b>Cyan</b> means our own weather data showed it was worse than the official alert." },
  { sel: "#insight", title: "6. The story in one sentence",
    text: "A plain-language summary. For Typhoon Hagibis: the official alert said <b>minor</b>, but our port weather data " +
          "recorded <b>162 km/h</b> winds at Tokyo - so the system raised it. One data source alone would have missed it." },
  { sel: ".hero .mini", title: "7. Five years of context",
    text: "Every disaster per week since 2019. The <b>red line</b> shows where the current event sits in time." },
  { sel: ".matrix-card", title: "8. Which industries are exposed",
    text: "Industries (rows) in affected countries (columns). <b>Click any dot</b> for the full breakdown, " +
          "<b>Values</b> to print every number, or <b>All values</b> for the complete table." },
  { sel: ".alerts-card", title: "9. The big picture",
    text: "All 48,802 disasters by alert level. The last card counts events our weather data found to be worse than reported." },
  { sel: ".anoms-card", title: "10. Unusual trade drops",
    text: "Trade flows that fell in a strange way, found by machine learning (Isolation Forest). " +
          "Press <b>Only hit country</b> to see the drops linked to the country hit by this event." },
  { sel: "#help-btn", title: "That's it!",
    text: "Press <b>?</b> any time to see this again. Every panel also has a small <b>i</b> button with an explanation." },
];
let tourAt = 0;

function tourShow(i) {
  tourAt = i;
  const step = TOUR[i];
  const target = document.querySelector(step.sel);
  $("#tour").hidden = false;
  target.scrollIntoView({ block: "center", behavior: "instant" });
  requestAnimationFrame(() => {
    const b = target.getBoundingClientRect(), pad = 6;
    Object.assign($("#tour-spot").style, { left: b.left - pad + "px", top: b.top - pad + "px",
                                           width: b.width + pad * 2 + "px", height: b.height + pad * 2 + "px" });
    $("#tour-step").textContent = `Step ${i + 1} of ${TOUR.length}`;
    $("#tour-title").textContent = step.title;
    $("#tour-text").innerHTML = step.text;
    $("#tour-back").hidden = i === 0;
    $("#tour-next").textContent = i === TOUR.length - 1 ? "Done" : "Next";
    // place the card next to the spotlight: right, left, below or above - whichever fits
    const card = $("#tour-card"), cw = card.offsetWidth, chh = card.offsetHeight, vw = window.innerWidth, vh = window.innerHeight;
    let left, top;
    if (b.right + 16 + cw < vw) { left = b.right + 16; top = b.top; }
    else if (b.left - 16 - cw > 0) { left = b.left - 16 - cw; top = b.top; }
    else if (b.bottom + 16 + chh < vh) { left = b.left; top = b.bottom + 16; }
    else { left = b.left; top = b.top - chh - 16; }
    card.style.left = Math.max(12, Math.min(vw - cw - 12, left)) + "px";
    card.style.top = Math.max(12, Math.min(vh - chh - 12, top)) + "px";
  });
}
function tourEnd() { $("#tour").hidden = true; window.scrollTo({ top: 0 }); }

function storeGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function storeSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode: just show it again next time */ } }

function bindHelp() {
  // "i" buttons: hover or focus on desktop, tap on touch screens
  document.addEventListener("mouseover", e => { const b = e.target.closest(".info"); if (b) showInfo(b); });
  document.addEventListener("mouseout", e => { if (e.target.closest(".info")) hideInfo(); });
  document.addEventListener("focusin", e => { const b = e.target.closest(".info"); if (b) showInfo(b); });
  document.addEventListener("focusout", e => { if (e.target.closest(".info")) hideInfo(); });
  document.addEventListener("click", e => {
    const b = e.target.closest(".info");
    if (b) { e.stopPropagation(); showInfo(b); } else hideInfo();
  }, true);

  $("#mx-values").addEventListener("click", e => {
    state.showValues = !state.showValues;
    e.currentTarget.setAttribute("aria-pressed", state.showValues);
    if (state.result) drawMatrix(state.result);
  });
  $("#mx-table").addEventListener("click", openTable);

  document.querySelectorAll(".modal").forEach(m => m.addEventListener("click", e => {
    if (e.target === m || e.target.closest("[data-close]")) { m.hidden = true; if (m.id === "welcome") storeSet("scx-welcome", "1"); }
  }));
  $("#help-btn").addEventListener("click", e => { e.stopPropagation(); $("#welcome").hidden = false; });
  $("#tour-start").addEventListener("click", () => { $("#welcome").hidden = true; storeSet("scx-welcome", "1"); tourShow(0); });
  $("#tour-next").addEventListener("click", () => tourAt < TOUR.length - 1 ? tourShow(tourAt + 1) : tourEnd());
  $("#tour-back").addEventListener("click", () => tourShow(Math.max(0, tourAt - 1)));
  $("#tour-skip").addEventListener("click", tourEnd);
  document.addEventListener("keydown", e => {
    if (e.key === "Escape") { tourEnd(); document.querySelectorAll(".modal").forEach(m => { m.hidden = true; }); }
    if (!$("#tour").hidden && e.key === "ArrowRight") $("#tour-next").click();
    if (!$("#tour").hidden && e.key === "ArrowLeft" && tourAt > 0) $("#tour-back").click();
  });
  window.addEventListener("resize", () => { if (!$("#tour").hidden) tourShow(tourAt); });

  if (!storeGet("scx-welcome")) $("#welcome").hidden = false;  // first visit
}

init().catch(err => { console.error(err); $("#map-title").textContent = "Could not load: " + err.message; });

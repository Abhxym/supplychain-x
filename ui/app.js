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
                showArcs: true, showMarkers: true, animStart: 0, raf: null };
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
    <div class="head"><span>Most affected</span><span class="warn">
      <svg width="12" height="12" viewBox="0 0 12 12"><path d="M6 1L11 10H1Z" fill="${C.orange}"/></svg>${r.summary.countries}</span></div>
    ${top.map((a, i) => `<div class="person" style="animation-delay:${animated ? a.hop * HOP + 300 + i * 90 : 0}ms"
        title="${a.chains[0].path.join(" → ")} · ${a.chains[0].product}">
      <span class="av" style="border-color:${heat(a.score)}">${a.iso3}</span>
      <span class="nm">${a.name}</span><span class="sc" style="color:${heat(a.score)}">${a.score.toFixed(2)}</span></div>`).join("")}`;
}

function gauge(el, { label, value, max, text, sub, color }) {
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
    <div class="g-l">${label}</div>
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
             text: r.summary.countries, sub: "/ " + state.countries.size, color: C.teal });
  gauge(b, { label: "Peak impact score", value: peak, max: 0.5, text: peak.toFixed(2), sub: "/ 1.0", color: heat(peak) });
  gauge(c, { label: raised ? "Severity (weather-raised)" : "Severity used", value: p.severity_used, max: 1,
             text: p.severity_used.toFixed(2), sub: raised ? "was " + p.severity_in.toFixed(2) : "/ 1.0",
             color: raised ? C.cyan : C.orange });
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
    if (!cells.has(k) || ch.score > cells.get(k).score) cells.set(k, { ind, iso3: a.iso3, score: ch.score, product: ch.product });
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
  svg.append("g").selectAll("circle").data(data).join("circle")
    .attr("cx", c => x(c.iso3)).attr("cy", c => y(c.ind)).attr("r", 0)
    .attr("fill", c => heat(c.score)).attr("fill-opacity", 0.9)
    .call(sel => sel.append("title").text(c => `${c.iso3} · ${c.ind} (via ${c.product}): ${c.score.toFixed(2)}`))
    .transition().delay((_, i) => 200 + i * 15).duration(400).attr("r", c => 2.5 + c.score * 13);

  // label the hottest cell, like an incident chip
  const hot = d3.greatest(data, c => c.score);
  if (hot) {
    const label = `${hot.iso3} · ${hot.ind}  ${hot.score.toFixed(2)}`;
    const lw = label.length * 6 + 22;
    const lx = Math.min(w - lw - 4, x(hot.iso3) + 14), ly = Math.max(2, y(hot.ind) - 30);
    const g = svg.append("g");
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

init().catch(err => { console.error(err); $("#map-title").textContent = "Could not load: " + err.message; });

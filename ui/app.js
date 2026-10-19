// SUPPLYCHAIN-X Cascade Explorer
// Draws the impact engine's cascade on a world map: the hit country glows red, supply links
// animate outward hop by hop, and every affected country is coloured by its impact score.

const WORLD = "https://cdn.jsdelivr.net/npm/world-atlas@2.0.2/countries-110m.json";
const HOP_DELAY = 1100; // ms between cascade waves
// countries too small for the 110m map: [lon, lat]
const FALLBACK = { SGP: [103.82, 1.35], HKG: [114.17, 22.3], BHR: [50.55, 26.07], MLT: [14.4, 35.9],
                   MUS: [57.55, -20.3], BRB: [-59.55, 13.15], MDV: [73.5, 4.2], ATG: [-61.8, 17.1] };

const state = { events: [], countries: new Map(), lonlat: new Map(), features: [], result: null,
                activeId: null, sim: [] };
const color = d3.scaleSequential(d3.interpolateRgbBasis(["#26365c", "#ffd166", "#ff9f1c", "#ff4d6d"]))
  .domain([0.08, 0.45]).clamp(true);
const money = v => !v ? "–" : d3.format("$.2s")(v).replace("G", "B");
const pct = v => Math.round(v * 100) + "%";
const $ = s => document.querySelector(s);

const svg = d3.select("#map");
const gLand = svg.append("g");
const gArcs = svg.append("g");
const gNodes = svg.append("g");
let projection, geoPath;

// ---------------------------------------------------------------- setup
async function init() {
  const [world, countries] = await Promise.all([
    d3.json(WORLD),
    fetch("/api/countries").then(r => r.json()),
  ]);
  countries.forEach(c => state.countries.set(c.iso3, c));
  const byNumeric = new Map(countries.filter(c => c.numeric).map(c => [c.numeric, c.iso3]));
  state.features = topojson.feature(world, world.objects.countries).features
    .filter(f => f.id !== "010") // Antarctica
    .map(f => Object.assign(f, { iso3: byNumeric.get(f.id) }));

  state.features.forEach(f => { if (f.iso3) state.lonlat.set(f.iso3, mainCentroid(f)); });
  countries.forEach(c => {
    if (state.lonlat.has(c.iso3)) return;
    if (FALLBACK[c.iso3]) state.lonlat.set(c.iso3, FALLBACK[c.iso3]);
    else if (c.port_lon != null) state.lonlat.set(c.iso3, [c.port_lon, c.port_lat]);
  });

  $("#country-list").innerHTML = countries
    .map(c => `<option value="${c.name} (${c.iso3})"></option>`).join("");

  drawBase();
  new ResizeObserver(() => { drawBase(); if (state.result) render(state.result, false); }).observe($(".map-wrap"));
  bindUI();
  await loadEvents();
  const start = state.events.find(e => e.event_id === "TC-1000611") || state.events[0]; // Typhoon Hagibis
  if (start) openEvent(start.event_id);
}

// the biggest landmass's centre, so France isn't placed in the Atlantic because of French Guiana
function mainCentroid(f) {
  if (f.geometry.type !== "MultiPolygon") return d3.geoCentroid(f);
  const polys = f.geometry.coordinates.map(c => ({ type: "Polygon", coordinates: c }));
  return d3.geoCentroid(d3.greatest(polys, p => d3.geoArea(p)));
}

function drawBase() {
  const { width, height } = $(".map-wrap").getBoundingClientRect();
  svg.attr("viewBox", `0 0 ${width} ${height}`);
  // fit to the land, not the whole globe - the polar ocean is just empty space
  projection = d3.geoNaturalEarth1()
    .fitExtent([[16, 16], [width - 16, height - 16]], { type: "FeatureCollection", features: state.features });
  geoPath = d3.geoPath(projection);

  gLand.selectAll("path.sphere").data([{ type: "Sphere" }]).join("path")
    .attr("class", "sphere").attr("d", geoPath).attr("fill", "#0a1224").attr("stroke", "#16213b");
  gLand.selectAll("path.land").data(state.features, f => f.id).join("path")
    .attr("class", "land").attr("d", geoPath)
    .on("mousemove", (e, f) => hoverCountry(e, f.iso3))
    .on("mouseleave", hideTip);
}

const xy = iso3 => { const ll = state.lonlat.get(iso3); return ll ? projection(ll) : null; };

// ---------------------------------------------------------------- render a cascade
function render(r, animate = true) {
  state.result = r;
  $("#empty").hidden = true;
  $("#replay").hidden = false;
  const t = animate ? 1 : 0;
  const sources = new Set(r.sources.map(s => s.iso3));
  const affected = new Map(r.affected.map(a => [a.iso3, a]));

  gLand.selectAll("path.land")
    .classed("hit", f => sources.has(f.iso3))
    .transition().duration(600 * t)
    .delay(f => affected.has(f.iso3) ? affected.get(f.iso3).hop * HOP_DELAY * t : 0)
    .style("fill", f => sources.has(f.iso3) ? null : affected.has(f.iso3) ? color(affected.get(f.iso3).score) : null);

  // one arc per supply link used by a cascade, coloured by how far out it is
  const links = new Map();
  r.affected.forEach(a => a.chains.slice(0, 2).forEach(ch => {
    for (let i = 0; i < ch.path.length - 1; i++) {
      const key = ch.path[i] + ">" + ch.path[i + 1];
      const prev = links.get(key);
      if (!prev || ch.shares[i] > prev.share)
        links.set(key, { a: ch.path[i], b: ch.path[i + 1], hop: i + 1, share: ch.shares[i], product: ch.product });
    }
  }));
  const arcs = [...links.values()].filter(l => xy(l.a) && xy(l.b)).sort((x, y) => x.hop - y.hop);

  gArcs.selectAll("path").remove();
  gArcs.selectAll("path").data(arcs).join("path")
    .attr("class", "arc")
    .attr("d", l => curve(xy(l.a), xy(l.b)))
    .attr("stroke", l => l.hop === 1 ? "#ff9f1c" : "#ffd166")
    .attr("stroke-width", l => 0.8 + l.share * 5)
    .attr("stroke-opacity", l => l.hop === 1 ? 0.85 : 0.6)
    .each(function (l, i) {
      const len = this.getTotalLength();
      d3.select(this).attr("stroke-dasharray", `${len} ${len}`).attr("stroke-dashoffset", t ? len : 0)
        .transition().delay(((l.hop - 1) * HOP_DELAY + i * 12) * t).duration(900 * t).ease(d3.easeCubicOut)
        .attr("stroke-dashoffset", 0);
    });

  // affected countries as glowing dots, sized by impact
  const nodes = r.affected.filter(a => xy(a.iso3));
  gNodes.selectAll("*").remove();
  gNodes.selectAll("circle.aff").data(nodes).join("circle")
    .attr("class", "aff")
    .attr("cx", a => xy(a.iso3)[0]).attr("cy", a => xy(a.iso3)[1])
    .attr("fill", a => color(a.score)).attr("stroke", "#0a1020").attr("stroke-width", 1)
    .attr("r", 0)
    .on("mousemove", (e, a) => hoverCountry(e, a.iso3))
    .on("mouseleave", hideTip)
    .transition().delay(a => (a.hop * HOP_DELAY + 300) * t).duration(500 * t)
    .attr("r", a => 3 + a.score * 14);

  // the hit countries: pulsing rings + their major ports
  r.sources.filter(s => xy(s.iso3)).forEach(s => {
    const [x, y] = xy(s.iso3);
    gNodes.append("circle").attr("class", "ring").attr("cx", x).attr("cy", y).attr("r", 10);
    gNodes.append("circle").attr("class", "node-src").attr("cx", x).attr("cy", y).attr("r", 6)
      .on("mousemove", e => hoverCountry(e, s.iso3)).on("mouseleave", hideTip);
    s.ports.forEach(p => {
      const pp = projection([p.longitude, p.latitude]);
      if (pp) gNodes.append("circle").attr("class", "port").attr("cx", pp[0]).attr("cy", pp[1]).attr("r", 3)
        .append("title").text(p.name);
    });
  });

  renderWaves(r, t);
  renderDetail(r);
}

function renderWaves(r, t) {
  const waves = [{ title: "Hit", rows: r.sources.map(s => ({ name: s.name, iso3: s.iso3, score: null })) }];
  for (let h = 1; h <= 3; h++) {
    const rows = r.affected.filter(a => a.hop === h);
    if (rows.length || h === 1) waves.push({ title: h + (h === 1 ? " hop" : " hops"), rows });
  }
  const el = $("#waves");
  el.hidden = false;
  el.innerHTML = waves.map((w, i) => `
    <div class="wave"><h5><span>${w.title}</span><span class="n">${w.rows.length}</span></h5>
      ${w.rows.slice(0, 8).map((a, j) => `<div class="pill" style="--c:${a.score == null ? "#ff4d6d" : color(a.score)};
          animation-delay:${t ? i * HOP_DELAY + j * 60 : 0}ms">
        <span>${a.name}</span><span class="mono">${a.score == null ? "hit" : a.score.toFixed(2)}</span></div>`).join("")}
      ${w.rows.length > 8 ? `<div class="more">+ ${w.rows.length - 8} more</div>` : ""}
      ${!w.rows.length ? '<div class="more">none above the share threshold</div>' : ""}
    </div>`).join("");
}

function curve([x1, y1], [x2, y2]) {
  const dx = x2 - x1, dy = y2 - y1, d = Math.hypot(dx, dy);
  const mx = (x1 + x2) / 2 - dy * 0.22, my = (y1 + y2) / 2 + dx * 0.22 - d * 0.08;
  return `M${x1},${y1} Q${mx},${my} ${x2},${y2}`;
}

// ---------------------------------------------------------------- tooltip
function hoverCountry(e, iso3) {
  if (!iso3 || !state.result) return;
  const c = state.countries.get(iso3);
  const a = state.result.affected.find(x => x.iso3 === iso3);
  const src = state.result.sources.find(s => s.iso3 === iso3);
  let html = `<b>${(c && c.name) || iso3}</b>`;
  if (src) html += `<div class="muted">directly hit${src.ports.length ? " · ports: " + src.ports.map(p => p.name).join(", ") : ""}</div>`;
  else if (a) html += `<div>impact <span class="mono">${a.score.toFixed(2)}</span> · ${a.hop} hop${a.hop > 1 ? "s" : ""}</div>` +
    a.chains.slice(0, 3).map(chainHTML).map(h => `<div class="muted" style="margin-top:4px">${h}</div>`).join("");
  else html += `<div class="muted">not affected (no supply link ≥ ${pct(state.result.parameters.min_share)})</div>`;
  const tip = $("#tooltip");
  const box = $(".map-wrap").getBoundingClientRect();
  tip.innerHTML = html;
  tip.hidden = false;
  const x = e.clientX - box.left + 14, y = e.clientY - box.top + 14;
  tip.style.left = Math.min(x, box.width - tip.offsetWidth - 8) + "px";
  tip.style.top = Math.min(y, box.height - tip.offsetHeight - 8) + "px";
}
const hideTip = () => { $("#tooltip").hidden = true; };

function chainHTML(ch) {
  const steps = ch.path.map((iso, i) => i === 0 ? `<b>${iso}</b>` : ` →${pct(ch.shares[i - 1])}→ <b>${iso}</b>`).join("");
  return `${steps} · ${ch.product}`;
}

// ---------------------------------------------------------------- detail panel
function renderDetail(r) {
  const ev = r.event;
  const sev = r.parameters;
  const boosted = sev.severity_used > sev.severity_in;
  const title = ev ? ev.title : "What if " + r.sources.map(s => s.name).join(" + ") + " is disrupted?";
  const meta = ev
    ? `<span class="badge ${ev.alert_level}">GDACS ${ev.alert_level}</span><span>${ev.start_ts.slice(0, 10)}</span>
       <span>· ${ev.countries.join(", ")}</span>`
    : `<span class="badge boost">simulation</span><span>severity ${sev.severity_used.toFixed(2)} · ${sev.duration_days} days</span>`;

  const weather = r.weather_evidence.length ? `
    <div class="card weather">
      <h4>Our weather data ${boosted ? "raised the severity" : "confirms it"}</h4>
      ${boosted ? `<div style="margin-bottom:8px">GDACS said <b>${sev.severity_in.toFixed(2)}</b> → engine used <b>${sev.severity_used.toFixed(2)}</b></div>` : ""}
      ${r.weather_evidence.slice(0, 5).map(w => `<div class="wx"><span>${w.port} · ${w.date}</span>
        <span class="mono">${w.gust_kmh} km/h · ${w.rain_mm} mm</span></div>`).join("")}
    </div>` : "";

  const top = r.affected.slice(0, 12);
  const max = d3.max(top, a => a.score) || 1;
  const rank = top.map(a => `
    <li>
      <div class="r1"><span><span class="who">${a.name}</span><span class="hop">${a.hop} hop${a.hop > 1 ? "s" : ""}</span></span>
        <span class="sc" style="color:${color(a.score)}">${a.score.toFixed(2)}</span></div>
      <div class="chain">${chainHTML(a.chains[0])}</div>
      <div class="bar"><i style="width:${(a.score / max) * 100}%;background:${color(a.score)}"></i></div>
    </li>`).join("");

  const inds = r.industries.slice(0, 12).map(i => `<span class="ind">${i.iso3} · ${i.industry}</span>`).join("");

  $("#detail").innerHTML = `
    <div class="d-head">
      <div class="kicker">${ev ? "Historical event" : "What-if simulation"}</div>
      <h2>${title}</h2>
      <div class="meta">${meta}</div>
    </div>
    <div class="kpis">
      <div class="kpi"><div class="v">${r.summary.countries}</div><div class="l">countries in the cascade</div></div>
      <div class="kpi"><div class="v">${r.summary.max_hop}</div><div class="l">cascade depth (hops)</div></div>
      <div class="kpi"><div class="v">${money(r.summary.exposure_usd)}</div><div class="l">yearly trade on affected links</div></div>
      <div class="kpi"><div class="v" style="color:${color(max)}">${max.toFixed(2)}</div><div class="l">highest impact score</div></div>
    </div>
    ${weather}
    <div class="card"><h4>Most affected</h4>${top.length ? `<ul class="rank">${rank}</ul>` :
      `<div class="muted">No country relies on the hit country for ≥ ${pct(sev.min_share)} of any product.</div>`}</div>
    ${inds ? `<div class="card"><h4>Industries exposed</h4><div class="inds">${inds}</div></div>` : ""}`;
}

// ---------------------------------------------------------------- events + simulator
async function loadEvents() {
  state.events = await fetch("/api/events?limit=600").then(r => r.json());
  renderEvents();
}

function renderEvents() {
  const q = $("#q").value.trim().toLowerCase();
  const list = state.events.filter(e => !q || (e.title + " " + (e.sources || []).join(" ")).toLowerCase().includes(q));
  $("#ev-count").textContent = `${list.length} scored events`;
  const max = d3.max(state.events, e => e.max_score) || 1;
  $("#events").innerHTML = list.slice(0, 250).map(e => `
    <li class="ev ${e.event_id === state.activeId ? "active" : ""}" data-id="${e.event_id}">
      <div class="row1"><span class="title">${e.title}</span><span class="score">${e.max_score.toFixed(2)}</span></div>
      <div class="row2"><span class="badge ${e.alert_level}">${e.alert_level}</span>
        ${e.severity_used > e.severity_in ? '<span class="badge boost">⚡ weather</span>' : ""}
        <span>${e.start_ts.slice(0, 10)}</span><span>· ${(e.sources || []).slice(0, 3).join(", ")}</span></div>
      <div class="bar"><i style="width:${(e.max_score / max) * 100}%"></i></div>
    </li>`).join("");
}

async function openEvent(id) {
  state.activeId = id;
  renderEvents();
  const r = await fetch("/api/impact/" + id).then(r => r.json());
  $("#f-decay").textContent = r.parameters.decay;
  render(r);
}

function renderChips() {
  $("#sim-chips").innerHTML = state.sim.map(iso =>
    `<span class="chip">${(state.countries.get(iso) || {}).name || iso}<button data-rm="${iso}" aria-label="remove">×</button></span>`).join("");
}

async function runSim() {
  if (!state.sim.length) { $("#sim-country").focus(); return; }
  const btn = $("#run");
  btn.disabled = true; btn.textContent = "Following the supply links…";
  const body = { countries: state.sim, severity: +$("#sev").value, duration_days: +$("#dur").value,
                 decay: +$("#decay").value, min_share: +$("#share").value };
  try {
    const r = await fetch("/api/simulate", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify(body) }).then(r => r.json());
    $("#f-decay").textContent = body.decay;
    render(r);
  } finally {
    btn.disabled = false; btn.textContent = "Simulate cascade";
  }
}

function bindUI() {
  document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.toggle("active", x === b));
    $("#events-pane").hidden = b.dataset.mode !== "events";
    $("#sim-pane").hidden = b.dataset.mode !== "sim";
  }));
  $("#q").addEventListener("input", renderEvents);
  $("#events").addEventListener("click", e => { const li = e.target.closest(".ev"); if (li) openEvent(li.dataset.id); });

  $("#sim-country").addEventListener("change", e => {
    const m = e.target.value.match(/\(([A-Z]{3})\)$/);
    if (m && !state.sim.includes(m[1])) { state.sim.push(m[1]); renderChips(); }
    e.target.value = "";
  });
  $("#sim-chips").addEventListener("click", e => {
    if (e.target.dataset.rm) { state.sim = state.sim.filter(x => x !== e.target.dataset.rm); renderChips(); }
  });
  document.querySelectorAll("[data-preset]").forEach(b => b.addEventListener("click", () => {
    state.sim = b.dataset.preset.split(","); renderChips(); runSim();
  }));
  const out = (id, f) => { const el = $("#" + id); const o = $("#" + id + "-out");
    const upd = () => { o.textContent = f(+el.value); }; el.addEventListener("input", upd); upd(); };
  out("sev", v => v.toFixed(2));
  out("dur", v => v + " days");
  out("decay", v => v.toFixed(2));
  out("share", v => Math.round(v * 100) + "%");
  $("#run").addEventListener("click", runSim);
  $("#replay").addEventListener("click", () => state.result && render(state.result, true));
}

init().catch(err => {
  $("#empty").textContent = "Could not load: " + err.message + " - is the API running?";
  console.error(err);
});

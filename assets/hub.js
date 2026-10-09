/* Research Hub front end: hash router + generic config-driven dashboard renderer.
   Data comes from data/*.json (written by fetch_data.py) or, in the single-file export,
   from window.HUB_INLINE. To add a dashboard: add a config in config/dashboards/, flip its
   area to "live" in config/hub.json, run refresh.sh. No front-end code changes needed. */
(function () {
  const TZ = "America/Chicago";
  const COLORS = ["#4ea1ff", "#f0883e", "#a371f7", "#3fb950", "#e3b341", "#ff7b72"];
  const ICONS = {
    globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg>',
    bank: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 9l9-5 9 5M4 9h16M5 9v9M9.5 9v9M14.5 9v9M19 9v9M3 20h18"/></svg>',
    table: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 9v11M15 9v11"/></svg>',
    pie: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3v9h9a9 9 0 1 1-9-9z"/><path d="M15 3.5A9 9 0 0 1 20.5 9H15z"/></svg>',
    curve: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 20V4M3 20h18"/><path d="M5 16c3-6 6-8 9-8.5S19 7 20 6.5"/></svg>',
    chart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 20h18M6 16l4-5 3 3 5-7"/><circle cx="18" cy="7" r="1.2"/></svg>'
  };
  const EXT = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.2" style="vertical-align:-1px"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';
  const app = document.getElementById("app"), crumbs = document.getElementById("crumbs"), stamp = document.getElementById("stamp");
  const INLINE = window.HUB_INLINE || null;
  const cache = {};
  let charts = [], range = localStorage.getItem("rh-range") || "5Y";

  async function load(name) {
    if (cache[name]) return cache[name];
    if (INLINE) return (cache[name] = INLINE[name]);
    const r = await fetch("data/" + name + ".json", { cache: "no-store" });
    if (!r.ok) throw new Error("data/" + name + ".json: HTTP " + r.status);
    return (cache[name] = await r.json());
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmtTime = iso => new Date(iso).toLocaleString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) + " CT";
  function fmtDate(s, freq) {
    const d = new Date(s + "T00:00:00Z");
    if (freq === "Quarterly") return "Q" + (Math.floor(d.getUTCMonth() / 3) + 1) + " " + d.getUTCFullYear();
    if (freq === "Monthly") return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", year: "numeric" });
    return d.toLocaleString("en-US", { timeZone: "UTC", month: "short", day: "numeric", year: "numeric" });
  }
  function fmtVal(v, f) {
    if (v == null) return "–";
    if (f === "pct1") return v.toFixed(1) + "%";
    if (f === "pct2") return v.toFixed(2) + "%";
    if (f === "pp2") return (v > 0 ? "+" : "") + v.toFixed(2) + " pp";
    if (f === "k0") return (v > 0 && v < 0 ? "" : "") + Math.round(v).toLocaleString() + "K";
    return v.toFixed(2);
  }
  function fmtChg(d, u) {
    const sgn = d > 0 ? "+" : d < 0 ? "−" : "±", a = Math.abs(d);
    if (u === "bp") return sgn + Math.round(a * 100) + " bp";
    if (u === "pp") return sgn + a.toFixed(1) + " pp";
    if (u === "k") return sgn + Math.round(a).toLocaleString() + "K";
    return sgn + a.toFixed(2);
  }
  function cls(d, s) {
    if (s.chg === "bp" || Math.abs(d) < 1e-9) return "flat";
    return (d > 0) !== !!s.invert ? "pos" : "neg";
  }
  function destroy() { charts.forEach(c => c.destroy()); charts = []; }

  async function route() {
    destroy();
    const [h, q] = location.hash.replace(/^#\/?/, "").split("?");
    const rq = new URLSearchParams(q || "").get("r"); if (["1Y", "5Y", "10Y", "Max"].includes(rq)) range = rq;
    const hub = await load("hub");
    const area = hub.areas.find(a => a.id === h);
    const link = (hub.links || []).find(l => l.id === h && l.embed);
    document.body.classList.toggle("embedded", !!link);
    window.scrollTo(0, 0);
    try {
      if (link) return embed(link);
      if (!area) return home(hub);
      crumbs.innerHTML = '<a href="#/">Hub</a> / ' + esc(area.title);
      if (area.status === "live") return dashboard(area);
      return soon(area);
    } catch (e) { app.innerHTML = '<p class="err">Failed to load: ' + esc(e.message) + "</p>"; }
  }

  async function home(hub) {
    crumbs.textContent = "";
    document.title = "Research Hub";
    app.innerHTML = '<h1>Research Hub</h1><p class="sub">Financials research workspace. Select an area.</p><div class="tiles">' +
      hub.areas.map(a => '<a class="tile" href="#/' + a.id + '"><span class="badge ' + (a.status === "live" ? "live\">LIVE" : "soon\">COMING SOON") + '</span><div class="ic">' + (ICONS[a.icon] || "") + "</div><h3>" + esc(a.title) + "</h3><p>" + esc(a.tagline) + "</p></a>").join("") + "</div>" +
      ((hub.links || []).length ? '<h2>Links</h2><div class="tiles">' + hub.links.map(l => (l.embed ? '<a class="tile ext" href="#/' + esc(l.id) + '" title="Opens inside the hub"><span class="badge ext">EMBEDDED</span>' : '<a class="tile ext" href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer" title="' + esc(l.url) + '"><span class="badge ext">EXTERNAL ' + EXT + '</span>') + '<div class="ic">' + (ICONS[l.icon] || "") + "</div><h3>" + esc(l.title) + "</h3><p>" + esc(l.tagline) + '</p><span class="url">' + esc(l.url.replace(/^https?:\/\//, "").replace(/\/$/, "")) + "</span></a>").join("") + "</div>" : "");
    const live = hub.areas.filter(a => a.status === "live");
    try { stamp.textContent = "Data last updated " + fmtTime(await lastChecked(live[0].id)); } catch (e) { stamp.textContent = ""; }
  }

  // last successful check time (data/status.json), falling back to the data file's own stamp
  async function lastChecked(id) {
    let st = null; try { st = await load("status"); } catch (e) {}
    const d = await load(id);
    return (st && st.dashboards && st.dashboards[id] && st.dashboards[id].checked_at) || d.updated_at;
  }

  function embed(l) {
    document.title = l.title + " · Research Hub";
    crumbs.innerHTML = '<a href="#/">Hub</a> / ' + esc(l.title);
    stamp.innerHTML = '<a class="btn sm" href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">Open in new tab ' + EXT + "</a>";
    app.innerHTML = '<iframe class="embed" src="' + esc(l.url) + '" title="' + esc(l.title) + '" loading="eager"></iframe>';
  }

  function soon(a) {
    document.title = a.title + " · Research Hub";
    stamp.textContent = "";
    app.innerHTML = '<div class="soonbox"><span class="badge soon" style="position:static">COMING SOON</span><h1 style="margin-top:12px">' + esc(a.title) + "</h1><p>" + esc(a.description) + '</p>' +
      (a.planned ? "<h2>Planned views</h2><ul>" + a.planned.map(p => "<li>" + esc(p) + "</li>").join("") + "</ul>" : "") + '<a class="btn" href="#/">Back to hub</a></div>';
  }

  function cutoff() {
    if (range === "Max") return null;
    const d = new Date(); d.setFullYear(d.getFullYear() - parseInt(range)); return d.getTime();
  }

  async function dashboard(area) {
    const D = await load(area.id), cfg = D.config, S = D.series;
    document.title = cfg.title + " · Research Hub";
    const chk = await lastChecked(area.id);
    stamp.innerHTML = "Last updated " + fmtTime(chk) + (chk !== D.updated_at ? '<br><span style="opacity:.75">FRED data last changed ' + fmtTime(D.updated_at) + "</span>" : "");
    const kpis = cfg.series.map(s => kpiCard(S[s.key])).join("");
    const secs = cfg.sections.map((sec, i) => "<h2>" + esc(sec.title) + '</h2><div class="panels">' + sec.panels.map((p, j) =>
      '<div class="panel' + (p.wide ? " wide" : "") + (p.full ? " full" : "") + '"><h4>' + esc(p.title) + '</h4><div class="cv"><canvas id="c' + i + "_" + j + '"></canvas></div><div class="src">FRED: ' + p.series.map(k => esc(S[k].fred)).join(", ") + "</div></div>").join("") + "</div>").join("");
    app.innerHTML = "<h1>" + esc(cfg.title) + '</h1><p class="sub">' + esc(cfg.subtitle) + '</p><div class="kpis">' + kpis + '</div><div class="toolbar"><span>Lookback</span><div class="seg">' +
      ["1Y", "5Y", "10Y", "Max"].map(r => '<button data-r="' + r + '" class="' + (r === range ? "on" : "") + '">' + r + "</button>").join("") + "</div></div>" + secs;
    app.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
      range = b.dataset.r; localStorage.setItem("rh-range", range);
      app.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x === b));
      drawAll(cfg, S);
    });
    drawAll(cfg, S);
  }

  function kpiCard(s) {
    if (!s || !s.latest) return '<div class="kpi failed"><div class="t">' + esc(s ? s.title : "?") + '</div><div class="v">n/a</div><div class="d err">' + esc(s && s.error || "no data") + "</div></div>";
    const L = s.latest, P = s.prior, Y = s.year_ago;
    let c = "";
    if (P) { const d = L.value - P.value; c += '<span class="' + cls(d, s) + '">' + fmtChg(d, s.chg) + " vs prior</span>"; }
    if (Y) { const d = L.value - Y.value; c += '<span class="' + cls(d, s) + '">' + fmtChg(d, s.chg) + " y/y</span>"; }
    return '<div class="kpi ' + (s.status !== "ok" ? s.status : "") + '" title="FRED ' + esc(s.fred) + (s.error ? " · " + esc(s.error) : "") + '"><div class="t">' + esc(s.title) + '</div><div class="v">' + fmtVal(L.value, s.fmt) +
      '</div><div class="d">' + fmtDate(L.date, s.freq) + (P ? " · prior " + fmtVal(P.value, s.fmt) : "") + (s.status === "stale" ? " · STALE" : "") + '</div><div class="c">' + c + "</div></div>";
  }

  function drawAll(cfg, S) {
    destroy();
    const cut = cutoff();
    const refLine = (y, label) => ({ id: "ref" + y, afterDraw(ch) {
      const sc = ch.scales.y; if (y < sc.min || y > sc.max) return;
      const ctx = ch.ctx, py = sc.getPixelForValue(y); ctx.save(); ctx.strokeStyle = "#8b9bb0"; ctx.setLineDash([4, 4]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(ch.chartArea.left, py); ctx.lineTo(ch.chartArea.right, py); ctx.stroke();
      if (label) { ctx.fillStyle = "#8b9bb0"; ctx.font = "11px sans-serif"; ctx.fillText(label, ch.chartArea.left + 4, py - 4); } ctx.restore(); } });
    cfg.sections.forEach((sec, i) => sec.panels.forEach((p, j) => {
      const el = document.getElementById("c" + i + "_" + j); if (!el) return;
      const datasets = p.series.map((k, n) => {
        const s = S[k]; let pts = (s.obs || []).map(o => ({ x: Date.parse(o[0] + "T00:00:00Z"), y: o[1] }));
        // quarterly series: pad the window one quarter so 1Y shows >= 4 quarters
        if (cut) { const c = s.freq === "Quarterly" ? cut - 100 * 864e5 : cut; pts = pts.filter(o => o.x >= c); }
        const col = COLORS[n % COLORS.length];
        const ds = { label: s.title, data: pts, borderColor: col, backgroundColor: p.type === "bar" ? pts.map(o => o.y < 0 ? "#f85149" : col) : (p.fill ? col + "22" : col), borderWidth: p.type === "bar" ? 0 : 1.6, pointRadius: 0, tension: 0, fill: p.fill ? "origin" : false };
        return ds;
      });
      const plugins = [];
      if (p.zero) plugins.push(refLine(0)); if (p.ref != null) plugins.push(refLine(p.ref, p.refLabel));
      const S0 = S[p.series[0]];
      charts.push(new Chart(el, {
        type: p.type === "bar" ? "bar" : "line", data: { datasets }, plugins,
        options: {
          parsing: false, normalized: true, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales: { x: { type: "time", time: { minUnit: "month", unit: (S0.freq === "Quarterly" && range === "1Y") ? "quarter" : undefined }, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 7 } }, y: { grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" } } },
          plugins: {
            decimation: { enabled: p.type !== "bar", algorithm: "lttb", samples: 600 },
            legend: { display: p.series.length > 1, labels: { color: "#e6edf3", boxWidth: 12 } },
            tooltip: { callbacks: { title: it => it.length ? fmtDate(new Date(it[0].parsed.x).toISOString().slice(0, 10), S0.freq) : "", label: it => it.dataset.label + ": " + fmtVal(it.parsed.y, S[p.series[it.datasetIndex]].fmt) } }
          }
        }
      }));
    }));
  }

  window.addEventListener("hashchange", route);
  route();
})();

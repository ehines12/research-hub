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
    if (f === "usd2") return "$" + v.toFixed(2);
    if (f === "n1") return v.toFixed(1);
    if (f === "m2") return v.toFixed(2) + "M";
    if (f === "bn0") return "$" + Math.round(v).toLocaleString() + "bn";
    return v.toFixed(2);
  }
  function fmtChg(d, u) {
    const sgn = d > 0 ? "+" : d < 0 ? "−" : "±", a = Math.abs(d);
    if (u === "bp") return sgn + Math.round(a * 100) + " bp";
    if (u === "pp") return sgn + a.toFixed(1) + " pp";
    if (u === "k") return sgn + Math.round(a).toLocaleString() + "K";
    if (u === "pctc") return sgn + a.toFixed(1) + "%";
    if (u === "usd") return sgn + "$" + a.toFixed(2);
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
    stamp.innerHTML = (l.source ? '<a class="srclink" href="' + esc(l.source.url) + '" target="_blank" rel="noopener noreferrer">Source: ' + esc(l.source.label) + " " + EXT + "</a>" : "") +
      '<a class="btn sm" href="' + esc(l.url) + '" target="_blank" rel="noopener noreferrer">Open in new tab ' + EXT + "</a>";
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
    const inSec = new Set(cfg.sections.flatMap(sec => sec.kpis || []));
    const kpis = D.kpis ? D.kpis.map(chipTile).join("") : cfg.series.filter(s => s.kpi !== false && !inSec.has(s.key)).map(s => kpiCard(S[s.key], S)).join("");
    const secs = cfg.sections.map((sec, i) => "<h2>" + esc(sec.title) + (sec.link ? ' <a class="hint" href="' + esc(sec.link) + '" target="_blank" rel="noopener noreferrer">source page ' + EXT + "</a>" : "") + "</h2>" +
      (sec.kpis ? '<div class="kpis sec">' + sec.kpis.map(k => kpiCard(S[k], S)).join("") + "</div>" : "") + (sec.nowcast_table ? nowcastTable(sec.nowcast_table, S) : "") + (sec.growth5y && D.growth5y ? '<div id="g5">' + growthTable(D.growth5y) + "</div>" : "") + (sec.quarterly && D.quarterly ? '<div id="qtr">' + quarterlyTable(D.quarterly, area.id) + "</div>" : "") + (sec.panels.length ? '<div class="panels' + (sec.cols === 2 ? " c2" : "") + '">' + sec.panels.map((p, j) =>
      '<div class="panel' + (p.wide ? " wide" : "") + (p.full ? " full" : "") + '"><h4>' + esc(p.title) + "</h4>" + (cfg.panel_latest ? panelLatest(p, S) : "") + '<div class="cv"><canvas id="c' + i + "_" + j + '"></canvas></div>' + (p.note ? '<div class="pnote">' + esc(p.note) + "</div>" : "") + '<div class="src">Source: ' + [...new Set(p.series.map(k => S[k].src_label || "FRED " + S[k].fred))].map(esc).join(" · ") + "</div></div>").join("") + "</div>" : "")).join("") +
      (D.summary ? summaryTable(D, cfg) : "");
    app.innerHTML = "<h1>" + esc(cfg.title) + '</h1><p class="sub">' + esc(cfg.subtitle) + '</p><div class="kpis">' + kpis + '</div><div class="toolbar"><span>Lookback</span><div class="seg">' +
      ["1Y", "5Y", "10Y", "Max"].map(r => '<button data-r="' + r + '" class="' + (r === range ? "on" : "") + '">' + r + "</button>").join("") + "</div></div>" + secs;
    app.querySelectorAll(".seg button").forEach(b => b.onclick = () => {
      range = b.dataset.r; localStorage.setItem("rh-range", range);
      app.querySelectorAll(".seg button").forEach(x => x.classList.toggle("on", x === b));
      drawAll(cfg, S);
    });
    const qb = app.querySelector("#qtr");
    if (qb) qb.addEventListener("click", e => {
      const b = e.target.closest("button[data-qv]"), dl = e.target.closest("button[data-csv]");
      if (b) { qView = b.dataset.qv; localStorage.setItem("rh-qview", qView); qb.innerHTML = quarterlyTable(D.quarterly, area.id); }
      if (dl) downloadCsv(D.quarterly, area.id);
    });
    const gb = app.querySelector("#g5");
    if (gb) gb.addEventListener("click", e => {
      const b = e.target.closest("button[data-gm],button[data-gb]"), dl = e.target.closest("button[data-gcsv]");
      if (b) { if (b.dataset.gm) gMetric = b.dataset.gm; if (b.dataset.gb) gBasis = b.dataset.gb; gb.innerHTML = growthTable(D.growth5y); g5scroll(); }
      if (dl) growthCsv(D.growth5y, area.id);
    });
    g5scroll();
    drawAll(cfg, S);
  }

  // ---- 5-year loan & deposit growth: EOP or quarter-average basis, YoY or compounded LQA ----
  let gMetric = "yoy", gBasis = "eop";
  function g5scroll() { const w = app.querySelector("#g5 .gwrap"); if (w) w.scrollLeft = w.scrollWidth; }  // open on the newest quarters
  const GB = { eop: "End of period (last weekly reading in quarter)", avg: "Quarter average" }, GM = { yoy: "YoY %", lqa: "LQA % (compounded)" };
  const shortD = s => fmtDate(s, "Daily").replace(/, \d{4}$/, "");
  function growthTable(G) {
    const seg = (attr, opts, cur) => '<div class="seg">' + Object.entries(opts).map(([k, l]) => '<button data-' + attr + '="' + k + '" class="' + (k === cur ? "on" : "") + '">' + l + "</button>").join("") + "</div>";
    let h = '<div class="qbar"><div class="gtg"><span class="glab">Basis</span>' + seg("gb", { eop: "EOP", avg: "Average" }, gBasis) + '<span class="glab">Metric</span>' + seg("gm", { yoy: "YoY %", lqa: "LQA %" }, gMetric) + "</div>" +
      '<div class="qdl"><button class="btn sm" data-gcsv="1">Download CSV</button>' + (INLINE ? "" : '<a class="btn sm" href="data/h8-growth5y.xlsx" download>Download Excel</a>') + "</div></div>" +
      '<div class="gcap">Showing <b>' + esc(GM[gMetric]) + "</b> on a <b>" + esc(GB[gBasis]) + "</b> basis · all commercial banks, SA · hover a cell for the $bn level and week · <i>scroll left for earlier quarters</i></div>" +
      '<div class="gwrap"><table class="sumtbl qtbl gtbl"><thead><tr><th class="sl">Series</th>' + G.columns.map(c => '<th class="r">' + esc(c.label) +
        (c.partial ? '<span class="qtag">QTD: ' + c.n + " wk" + (c.n > 1 ? "s" : "") + "</span>" : "") + (gBasis === "eop" ? '<span class="wk">wk ' + esc(shortD(c.eop_date)) + "</span>" : '<span class="wk">' + c.n + " wks avg</span>") + "</th>").join("") + "</tr></thead><tbody>";
    for (const r of G.rows) {
      const top = !r.lvl;
      h += '<tr class="' + (top ? "gtop" : "") + '"><td class="sl" title="FRED ' + esc(r.key) + '" style="padding-left:' + (10 + (r.lvl || 0) * 14) + 'px">' + esc(r.name) + (r.sa === "NSA" ? ' <span class="stl">NSA</span>' : "") + (r.status !== "ok" ? ' <span class="stl">' + esc(r.status.toUpperCase()) + "</span>" : "") + "</td>" +
        r.cells.map(c => { if (!c) return '<td class="r na">–</td>'; const b = c[gBasis], x = b[gMetric];
          const tip = (gBasis === "eop" ? "EOP week " + shortD(c.eop_date) : c.n + " weeks avg") + " · $" + b.level.toLocaleString("en-US", { maximumFractionDigits: 1 }) + "bn · YoY " + (b.yoy == null ? "n/a" : b.yoy.toFixed(2) + "%") + " · LQA " + (b.lqa == null ? "n/a" : b.lqa.toFixed(2) + "%");
          const k = x == null ? "na" : x > 0.005 ? "pos" : x < -0.005 ? "neg" : "flat";
          return '<td class="r ' + k + (c.partial ? " qtd" : "") + '" title="' + esc(tip) + '">' + (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(1) + "%") + "</td>"; }).join("") + "</tr>";
    }
    return h + "</tbody></table></div>" + (G.note ? '<div class="pnote">' + esc(G.note) + "</div>" : "");
  }
  function growthCsv(G, id) {
    const rows = [];
    for (const basis of ["eop", "avg"]) {
      const head = ["Basis", "Series", "FRED id", "SA/NSA"];
      G.columns.forEach(c => { const l = c.label + (c.partial ? " QTD" : ""); head.push(l + " level ($bn)", l + " YoY %", l + " LQA %", basis === "eop" ? l + " EOP week" : l + " weeks in qtr"); });
      rows.push(head);
      G.rows.forEach(r => { const row = [basis === "eop" ? "End of period" : "Quarter average", "  ".repeat(r.lvl || 0) + r.name, r.key, r.sa];
        r.cells.forEach(c => c ? row.push(c[basis].level, c[basis].yoy ?? "", c[basis].lqa ?? "", basis === "eop" ? c.eop_date : c.n) : row.push("", "", "", "")); rows.push(row); });
      rows.push([]);
    }
    if (G.note) rows.push([G.note]);
    const q = v => { v = String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    const blob = new Blob([rows.map(r => r.map(q).join(",")).join("\r\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = id + "-growth5y.csv"; document.body.appendChild(a); a.click(); a.remove();
  }

  // ---- quarterly table (quarter-average levels, YoY, compounded LQA) ----
  let qView = localStorage.getItem("rh-qview") || "yoy";
  function qCell(c, v) {
    if (!c) return '<td class="r na">–</td>';
    const tip = c.n + (c.partial ? " obs so far (QTD), through " : " obs, through ") + fmtDate(c.last, "Daily") + " · avg $" + c.level.toLocaleString("en-US", { maximumFractionDigits: 1 }) + "bn" +
      " · YoY " + (c.yoy == null ? "n/a" : c.yoy.toFixed(2) + "%") + " · LQA " + (c.lqa == null ? "n/a" : c.lqa.toFixed(2) + "%");
    let txt, k = "";
    if (v === "level") txt = c.level.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    else { const x = c[v]; if (x == null) txt = "–"; else { txt = (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x).toFixed(2) + "%"; k = x > 0.005 ? "pos" : x < -0.005 ? "neg" : "flat"; } }
    return '<td class="r ' + k + (c.partial ? " qtd" : "") + '" title="' + esc(tip) + '">' + txt + (c.partial ? "<sup>QTD</sup>" : "") + "</td>";
  }
  function quarterlyTable(Q, id) {
    const V = { level: "Level ($bn, qtr avg)", yoy: "YoY %", lqa: "LQA % (compounded)" };
    const cols = Q.columns, nc = cols.length;
    // column header: mark QTD and summarize how much of the quarter is in, per frequency
    const hdr = cols.map((c, i) => {
      const part = {}; Q.groups.forEach(g => g.rows.forEach(r => { const x = r.cells[i]; if (x && x.partial) part[r.freq] = x.n; }));
      const tag = Object.entries(part).map(([f, n]) => (f === "Monthly" ? "H.6 QTD: " + n + " of 3 mo" : "QTD: " + n + " wk" + (n > 1 ? "s" : ""))).join("; ");
      return '<th class="r">' + esc(c.label) + (tag ? '<span class="qtag">' + esc(tag) + "</span>" : "") + "</th>"; }).join("");
    let h = '<div class="qbar"><div class="seg">' + Object.entries(V).map(([k, l]) => '<button data-qv="' + k + '" class="' + (k === qView ? "on" : "") + '">' + l + "</button>").join("") + "</div>" +
      '<div class="qdl"><button class="btn sm" data-csv="1">Download CSV</button>' + (INLINE ? "" : '<a class="btn sm" href="data/' + esc(id) + '-quarterly.xlsx" download>Download Excel</a>') + "</div></div>" +
      '<div class="qwrap"><table class="sumtbl qtbl"><thead><tr><th class="sl">Series</th>' + hdr + "</tr></thead><tbody>";
    for (const g of Q.groups) {
      h += '<tr class="grp"><td class="sl" colspan="1">' + esc(g.title) + '</td><td colspan="' + nc + '"></td></tr>';
      for (const r of g.rows) {
        const ind = (r.name.match(/^ */) || [""])[0].length / 2;
        h += '<tr><td class="sl" style="padding-left:' + (10 + ind * 14) + 'px">' + esc(r.name.trim()) + ' <span class="sid">' + esc(r.key) + "</span>" + (r.sa === "NSA" ? ' <span class="stl">NSA</span>' : "") + (r.status !== "ok" ? ' <span class="stl">' + esc(r.status.toUpperCase()) + "</span>" : "") + "</td>" + r.cells.map(c => qCell(c, qView)).join("") + "</tr>";
      }
    }
    return h + "</tbody></table></div>" + (Q.note ? '<div class="pnote">' + esc(Q.note) + "</div>" : "");
  }
  function downloadCsv(Q, id) {
    const head = ["Group", "Series", "FRED id", "SA/NSA", "Frequency"];
    Q.columns.forEach(c => head.push(c.label + " avg level ($bn)", c.label + " YoY %", c.label + " LQA %", c.label + " obs in qtr", c.label + " partial (QTD)"));
    const rows = [head];
    Q.groups.forEach(g => g.rows.forEach(r => { const row = [g.title, r.name.trim(), r.key, r.sa || "SA", r.freq || ""];
      r.cells.forEach(c => c ? row.push(c.level, c.yoy ?? "", c.lqa ?? "", c.n, c.partial ? "QTD" : "") : row.push("", "", "", "", "")); rows.push(row); }));
    if (Q.note) rows.push([], [Q.note]);
    const q = v => { v = String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    const blob = new Blob([rows.map(r => r.map(q).join(",")).join("\r\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = id + "-quarterly.csv"; document.body.appendChild(a); a.click(); a.remove();
  }

  function kpiCard(s, S) {
    if (!s || !s.latest) return '<div class="kpi failed"><div class="t">' + esc(s ? s.title : "?") + '</div><div class="v">n/a</div><div class="d err">' + esc(s && s.error || "no data") + "</div></div>";
    const L = s.latest, P = s.prior, Y = s.year_ago;
    let c = "";
    const dv = (a, b) => s.chg === "pctc" ? (a / b - 1) * 100 : a - b;
    if (P) { const d = dv(L.value, P.value); c += '<span class="' + cls(d, s) + '">' + fmtChg(d, s.chg) + " vs prior</span>"; }
    if (Y) { const d = dv(L.value, Y.value); c += '<span class="' + cls(d, s) + '">' + fmtChg(d, s.chg) + " y/y</span>"; }
    const YK = s.yoy_key && S && S[s.yoy_key] && S[s.yoy_key].latest;  // y/y from a companion series (e.g. same-weekday TSA y/y)
    if (YK && YK.date === L.date) { const d = YK.value; c += '<span class="' + cls(d, s) + '">' + fmtChg(d, "pctc") + " y/y</span>"; }
    if (L.target) {  // nowcast: show target quarter, as-of date, change vs prior estimate for that quarter
      c = P ? '<span class="' + cls(L.value - P.value, s) + '">' + fmtChg(L.value - P.value, s.chg) + " vs " + fmtDate(P.date, "Daily").replace(/, \d{4}$/, "") + " est.</span>" : '<span class="flat">first estimate for ' + esc(L.target) + "</span>";
    }
    const tag = s.link ? "a" : "div", href = s.link ? ' href="' + esc(s.link) + '" target="_blank" rel="noopener noreferrer"' : "";
    const tip = (s.src_label || "FRED " + s.fred) + (L.release ? " · latest update after: " + L.release : "") + (s.error ? " · " + esc(s.error) : "");
    const dline = L.asof ? esc(L.target) + " · as of " + fmtDate(L.asof, "Daily").replace(/, \d{4}$/, "") + (L.mm != null ? " · m/m " + L.mm.toFixed(2) + "%" : "")
                : L.target ? esc(L.target) + " · as of " + fmtDate(L.date, "Daily") + (P ? " · prior " + fmtVal(P.value, s.fmt) : "")
                           : fmtDate(L.date, s.freq) + (P ? " · prior " + fmtVal(P.value, s.fmt) : "");
    return "<" + tag + href + ' class="kpi ' + (s.link ? "linked " : "") + (s.status !== "ok" ? s.status : "") + '" title="' + esc(tip) + '"><div class="t">' + esc(s.title) + (s.link ? " " + EXT : "") + '</div><div class="v">' + fmtVal(L.value, s.fmt) +
      '</div><div class="d">' + dline + (s.status === "stale" ? " · STALE" : "") + '</div><div class="c">' + c + "</div></" + tag + ">";
  }

  // Cleveland Fed-style nowcast table: rows = target periods still being nowcast, cols = measures
  function nowcastTable(t, S) {
    const rows = {};  // target label -> {kind, start, cells}
    const add = (kind, n, s) => { if (!s || !s.obs_meta) return;
      for (const [d, m] of Object.entries(s.obs_meta)) { if (!m.pending) continue;
        const r = rows[m.target] || (rows[m.target] = { kind, start: d, asof: m.asof, cells: {} });
        r.cells[n] = { v: (s.obs.find(o => o[0] === d) || [])[1], mm: m.mm }; if (m.asof > r.asof) r.asof = m.asof; } };
    t.measures.forEach((m, n) => { add("m", n, S[m.yy]); add("q", n, S[m.q]); });
    const order = Object.entries(rows).sort((a, b) => (a[1].kind === b[1].kind ? a[1].start.localeCompare(b[1].start) : a[1].kind === "m" ? -1 : 1));
    if (!order.length) return '<p class="err">No pending nowcasts found in the Cleveland Fed data.</p>';
    let h = '<div class="tblwrap ncw"><table class="sumtbl nctbl"><thead><tr><th>Target</th>' + t.measures.map(m => '<th class="r">' + esc(m.label) + "</th>").join("") + "<th>As of</th></tr></thead><tbody>";
    for (const [lab, r] of order) {
      h += "<tr><td>" + esc(lab) + ' <span class="sid">' + (r.kind === "m" ? "y/y · m/m" : "q/q SAAR") + "</span></td>" + t.measures.map((m, n) => { const c = r.cells[n];
        return '<td class="r b">' + (c && c.v != null ? c.v.toFixed(2) + "%" + (c.mm != null ? '<span class="mm">' + c.mm.toFixed(2) + "% m/m</span>" : "") : '<span class="sid">released</span>') + "</td>"; }).join("") +
        "<td>" + fmtDate(r.asof, "Daily") + "</td></tr>";
    }
    return h + "</tbody></table></div>" + (t.note ? '<div class="pnote">' + esc(t.note) + "</div>" : "");
  }

  // ---- config-driven extras (used by the H.8 / H.6 dashboard; Macro unaffected) ----
  function fmtLatest(code, v) {
    if (v == null) return "–";
    const n2 = x => x.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (code === "pct") return n2(v) + "%";
    if (code === "pp") return (v > 0 ? "+" : "") + n2(v) + " pp";
    if (code === "T") return "$" + n2(v) + "T";
    return n2(v);
  }
  function panelLatest(p, S) {
    return '<div class="plat">' + p.series.map((k, n) => {
      const s = S[k], lab = esc((p.labels && p.labels[n]) || (s && s.title) || k), sw = '<i style="background:' + COLORS[n % COLORS.length] + '"></i>';
      if (!s || !s.obs || !s.obs.length) return "<span>" + sw + lab + ": <b>unavailable</b></span>";
      const L = s.obs[s.obs.length - 1], v = L[1] * (p.scale || 1);
      return "<span>" + sw + lab + ": <b>" + (p.fmt ? fmtLatest(p.fmt[n], v) : v.toFixed(2)) + "</b> (" + fmtDate(L[0], s.freq) + ")" + (s.status !== "ok" ? ' <span class="stl">' + esc(s.status.toUpperCase()) + "</span>" : "") + "</span>";
    }).join("") + "</div>";
  }
  const sgn = v => (v > 0 ? "+" : v < 0 ? "−" : "±");
  function chgTxt(unit, c) {
    if (!c || c.value == null) return "–";
    const a = Math.abs(c.value);
    if (unit === "bp") return sgn(c.value) + Math.round(a).toLocaleString() + " bp";
    if (unit === "pct") return sgn(c.value) + a.toFixed(a < 10 ? 2 : 1) + "%";
    return sgn(c.value) + a.toFixed(2);
  }
  function chgCls(pol, c) {
    if (!c || c.value == null || Math.abs(c.value) < 1e-9) return "flat";
    if (!pol) return "neu";
    return (c.value > 0) === (pol > 0) ? "pos" : "neg";
  }
  function tileVal(fmt, v) {
    if (fmt === "tn") return "$" + (v / 1000).toFixed(2) + "T";
    if (fmt === "pct2") return v.toFixed(2) + "%";
    return fmtVal(v, fmt);
  }
  function chipTile(t) {
    if (t.latest == null) return '<div class="kpi failed"><div class="t">' + esc(t.label) + '</div><div class="v">n/a</div><div class="d err">series unavailable</div></div>';
    const chips = ["1w", "1m", "1y"].map(h => { const c = t.chg && t.chg[h];
      const tip = c ? "vs " + fmtDate(c.vs_date, t.freq) + ": " + tileVal(t.fmt, c.vs_value) : "not meaningful at this frequency";
      return '<div title="' + esc(tip) + '"><span>' + h.toUpperCase() + '</span><b class="' + chgCls(t.polarity, c) + '">' + chgTxt(t.unit, c) + "</b></div>"; }).join("");
    return '<div class="kpi chip ' + (t.status !== "ok" ? t.status : "") + '" title="' + esc((t.src_label || "FRED") + " · " + t.key) + '"><div class="t">' + esc(t.label) + '</div><div class="v">' + tileVal(t.fmt, t.latest) +
      '</div><div class="d">as of ' + fmtDate(t.asof, t.freq) + " · " + esc(t.freq || "") + (t.status === "stale" ? " · STALE" : "") + '</div><div class="chips">' + chips + "</div></div>";
  }
  function summaryTable(D, cfg) {
    const H = ["1w", "1m", "3m", "1y"]; let sec = null;
    let h = "<h2>" + esc(cfg.summary_title || "Summary") + (cfg.summary_note ? ' <span class="hint">' + esc(cfg.summary_note) + "</span>" : "") + '</h2><div class="tblwrap"><table class="sumtbl"><thead><tr><th>Series</th><th class="r">Latest</th><th>As of</th><th>Chg in</th>' + H.map(x => '<th class="r">' + x.toUpperCase() + "</th>").join("") + "</tr></thead><tbody>";
    for (const r of D.summary) {
      if (r.section !== sec) { sec = r.section; h += '<tr class="grp"><td colspan="8">' + esc(sec) + "</td></tr>"; }
      if (r.missing) { h += "<tr><td>" + esc(r.name) + ' <span class="sid">' + esc(r.id) + '</span></td><td colspan="7" class="err">series unavailable</td></tr>'; continue; }
      h += "<tr><td>" + esc(r.name) + ' <span class="sid">' + esc(r.id) + "</span>" + (r.status !== "ok" ? ' <span class="stl">' + esc(r.status.toUpperCase()) + "</span>" : "") + '</td><td class="r b">' + esc(r.latest_fmt) + "</td><td>" + fmtDate(r.asof, r.freq) + '</td><td class="cu">' + esc(r.change_unit) + "</td>" +
        H.map(x => { const c = r.chg[x]; return '<td class="r ' + chgCls(r.polarity, c) + '" title="' + esc(c ? "vs " + fmtDate(c.vs_date, r.freq) + " (" + c.vs_value.toFixed(2) + ")" : "not meaningful at this frequency") + '">' + esc(r.chg_fmt[x]) + "</td>"; }).join("") + "</tr>";
    }
    return h + "</tbody></table></div>";
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
        const s = S[k], sc = p.scale || 1; let pts = (s.obs || []).map(o => ({ x: Date.parse(o[0] + "T00:00:00Z"), y: +(o[1] * sc).toFixed(4) }));
        // quarterly series: pad the window one quarter so 1Y shows >= 4 quarters
        if (cut) { const c = s.freq === "Quarterly" ? cut - 100 * 864e5 : cut; pts = pts.filter(o => o.x >= c); }
        const col = COLORS[n % COLORS.length], t = (p.types && p.types[n]) || (p.type === "bar" ? "bar" : "line");
        const ds = { type: t, label: (p.labels && p.labels[n]) || s.title, data: pts, borderColor: t === "bar" ? col : (p.types ? "#f0883e" : col), backgroundColor: t === "bar" ? pts.map(o => o.y < 0 ? "#f85149" : col) : (p.fill ? col + "22" : col), borderWidth: t === "bar" ? 0 : (p.types ? 2 : 1.6), pointRadius: t === "line" && p.types ? 1.5 : 0, tension: 0, fill: p.fill ? "origin" : false, order: t === "line" ? 0 : 1 };
        if (p.stacked) {  // component bars / areas keep their own colour; a line overlays as the total
          Object.assign(ds, { borderColor: col, backgroundColor: t === "bar" ? col + "c0" : (p.fill ? col + "99" : col), stack: t === "line" && !p.fill ? "total" : "parts",
            borderWidth: p.fill ? 1 : (t === "bar" ? 0 : 2), pointRadius: 0, fill: p.fill ? (n === 0 ? "origin" : "-1") : false, barPercentage: 1, categoryPercentage: 1 });
        }
        if (p.y2 && p.y2.includes(k)) ds.yAxisID = "y2";
        return ds;
      });
      const plugins = [];
      if (p.zero) plugins.push(refLine(0)); if (p.ref != null) plugins.push(refLine(p.ref, p.refLabel));
      const S0 = S[p.series[0]];
      const yax = { grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" } };
      if (p.stacked) { yax.stacked = true; if (p.fill) { yax.min = 0; yax.max = 100; } }
      const scalesX = { type: "time", stacked: !!p.stacked, time: { minUnit: "month", unit: (S0.freq === "Quarterly" && range === "1Y") ? "quarter" : undefined }, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 7 } };
      const scales = { x: scalesX, y: yax };
      if (p.y2) scales.y2 = { position: "right", grid: { display: false }, ticks: { color: "#8b9bb0" } };
      charts.push(new Chart(el, {
        type: p.type === "bar" ? "bar" : "line", data: { datasets }, plugins,
        options: {
          parsing: false, normalized: true, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales,
          plugins: {
            decimation: { enabled: p.type !== "bar" && !p.types && !p.stacked, algorithm: "lttb", samples: 600 },
            legend: { display: p.series.length > 1 && !cfg.panel_latest, labels: { color: "#e6edf3", boxWidth: 12 } },
            tooltip: { callbacks: { title: it => it.length ? fmtDate(new Date(it[0].parsed.x).toISOString().slice(0, 10), S0.freq) : "", label: it => it.dataset.label + ": " + (p.fmt ? fmtLatest(p.fmt[it.datasetIndex], it.parsed.y) : fmtVal(it.parsed.y, S[p.series[it.datasetIndex]].fmt)) } }
          }
        }
      }));
    }));
  }

  window.addEventListener("hashchange", route);
  route();
})();

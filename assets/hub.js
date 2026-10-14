/* Research Hub front end: hash router + generic config-driven dashboard renderer.
   Data comes from data/*.json (written by fetch_data.py) or, in the single-file export,
   from window.HUB_INLINE. To add a dashboard: add a config in config/dashboards/, flip its
   area to "live" in config/hub.json, run refresh.sh. No front-end code changes needed. */
(function () {
  const TZ = "America/Chicago";
  const COLORS = ["#4ea1ff", "#f0883e", "#a371f7", "#3fb950", "#e3b341", "#ff7b72"];
  const ICONS = {
    gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-5"/><circle cx="12" cy="17" r="1.2"/></svg>',
    globe: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg>',
    bank: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M3 9l9-5 9 5M4 9h16M5 9v9M9.5 9v9M14.5 9v9M19 9v9M3 20h18"/></svg>',
    table: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 9v11M15 9v11"/></svg>',
    shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3l8 3v6c0 4.5-3.4 8.3-8 9-4.6-.7-8-4.5-8-9V6z"/><circle cx="12" cy="11" r="3"/><path d="M12 8v-2M12 16v-2M9 11H7M17 11h-2"/></svg>',
    odds: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="3" y="3" width="18" height="18" rx="3"/><path d="M8 16L16 8"/><circle cx="8.5" cy="8.5" r="1.6"/><circle cx="15.5" cy="15.5" r="1.6"/></svg>',
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
    if (cfg.kind === "predictions") return predictionsPage(area, D);
    if (cfg.kind === "bank_conditions") return bankPage(area, D);
    document.title = cfg.title + " · Research Hub";
    const chk = await lastChecked(area.id);
    stamp.innerHTML = "Last updated " + fmtTime(chk) + (chk !== D.updated_at ? '<br><span style="opacity:.75">FRED data last changed ' + fmtTime(D.updated_at) + "</span>" : "");
    const inSec = new Set(cfg.sections.flatMap(sec => sec.kpis || []));
    const kpis = D.kpis ? D.kpis.map(chipTile).join("") : cfg.series.filter(s => s.kpi !== false && !inSec.has(s.key)).map(s => kpiCard(S[s.key], S)).join("");
    const secs = cfg.sections.map((sec, i) => "<h2>" + esc(sec.title) + (sec.link ? ' <a class="hint" href="' + esc(sec.link) + '" target="_blank" rel="noopener noreferrer">source page ' + EXT + "</a>" : "") + "</h2>" + (sec.note ? '<p class="secnote">' + esc(sec.note) + "</p>" : "") +
      (sec.kpis ? '<div class="kpis sec' + (sec.kpi_cols === 3 ? " c3" : "") + '">' + sec.kpis.map(k => kpiCard(S[k], S)).join("") + "</div>" : "") + (sec.nowcast_table ? nowcastTable(sec.nowcast_table, S) : "") + (sec.growth5y && D.growth5y ? '<div id="g5">' + growthTable(D.growth5y) + "</div>" : "") + (sec.auctions ? auctionsTable(D.auctions) : "") + (sec.deposit_pricing ? depositTables(D.deposit_pricing) : "") + (sec.sloos ? '<div id="sloos">' + sloosTable(sec.sloos, S) + "</div>" : "") + (sec.quarterly && D.quarterly ? '<div id="qtr">' + quarterlyTable(D.quarterly, area.id) + "</div>" : "") + (sec.panels.length ? '<div class="panels' + (sec.cols === 2 ? " c2" : "") + '">' + sec.panels.map((p, j) =>
      '<div class="panel' + (p.wide ? " wide" : "") + (p.full ? " full" : "") + '"><h4>' + esc(p.title) + "</h4>" + (cfg.panel_latest ? panelLatest(p, S) : "") + '<div class="cv"><canvas id="c' + i + "_" + j + '"></canvas></div>' + (p.note ? '<div class="pnote">' + esc(p.note) + "</div>" : "") + '<div class="src">Source: ' + [...new Set(p.series.map(k => S[k].src_label || "FRED " + S[k].fred))].map(esc).join(" · ") + "</div></div>").join("") + "</div>" : "")).join("") +
      (D.summary ? summaryTable(D, cfg) : "");
    app.innerHTML = "<h1>" + esc(cfg.title) + '</h1><p class="sub">' + esc(cfg.subtitle) + '</p><div class="kpis">' + kpis + '</div><div class="toolbar"><span>Lookback</span><div class="seg">' +
      ["1Y", "5Y", "10Y", "Max"].map(r => '<button data-r="' + r + '" class="' + (r === range ? "on" : "") + '">' + r + "</button>").join("") + "</div></div>" + secs;
    app.querySelectorAll(".toolbar .seg button").forEach(b => b.onclick = () => {
      range = b.dataset.r; localStorage.setItem("rh-range", range);
      app.querySelectorAll(".toolbar .seg button").forEach(x => x.classList.toggle("on", x === b));
      drawAll(cfg, S);
    });
    const qb = app.querySelector("#qtr");
    if (qb) qb.addEventListener("click", e => {
      const b = e.target.closest("button[data-qv]"), dl = e.target.closest("button[data-csv]");
      const bk = e.target.closest("button[data-bk]");
      if (bk) { setBank(bk.dataset.bk); return; }
      if (b) { qView = b.dataset.qv; localStorage.setItem("rh-qview", qView); qb.innerHTML = quarterlyTable(D.quarterly, area.id); }
      if (dl) downloadCsv(D.quarterly, area.id);
    });
    const gb = app.querySelector("#g5");
    if (gb) gb.addEventListener("click", e => {
      const b = e.target.closest("button[data-gm],button[data-gb]"), dl = e.target.closest("button[data-gcsv]");
      const bk = e.target.closest("button[data-bk]");
      if (bk) { setBank(bk.dataset.bk); return; }
      if (b) { if (b.dataset.gm) gMetric = b.dataset.gm; if (b.dataset.gb) gBasis = b.dataset.gb; gb.innerHTML = growthTable(D.growth5y); g5scroll(); }
      if (dl) growthCsv(D.growth5y, area.id);
    });
    function setBank(k) {  // one bank-group selection drives both tables
      bankView = k; localStorage.setItem("rh-bank", k);
      if (qb) qb.innerHTML = quarterlyTable(D.quarterly, area.id);
      if (gb) { gb.innerHTML = growthTable(D.growth5y); g5scroll(); }
    }
    const sb = app.querySelector("#sloos");
    if (sb) sb.addEventListener("click", e => { if (e.target.closest("button[data-scsv]")) sloosCsv(cfg.sections.find(x => x.sloos).sloos, S); });
    g5scroll();
    drawAll(cfg, S);
  }

  // ---- 5-year loan & deposit growth: EOP or quarter-average basis, YoY or compounded LQA ----
  let gMetric = "yoy", gBasis = "eop", bankView = localStorage.getItem("rh-bank") || "S";
  const BANKS = { D: "Domestic total", L: "Large", S: "Small" }, BANKL = { D: "domestically chartered banks (total)", L: "large domestic banks", S: "small domestic banks" };
  const bankSeg = () => '<span class="glab">Banks</span><div class="seg">' + Object.entries(BANKS).map(([k, l]) => '<button data-bk="' + k + '" class="' + (k === bankView ? "on" : "") + '">' + l + "</button>").join("") + "</div>";
  const hasBanks = rows => rows.some(r => r.bank);
  function g5scroll() { const w = app.querySelector("#g5 .gwrap"); if (w) w.scrollLeft = w.scrollWidth; }  // open on the newest quarters
  const GB = { eop: "End of period (last weekly reading in quarter)", avg: "Quarter average" }, GM = { yoy: "YoY %", lqa: "LQA % (compounded)" };
  const shortD = s => fmtDate(s, "Daily").replace(/, \d{4}$/, "");
  function growthTable(G) {
    const seg = (attr, opts, cur) => '<div class="seg">' + Object.entries(opts).map(([k, l]) => '<button data-' + attr + '="' + k + '" class="' + (k === cur ? "on" : "") + '">' + l + "</button>").join("") + "</div>";
    const banked = hasBanks(G.rows), rows = banked ? G.rows.filter(r => r.bank === bankView) : G.rows;
    let h = '<div class="qbar"><div class="gtg">' + (banked ? bankSeg() : "") + '<span class="glab">Basis</span>' + seg("gb", { eop: "EOP", avg: "Average" }, gBasis) + '<span class="glab">Metric</span>' + seg("gm", { yoy: "YoY %", lqa: "LQA %" }, gMetric) + "</div>" +
      '<div class="qdl"><button class="btn sm" data-gcsv="1">Download CSV</button>' + (INLINE ? "" : '<a class="btn sm" href="data/h8-growth5y.xlsx" download>Download Excel</a>') + "</div></div>" +
      '<div class="gcap">Showing <b>' + esc(GM[gMetric]) + "</b> on a <b>" + esc(GB[gBasis]) + "</b> basis · " + (banked ? esc(BANKL[bankView]) : "all commercial banks") + ", SA · hover a cell for the $bn level and week · <i>scroll left for earlier quarters</i></div>" +
      '<div class="gwrap"><table class="sumtbl qtbl gtbl"><thead><tr><th class="sl">Series</th>' + G.columns.map(c => '<th class="r">' + esc(c.label) +
        (c.partial ? '<span class="qtag">QTD: ' + c.n + " wk" + (c.n > 1 ? "s" : "") + "</span>" : "") + (gBasis === "eop" ? '<span class="wk">wk ' + esc(shortD(c.eop_date)) + "</span>" : '<span class="wk">' + c.n + " wks avg</span>") + "</th>").join("") + "</tr></thead><tbody>";
    for (const r of rows) {
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
      const head = ["Bank group", "Basis", "Series", "FRED id", "SA/NSA"];
      G.columns.forEach(c => { const l = c.label + (c.partial ? " QTD" : ""); head.push(l + " level ($bn)", l + " YoY %", l + " LQA %", basis === "eop" ? l + " EOP week" : l + " weeks in qtr"); });
      rows.push(head);
      G.rows.forEach(r => { const row = [BANKS[r.bank] ? (r.bank === "D" ? "Domestic total" : BANKS[r.bank] + " domestic") : "", basis === "eop" ? "End of period" : "Quarter average", "  ".repeat(r.lvl || 0) + r.name, r.key, r.sa];
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
    const cols = Q.columns, nc = cols.length, banked = Q.groups.some(g => g.bank), groups = banked ? Q.groups.filter(g => !g.bank || g.bank === bankView) : Q.groups;
    // column header: mark QTD and summarize how much of the quarter is in, per frequency
    const hdr = cols.map((c, i) => {
      const part = {}; groups.forEach(g => g.rows.forEach(r => { const x = r.cells[i]; if (x && x.partial) part[r.freq] = x.n; }));
      const tag = Object.entries(part).map(([f, n]) => (f === "Monthly" ? "H.6 QTD: " + n + " of 3 mo" : "QTD: " + n + " wk" + (n > 1 ? "s" : ""))).join("; ");
      return '<th class="r">' + esc(c.label) + (tag ? '<span class="qtag">' + esc(tag) + "</span>" : "") + "</th>"; }).join("");
    let h = '<div class="qbar"><div class="gtg">' + (banked ? bankSeg() : "") + '<div class="seg">' + Object.entries(V).map(([k, l]) => '<button data-qv="' + k + '" class="' + (k === qView ? "on" : "") + '">' + l + "</button>").join("") + "</div></div>" +
      '<div class="qdl"><button class="btn sm" data-csv="1">Download CSV</button>' + (INLINE ? "" : '<a class="btn sm" href="data/' + esc(id) + '-quarterly.xlsx" download>Download Excel</a>') + "</div></div>" +
      '<div class="qwrap"><table class="sumtbl qtbl"><thead><tr><th class="sl">Series</th>' + hdr + "</tr></thead><tbody>";
    for (const g of groups) {
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

  // ---- prediction markets ----
  const pp = x => x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "±") + Math.abs(x * 100).toFixed(Math.abs(x) < 0.1 ? 1 : 0) + " pp";
  const pct = x => (x * 100 < 1 && x > 0 ? "<1" : x * 100 > 99 && x < 1 ? ">99" : Math.round(x * 100)) + "%";
  const money = (v, venue) => (venue === "Kalshi" ? "" : "$") + (v >= 1e6 ? (v / 1e6).toFixed(1) + "M" : v >= 1e3 ? Math.round(v / 1e3) + "K" : Math.round(v)) + (venue === "Kalshi" ? " ct" : "");
  const shortClose = s => s ? new Date(s).toLocaleDateString("en-US", { timeZone: TZ, month: "short", day: "numeric", year: "numeric" }) : "–";
  function venueBlock(v) {
    const rows = v.outcomes.map(o => '<div class="pmo"><span class="pml" title="' + esc(o.label) + '">' + esc(o.label) + '</span><span class="pmb"><i style="width:' + Math.max(1, Math.min(100, o.p * 100)).toFixed(1) + '%"></i></span><b>' + pct(o.p) + "</b>" +
      '<span class="pmc ' + (o.chg24h > 0.0005 ? "pos" : o.chg24h < -0.0005 ? "neg" : "flat") + '" title="24h change">' + pp(o.chg24h) + '</span><span class="pmc ' + (o.chg7d > 0.0005 ? "pos" : o.chg7d < -0.0005 ? "neg" : "flat") + '" title="7d change">' + pp(o.chg7d) + "</span></div>").join("");
    return '<div class="pmv"><div class="pmh"><span class="pmvn ' + v.venue.toLowerCase() + '">' + esc(v.venue) + '</span><a href="' + esc(v.url) + '" target="_blank" rel="noopener noreferrer">open market ' + EXT + "</a></div>" +
      '<div class="pmhd"><span></span><span></span><span>prob</span><span>24h</span><span>7d</span></div>' + rows +
      '<div class="pmm">7d vol ' + money(v.vol7d || 0, v.venue) + " · " + (v.venue === "Kalshi" ? "OI " + money(v.oi || 0, v.venue) : "OI $" + money(v.oi || 0, "x").slice(1)) + " · closes " + shortClose(v.close) + "</div></div>";
  }

  function bankPage(area, D) {
    const cfg = D.config, C = D.current, comps = D.components || [];
    document.title = cfg.title + " · Research Hub";
    stamp.innerHTML = "Last updated " + fmtTime(D.updated_at);
    const col = x => x == null ? "var(--mut)" : x > 60 ? "var(--up)" : x < 40 ? "var(--dn)" : "var(--warn)";
    const lbl = x => x == null ? "n/a" : x > 60 ? "Supportive" : x < 40 ? "Challenging" : "Neutral";
    const ang = x => Math.PI * (1 - x / 100), pt = (x, r) => [100 + r * Math.cos(ang(x)), 100 - r * Math.sin(ang(x))];
    const arc = (a, b, c) => { const p = pt(a, 80), q = pt(b, 80); return '<path d="M' + p[0] + " " + p[1] + " A80 80 0 0 1 " + q[0] + " " + q[1] + '" stroke="' + c + '" stroke-width="16" fill="none"/>'; };
    const nd = C.score == null ? null : pt(C.score, 66);
    const gauge = '<svg viewBox="0 0 200 112" class="bcg">' + arc(0, 40, "#5a2a2a") + arc(40, 60, "#5a4a1f") + arc(60, 100, "#1f4a2a") +
      (C.score == null ? "" : arc(0, Math.max(C.score, 0.5), col(C.score)) + '<line x1="100" y1="100" x2="' + nd[0] + '" y2="' + nd[1] + '" stroke="#e6edf3" stroke-width="3" stroke-linecap="round"/><circle cx="100" cy="100" r="5" fill="#e6edf3"/>') + "</svg>";
    const chg = (o, t) => { if (!o || o.score == null || C.score == null) return '<span class="flat">' + t + ": n/a</span>"; const d = C.score - o.score;
      return '<span class="' + (Math.abs(d) < 0.05 ? "flat" : d > 0 ? "pos" : "neg") + '">' + (d > 0 ? "+" : "") + d.toFixed(1) + " vs " + t + " (" + o.score.toFixed(1) + ", " + fmtDate(o.date, "Daily").replace(/, \d{4}$/, "") + ")</span>"; };
    let h = "<h1>" + esc(cfg.title) + '</h1><p class="sub">' + esc(cfg.subtitle) + "</p>" +
      '<div class="bctop"><div class="panel bchead">' + gauge + '<div class="bcv" style="color:' + col(C.score) + '">' + (C.score == null ? "n/a" : C.score.toFixed(1)) + '</div><div class="bcl" style="color:' + col(C.score) + '">' + lbl(C.score) + '</div><div class="pnote" style="margin:2px 0 4px">Backtested against KRE relative to small caps (IWM)</div>' +
      '<div class="bcc">' + chg(C.w1, "1 wk ago") + chg(C.m1, "1 mo ago") + (D.deterioration && D.deterioration.current_off_high != null ? '<span class="' + (D.deterioration.current_off_high <= -15 ? "neg" : D.deterioration.current_off_high <= -10 ? "flat" : "pos") + '" title="Ex-equity index vs its trailing 26-week high (in-sample deterioration check)">Ex-equity: ' + D.history[D.history.length - 1].score_ex.toFixed(1) + ', ' + Math.abs(D.deterioration.current_off_high).toFixed(1) + ' pts below 26-wk high (' + D.deterioration.high_26w.toFixed(1) + ')</span>' : '') + (D.flag && D.flag.current.streak != null ? '<span class="' + (D.flag.current.streak >= 6 ? "neg" : D.flag.current.streak >= 4 ? "flat" : "pos") + '" title="Consecutive weeks the ex-equity index has been 15+ pts below its 26-week high. Context only; thresholds fitted in-sample.">' + D.flag.current.streak + ' wk' + (D.flag.current.streak === 1 ? "" : "s") + ' in a row below −15 · ' + [4, 6, 8].map(n => n + "wk " + (D.flag.current.streak >= n ? "ON" : "off")).join(" / ") + ' <i style="color:var(--mut)">(in-sample, fitted)</i></span>' : '') + '</div><div class="pnote">' + C.fav + " favorable · " + C.neu + " neutral · " + C.unf + " unfavorable · " + C.n + " of " + C.total + " scored" + (C.n < C.total ? " (" + (C.total - C.n) + " stale, excluded)" : "") + (C.context_only ? " · " + C.context_only + " context only" : "") + "</div></div>" +
      '<div class="panel"><h4>Category subscores</h4><div class="bccats">' + D.categories.map(c => '<div class="bccat"><div class="bcn">' + esc(c.name) + '<span class="hint">' + c.n + "/" + c.total + (c.context ? " +" + c.context + " ctx" : "") + '</span></div><div class="bcbar"><i style="width:' + (c.score || 0) + "%;background:" + col(c.score) + '"></i></div><div class="bcs" style="color:' + col(c.score) + '">' + (c.score == null ? (c.total === 0 ? "context only, not scored" : "n/a") : c.score.toFixed(0) + " · " + lbl(c.score)) + "</div></div>").join("") + "</div></div></div>";
    h += '<h2>Diffusion index history <span class="hint">weekly, point-in-time · ' + (D.coverage_from ? "≥75% of components available from " + fmtDate(D.coverage_from, "Daily") : "") + '</span></h2><div class="toolbar"><span>Lookback</span><div class="seg">' + ["1Y", "5Y", "10Y", "Max"].map(r => '<button data-r="' + r + '" class="' + (r === range ? "on" : "") + '">' + r + "</button>").join("") + '</div></div><div class="panel full"><div class="cv" style="height:340px"><canvas id="bch"></canvas></div><div class="pnote">Line = diffusion index (left); grey = number of components scored that week (right). Dashed lines at 40 and 60. Coverage grows as sources begin: SOFR Apr 2018, CRE SLOOS Q4 2013, FDIC CD rates Apr 2021, ICE BofA OAS Oct 2023 (level percentiles score from Oct 2024).</div></div>';
    const v = (x, u) => x == null ? "–" : (u === "%" || u === "pp" ? (x > 0 && u === "pp" ? "+" : "") + x.toFixed(2) + (u === "%" ? "%" : "") : u === "net %" ? x.toFixed(1) : x.toFixed(2));
    const sig = c => c.scored === false ? '<span class="flat b">Context only · not scored</span><span class="dl" style="color:var(--mut)">' + esc(c.context_reason || "") + (c.signal != null ? " (would read " + (c.signal === 1 ? "favorable" : c.signal === -1 ? "unfavorable" : "neutral") + ")" : "") + "</span>" : c.status !== "ok" ? '<span class="stl">STALE · excluded</span>' : c.signal === 1 ? '<span class="pos b">Favorable</span>' : c.signal === -1 ? '<span class="neg b">Unfavorable</span>' : '<span class="flat b">Neutral</span>';
    const dir = c => { if (!c.prior || c.value == null) return "–"; const d = c.value - c.prior.value; if (Math.abs(d) < 1e-6) return '<span class="flat">unch.</span>';
      const good = c.better === "abs" ? Math.abs(c.value) < Math.abs(c.prior.value) : (d > 0) === (c.better === "high"); return '<span class="' + (good ? "pos" : "neg") + '">' + (d > 0 ? "▲ " : "▼ ") + (good ? "improving" : "worsening") + '</span><span class="dl" style="color:var(--mut)">vs ' + v(c.prior.value, c.unit) + " " + fmtDate(c.prior.date, c.freq === "q" ? "Quarterly" : c.freq === "m" ? "Monthly" : "Daily") + "</span>"; };
    const fq = { d: "Daily", w: "Daily", m: "Monthly", q: "Quarterly" };
    const fp = x => x == null ? "–" : (x > 0 ? "+" : "") + x.toFixed(2) + "%";
    if (D.kre && D.kre.length) {
      h += '<h2>Ex-equity index vs its trailing 26-week high <span class="hint">same dates and lookback as the index</span></h2><div class="panel full"><div class="cv" style="height:240px"><canvas id="bcdd"></canvas></div></div><h2>Ex-equity index minus its 26-week high <span class="hint">points · dashed at -10 and -15</span></h2><div class="panel full"><div class="cv" style="height:200px"><canvas id="bcdd2"></canvas></div>' + (() => { const B = (D.deterioration || {}).buckets; if (!B) return ""; const wa = (bs, k) => { let n = 0, t = 0; bs.forEach(b => { if (b[k] != null) { n += b.weeks; t += b[k] * b.weeks; } }); return n ? t / n : null; };
        const band = (c, lab, bs) => '<span style="display:inline-flex;align-items:center;gap:6px;margin-right:18px"><i style="width:12px;height:12px;background:' + c + ';display:inline-block;border-radius:2px"></i>' + lab + ': ' + fp(wa(bs, "rel_iwm_26")) + " KRE vs IWM, " + fp(wa(bs, "mdd_26")) + " max drawdown</span>";
        return '<div class="pnote">Bands, in-sample avg forward 26 wk (2012-2026, overlapping windows, revised data): ' + band("rgba(46,160,67,.5)", "0-10 below", B.slice(0, 2)) + band("rgba(210,153,34,.5)", "10-15 below", [B[2]]) + band("rgba(248,81,73,.5)", "15+ below", [B[3]]) + "</div>"; })() + '</div>' +
'<h2>KRE vs Russell 2000 (IWM) <span class="hint">ratio of adjusted closes, rebased to 100 at Jan 6, 2012 · rising = regionals outperforming small caps</span></h2><div class="panel full"><div class="cv" style="height:240px"><canvas id="bcrel"></canvas></div></div>';
      const DT = D.deterioration;
      if (DT) h += '<h2>Deterioration check: ex-equity index vs its 26-week high <span class="hint">IN-SAMPLE · not a trading signal</span></h2><div class="pnote" style="margin-bottom:6px">Now: ex-equity index ' + (DT.current_off_high == null ? "–" : DT.current_off_high.toFixed(1)) + " pts from its 26-week high of " + DT.high_26w.toFixed(1) + '.</div><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Ex-equity index vs trailing 26-wk high</th><th class="r">Weeks</th><th class="r">KRE vs IWM, fwd 13 wk</th><th class="r">KRE vs IWM, fwd 26 wk</th><th class="r">KRE vs XLF, fwd 26 wk</th><th class="r">KRE max drawdown, fwd 26 wk</th></tr></thead><tbody>' +
        DT.buckets.map(b => "<tr><td>" + esc(b.label) + '</td><td class="r">' + b.weeks + '</td><td class="r b">' + fp(b.rel_iwm_13) + '</td><td class="r b">' + fp(b.rel_iwm_26) + '</td><td class="r b">' + fp(b.rel_xlf_26) + '</td><td class="r b">' + fp(b.mdd_26) + "</td></tr>").join("") +
        '</tbody></table></div><div class="pnote">' + esc((cfg.notes || {}).deterioration || "") + '</div>';

    }
    const FL = D.flag;
    if (FL) {
      const cu = FL.current, onc = cu.on ? "neg" : "pos";
      h += '<h2>Rate shock + credit deterioration flag <span class="hint">context panel · not part of the headline · threshold fixed on 2012-2018 data</span></h2><div class="panel"><div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center"><div class="bcv ' + onc + '" style="font-size:28px">' + (cu.on == null ? "n/a" : cu.on ? "ON" : "OFF") + '</div><div><div class="bcv ' + (cu.confirmed ? "neg" : "pos") + '" style="font-size:20px">Confirmed: ' + (cu.confirmed ? "ON" : "OFF") + '</div><div class="pnote" style="margin:0">flag ON + ' + cu.streak + '/6 wks in a row below −15</div></div><div class="pnote" style="margin:0">ON when the 10Y is up more than +' + FL.rate_bp + "bp over 12 months AND the full Credit subscore (all 11 credit inputs, incl. context-only) is " + Math.abs(FL.threshold).toFixed(1) + " pts or more below its 26-week high (pre-2019 20th percentile).<br>Now: 10Y 12-month change " + (cu.ust12_bp == null ? "–" : (cu.ust12_bp > 0 ? "+" : "") + cu.ust12_bp + "bp") + " (" + (cu.ust12_bp > FL.rate_bp ? "met" : "not met") + ") · Credit " + (cu.credit == null ? "–" : cu.credit.toFixed(1)) + ", " + (cu.credit_off == null ? "–" : Math.abs(cu.credit_off).toFixed(1)) + " pts below its 26-wk high (" + (cu.credit_off != null && cu.credit_off <= FL.threshold ? "met" : "not met") + ')</div></div><div class="cv" style="height:200px;margin-top:8px"><canvas id="bcflag"></canvas></div></div>' +
        (FL.confirmed_events ? '<h4 class="atit" style="margin-top:10px">Confirmed triggers <span class="hint">flag ON and ex-equity index below −15 for 6+ consecutive weeks · IN-SAMPLE, FITTED</span></h4><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Trigger week</th><th class="r">KRE vs IWM, fwd 6 mo</th><th class="r">KRE absolute, fwd 6 mo</th><th class="r">KRE max drawdown, fwd 6 mo</th></tr></thead><tbody>' +
          FL.confirmed_events.map(e => "<tr><td>" + fmtDate(e.date, "Daily") + '</td><td class="r b">' + (e.rel_iwm_26 == null ? "pending" : fp(e.rel_iwm_26)) + '</td><td class="r">' + (e.abs_26 == null ? "pending" : fp(e.abs_26)) + '</td><td class="r b">' + (e.mdd_26 == null ? "pending" : fp(e.mdd_26)) + "</td></tr>").join("") +
          '</tbody></table></div><div class="pnote">Context only. The Confirmed tier rests on two episodes (2018 and 2022); the 6-week streak was picked after looking at the data, and the best streak length differs by index version (4 weeks worked best on the older 41-input index, 6 on the current 30-input one).</div>' : "") +
        '<div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Period</th><th>Flag</th><th class="r">Weeks</th><th class="r">KRE vs IWM, fwd 26 wk</th><th class="r">KRE vs XLF, fwd 26 wk</th><th class="r">KRE absolute, fwd 26 wk</th><th class="r">KRE max drawdown, fwd 26 wk</th></tr></thead><tbody>' +
        FL.stats.map(r => "<tr><td>" + esc(r.period) + '</td><td class="b ' + (r.state === "ON" ? "neg" : "") + '">' + r.state + '</td><td class="r">' + r.weeks + '</td><td class="r b">' + fp(r.rel_iwm_26) + '</td><td class="r">' + fp(r.rel_xlf_26) + '</td><td class="r">' + fp(r.abs_26) + '</td><td class="r b">' + fp(r.mdd_26) + "</td></tr>").join("") +
        '</tbody></table></div><div class="pnote">Episodes (first week ON): ' + (FL.episodes.length ? FL.episodes.map(e => fmtDate(e.date, "Daily") + " (" + (e.rel_iwm_26 == null ? "pending" : fp(e.rel_iwm_26) + " vs IWM, " + fp(e.mdd_26) + " max DD") + ")").join(" · ") : "none") + ". " + esc((cfg.notes || {}).flag || "") + "</div>";
    }
    const FW = D.forward;
    if (FW) {
      const fv = (v, u) => v == null ? "–" : u === "bp" ? (v > 0 ? "+" : "") + Math.round(v) + " bp" : u === "idx" ? v.toFixed(0) : (u === "pp" && v > 0 ? "+" : "") + v.toFixed(1) + (u === "%" ? "%" : u === "pp" ? " pp" : "");
      const U = {}; FW.current.forEach(c => U[c.key] = c.unit);
      const bad = Object.entries(FW.sources || {}).filter(([, v]) => v.status !== "ok");
      h += '<h2>Forward-looking context <span class="hint">valuation, positioning and rate shock · not part of the diffusion score</span></h2><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Indicator</th><th class="r">Latest</th><th>As of</th><th class="r">10-yr percentile</th><th>Reading</th><th>History from</th></tr></thead><tbody>' +
        ["Valuation", "Positioning", "Rate shock"].map(g => '<tr class="bcgrp"><td colspan="6">' + g + "</td></tr>" + FW.current.filter(c => c.group === g).map(c => "<tr><td>" + esc(c.label) + '</td><td class="r b">' + fv(c.value, c.unit) + "</td><td>" + (c.date ? fmtDate(c.date, "Daily") : "–") + '</td><td class="r">' + (c.pct10y == null ? "–" : c.pct10y + "th") + '</td><td class="hint">' + esc(c.note) + "</td><td>" + (c.from ? c.from.slice(0, 4) : "–") + "</td></tr>").join("")).join("") +
        '</tbody></table></div><div class="pnote">Sources: Yahoo Finance (KRE, SPY closes and dividends); FINRA short interest and State Street shares outstanding via the Financials Dashboard; FDIC BankFind financials API (quarterly, ~60-day lag); FRED (DGS10, DGS2). The price-to-book line is a PROXY: KRE price divided by aggregate equity of all insured banks under $100bn (FDIC, lagged 60 days), rebased; it ignores share issuance, buybacks, M&A and banks crossing $100bn, so read its trend and percentile, not its level. No free P/B or forward P/E history for KRE or the S&P 500 was available, so valuation vs the S&P uses dividend yield. Percentiles use the trailing 10 years (or all history if shorter).' + (bad.length ? ' <span class="stl">Stale/failed: ' + esc(bad.map(([k, v]) => k + " (" + v.status + ")").join(", ")) + "</span>" : "") + "</div>";
      const E = (FW.episodes || {})["20"] || [], ks = [["KRE_SPY_DY", "KRE−SPY yield"], ["KRE_SI", "Short int. % SO"], ["KRE_SO_3M", "Shares out 3m"], ["DGS10_12M", "10Y 12m chg"], ["DGS2_12M", "2Y 12m chg"], ["UL_ALL", "Unreal. loss % eq."]];
      const pc = v => v == null ? "–" : (v > 0 ? "+" : "") + v.toFixed(1) + "%";
      if (E.length) h += '<h2>Deep-drawdown episodes with forward context <span class="hint">IN-SAMPLE · first crossing of −20 below the 26-wk high, re-armed above −15 · value (10-yr percentile) as publicly known at the signal</span></h2><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Signal date</th><th class="r">Ex-eq index</th><th class="r">KRE 3m</th><th class="r">vs IWM 3m</th><th class="r">KRE 6m</th><th class="r">vs IWM 6m</th>' + ks.map(k => '<th class="r">' + k[1] + "</th>").join("") + "</tr></thead><tbody>" +
        E.map(e => "<tr><td>" + fmtDate(e.date, "Daily") + '</td><td class="r">' + e.index.toFixed(0) + '</td><td class="r b">' + pc(e.abs3) + '</td><td class="r">' + pc(e.rel3) + '</td><td class="r b">' + pc(e.abs6) + '</td><td class="r">' + pc(e.rel6) + "</td>" +
          ks.map(([k]) => { const x = e.ind[k]; return '<td class="r">' + (x ? fv(x.value, U[k]) + '<span class="dl" style="color:var(--mut)">' + (x.pct == null ? "" : x.pct + "th") + "</span>" : "–") + "</td>"; }).join("") + "</tr>").join("") +
        '</tbody></table></div><div class="pnote">' + esc((cfg.notes || {}).episodes || "") + '</div>';
    }
    h += '<h2>Components</h2><div class="qbar"><h4 class="atit">' + comps.length + ' inputs <span class="hint">value, as-of date, rule and signal</span></h4><div class="qdl"><button class="btn sm" data-bccsv="c">Components CSV</button>' + (INLINE ? "" : '<a class="btn sm" href="data/bank-conditions-history.csv" download>History CSV</a>') + '<button class="btn sm" data-bccsv="h">History CSV (this view)</button></div></div>' +
      '<div class="tblwrap"><table class="sumtbl atbl bctbl"><thead><tr><th>Component</th><th class="r">Value</th><th>As of</th><th>Rule</th><th>Signal</th><th>Direction</th><th>Source</th></tr></thead><tbody>' +
      D.categories.map(cat => '<tr class="bcgrp"><td colspan="7">' + esc(cat.name) + " · " + (cat.score == null ? "n/a" : cat.score.toFixed(0)) + "</td></tr>" + comps.filter(c => c.cat === cat.name).map(c =>
        "<tr><td>" + esc(c.name) + '</td><td class="r b">' + v(c.value, c.unit) + (c.pct != null ? '<span class="dl" style="color:var(--mut)">' + c.pct + "th pctile</span>" : "") + "</td><td>" + (c.asof ? fmtDate(c.asof, fq[c.freq]) : "–") + '</td><td class="bcrule">' + esc(c.rule) + "</td><td>" + sig(c) + (c.error ? '<span class="dl err">' + esc(c.error) + "</span>" : "") + "</td><td>" + dir(c) + '</td><td class="sid">' + esc(c.sources.join(", ")) + "</td></tr>").join("")).join("") + "</tbody></table></div>";
    h += '<h2>Methodology</h2><div class="panel">' + (cfg.methodology || []).map(p => '<p class="pnote" style="margin:6px 0">' + esc(p) + "</p>").join("") + "</div>";
    app.innerHTML = h;
    const dl = (name, rows) => { const b = new Blob([rows.map(r => r.map(x => x == null ? "" : /[",\n]/.test(String(x)) ? '"' + String(x).replace(/"/g, '""') + '"' : x).join(",")).join("\n")], { type: "text/csv" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = name; a.click(); };
    app.querySelectorAll("button[data-bccsv]").forEach(b => b.onclick = () => b.dataset.bccsv === "c" ?
      dl("bank-conditions-components.csv", [["category", "component", "value", "unit", "as_of", "percentile", "signal", "status", "rule", "sources"]].concat(comps.map(c => [c.cat, c.name, c.value, c.unit, c.asof, c.pct, c.signal, c.status, c.rule, c.sources.join(" ")]))) :
      dl("bank-conditions-history.csv", [["date", "diffusion", "components_scored"].concat(D.categories.map(c => c.name))].concat(D.history.map(r => [r.date, r.score, r.n].concat(D.categories.map(c => r.cats[c.name]))))));
    const draw = () => { charts.forEach(c => c.destroy()); charts = []; const cut = cutoff(), H = D.history.filter(r => !cut || Date.parse(r.date) >= cut);
      const el = document.getElementById("bch"); if (!el) return;
      const ref = y => ({ label: "", data: H.length ? [{ x: Date.parse(H[0].date), y }, { x: Date.parse(H[H.length - 1].date), y }] : [], borderColor: "#5b6b80", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 });
      charts.push(new Chart(el, { type: "line", data: { datasets: [
        { label: "Diffusion index", data: H.filter(r => r.score != null).map(r => ({ x: Date.parse(r.date), y: r.score })), borderColor: "#4ea1ff", backgroundColor: "#4ea1ff", borderWidth: 1.8, pointRadius: 0, tension: 0 },
        { label: "Ex-equity index (drops 4 equity relative-performance inputs)", data: H.filter(r => r.score_ex != null).map(r => ({ x: Date.parse(r.date), y: r.score_ex })), borderColor: "#f472b6", backgroundColor: "#f472b6", borderWidth: 1.3, pointRadius: 0, tension: 0 },
        { label: "Components scored", yAxisID: "y2", data: H.map(r => ({ x: Date.parse(r.date), y: r.n })), borderColor: "#5b6b80", borderWidth: 1, pointRadius: 0, stepped: true }, ref(40), ref(60)] },
        options: { parsing: false, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales: { x: { type: "time", grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 10 } }, y: { min: 0, max: 100, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" }, afterFit: s => { s.width = 40; } }, y2: { position: "right", min: 0, max: comps.length + 2, grid: { display: false }, ticks: { color: "#5b6b80" } } },
          plugins: { legend: { labels: { color: "#e6edf3", boxWidth: 12, filter: i => i.text } }, tooltip: { filter: i => i.dataset.label, callbacks: { title: t => t.length ? fmtDate(new Date(t[0].parsed.x).toISOString().slice(0, 10), "Daily") : "" } } } } }));
      const K = (D.kre || []).filter(r => !cut || Date.parse(r.date) >= cut), x0 = H.length ? Date.parse(H[0].date) : undefined, x1 = H.length ? Date.parse(H[H.length - 1].date) : undefined;
      const mini = (id, key, label, color, rebase) => { const c = document.getElementById(id); if (!c) return; const base = rebase ? (K.find(r => r[key] != null) || {})[key] : null;
        charts.push(new Chart(c, { type: "line", data: { datasets: [{ label: label + (rebase && cut ? " (rebased to 100 at start of view)" : ""), data: K.filter(r => r[key] != null).map(r => ({ x: Date.parse(r.date), y: base ? 100 * r[key] / base : r[key] })), borderColor: color, borderWidth: 1.6, pointRadius: 0 }] },
          options: { parsing: false, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, layout: { padding: { right: 0 } },
            scales: { x: { type: "time", min: x0, max: x1, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 10 } }, y: { grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" }, afterFit: s => { s.width = 40; } }, y2: { position: "right", display: true, grid: { display: false }, ticks: { display: false }, afterFit: s => { s.width = yw2; } } },
            plugins: { legend: { labels: { color: "#e6edf3", boxWidth: 12 } }, tooltip: { callbacks: { title: t => t.length ? fmtDate(new Date(t[0].parsed.x).toISOString().slice(0, 10), "Daily") : "" } } } } })); };
      const yw2 = charts[0] ? charts[0].scales.y2.width : 30;
      { const el2 = document.getElementById("bcdd"); if (el2) { const A = D.history, P = [];
        A.forEach((r, i) => { if (r.score_ex == null) return; const w = A.slice(Math.max(0, i - 26), i + 1).map(x => x.score_ex).filter(x => x != null), hi = Math.max(...w); P.push({ x: Date.parse(r.date), v: r.score_ex, hi, off: r.score_ex - hi }); });
        const Q = P.filter(p => !cut || p.x >= cut), rl = y => ({ type: "line", label: "", yAxisID: "y2", data: Q.length ? [{ x: Q[0].x, y }, { x: Q[Q.length - 1].x, y }] : [], borderColor: y === -15 ? "#f85149" : "#d29922", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 });
        const opt = y => ({ parsing: false, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, scales: { x: { type: "time", min: x0, max: x1, offset: false, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 10 } }, y, y2: { position: "right", display: true, grid: { display: false }, ticks: { display: false }, afterFit: s => { s.width = yw2; } } }, plugins: { legend: { labels: { color: "#e6edf3", boxWidth: 12, filter: i => i.text } }, tooltip: { filter: i => i.dataset.label, callbacks: { title: t => t.length ? fmtDate(new Date(t[0].parsed.x).toISOString().slice(0, 10), "Daily") : "" } } } });
        charts.push(new Chart(el2, { type: "line", data: { datasets: [
          { label: "Ex-equity index", data: Q.map(p => ({ x: p.x, y: p.v })), borderColor: "#f472b6", borderWidth: 1.6, pointRadius: 0 },
          { label: "Trailing 26-wk high", data: Q.map(p => ({ x: p.x, y: p.hi })), borderColor: "#8b9bb0", borderWidth: 1.2, pointRadius: 0, stepped: true }] },
          options: opt({ min: 0, max: 100, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" }, afterFit: s => { s.width = 40; } }) }));
        const el3 = document.getElementById("bcdd2"), rl2 = y => ({ type: "line", label: "", data: Q.length ? [{ x: Q[0].x, y }, { x: Q[Q.length - 1].x, y }] : [], borderColor: y === -15 ? "#f85149" : "#d29922", borderDash: [4, 4], borderWidth: 1, pointRadius: 0 });
        if (el3) charts.push(new Chart(el3, { type: "bar", data: { datasets: [
          { type: "line", label: "6+ wks in a row below −15", data: (() => { const SH = (D.flag && D.flag.streak_hist) || [], m = {}; SH.forEach(r => m[r[0]] = r[1]); return Q.filter(p => m[new Date(p.x).toISOString().slice(0, 10)] >= 6).map(p => ({ x: p.x, y: 2 })); })(), showLine: false, pointStyle: "triangle", pointRadius: 3, borderColor: "#f85149", backgroundColor: "#f85149" },
          { type: "bar", label: "Index minus 26-wk high (pts)", data: Q.map(p => ({ x: p.x, y: p.off })), backgroundColor: Q.map(p => p.off <= -15 ? "rgba(248,81,73,.75)" : p.off <= -10 ? "rgba(210,153,34,.75)" : "rgba(46,160,67,.65)"), barPercentage: 1, categoryPercentage: 1 }, rl2(-10), rl2(-15)] },
          options: opt({ max: 4, suggestedMin: -30, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" }, afterFit: s => { s.width = 40; } }) })); } }
      { const ef = document.getElementById("bcflag"); if (ef && D.flag) { const FH = D.flag.history.filter(r => !cut || Date.parse(r[0]) >= cut);
        charts.push(new Chart(ef, { type: "bar", data: { datasets: [
          { type: "bar", label: "Flag ON", yAxisID: "y", data: FH.map(r => ({ x: Date.parse(r[0]), y: r[1] ? 1 : 0 })), backgroundColor: "rgba(248,81,73,.45)", barPercentage: 1, categoryPercentage: 1 },
          { type: "bar", label: "Confirmed (flag + 6-wk streak)", yAxisID: "y", data: FH.map(r => ({ x: Date.parse(r[0]), y: D.flag.confirmed_hist[D.flag.history.indexOf(r)] ? 1 : 0 })), backgroundColor: "rgba(185,28,28,.95)", barPercentage: 1, categoryPercentage: 1 },
          { type: "line", label: "Credit pts below 26-wk high", yAxisID: "y2", data: FH.filter(r => r[2] != null).map(r => ({ x: Date.parse(r[0]), y: r[2] })), borderColor: "#f472b6", borderWidth: 1.2, pointRadius: 0 },
          { type: "line", label: "10Y 12-month change (bp ÷ 10)", yAxisID: "y2", data: FH.filter(r => r[3] != null).map(r => ({ x: Date.parse(r[0]), y: r[3] / 10 })), borderColor: "#4ea1ff", borderWidth: 1.2, pointRadius: 0 }] },
          options: { parsing: false, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
            scales: { x: { type: "time", min: x0, max: x1, offset: false, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 10 } }, y: { min: 0, max: 1, display: true, grid: { display: false }, ticks: { display: false }, afterFit: s => { s.width = 40; } }, y2: { position: "right", grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0" }, afterFit: s => { s.width = yw2; } } },
            plugins: { legend: { labels: { color: "#e6edf3", boxWidth: 12 } }, tooltip: { callbacks: { title: t => t.length ? fmtDate(new Date(t[0].parsed.x).toISOString().slice(0, 10), "Daily") : "" } } } } })); } }
      mini("bcrel", "rel", "KRE / IWM (Jan 2012 = 100)", "#a78bfa", true);
    };
    draw();
    app.querySelectorAll(".toolbar .seg button").forEach(b => b.onclick = () => { range = b.dataset.r; localStorage.setItem("rh-range", range);
      app.querySelectorAll(".toolbar .seg button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
  }

  function predictionsPage(area, D) {
    const cfg = D.config;
    document.title = cfg.title + " · Research Hub";
    stamp.innerHTML = "Odds as of " + fmtTime(D.generated_at || D.updated_at) + (D.stale ? ' · <span class="stl">STALE (a venue failed; last good list shown)</span>' : "");
    const items = D.items || [];
    let h = "<h1>" + esc(cfg.title) + '</h1><p class="sub">' + esc(cfg.subtitle) + "</p>";
    for (const g of ["Macro", "Markets", "Geopolitical"]) {
      const gi = items.filter(x => x.group === g); if (!gi.length) continue;
      h += "<h2>" + g + ' <span class="hint">' + gi.length + " of " + items.length + "</span></h2><div class=\"pmgrid\">" + gi.map(it =>
        '<div class="pmcard' + (it.venues.length > 1 ? " both" : "") + '"><div class="pmt"><span class="pmr">#' + it.rank + "</span>" + esc(it.title) + (it.venues.length > 1 ? ' <span class="pmboth">Kalshi + Polymarket</span>' : "") + "</div>" +
        '<div class="pmvs">' + it.venues.map(venueBlock).join("") + "</div></div>").join("") + "</div>";
    }
    const ch = items.filter(x => x.chart);
    if (ch.length) h += '<h2>Probability history <span class="hint">top ' + ch.length + ' by liquidity, daily, up to 90 days</span></h2><div class="panels c2">' + ch.map((it, j) =>
      '<div class="panel"><h4>#' + it.rank + " " + esc(it.title) + " (" + esc(it.venues[0].venue) + ')</h4><div class="cv"><canvas id="pm' + j + '"></canvas></div><div class="src">Source: ' + esc(it.venues[0].venue) + "</div></div>").join("") + "</div>";
    h += '<div class="pnote pmnote">' + esc(cfg.ranking_note || "") + "</div><div class=\"pnote pmnote\">" + esc(cfg.disclaimer || "") + "</div>";
    app.innerHTML = h;
    ch.forEach((it, j) => {
      const v = it.venues[0], outs = v.outcomes.filter(o => o.hist && o.hist.length).sort((a, b) => b.p - a.p).slice(0, 4);
      const el = document.getElementById("pm" + j); if (!el || !outs.length) return;
      charts.push(new Chart(el, { type: "line", data: { datasets: outs.map((o, n) => ({ label: o.label, data: o.hist.map(x => ({ x: Date.parse(x[0] + "T00:00:00Z"), y: +(x[1] * 100).toFixed(1) })), borderColor: COLORS[n], backgroundColor: COLORS[n], borderWidth: 1.6, pointRadius: 0, tension: 0 })) },
        options: { parsing: false, animation: false, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
          scales: { x: { type: "time", time: { minUnit: "day" }, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", maxTicksLimit: 7 } }, y: { min: 0, max: 100, grid: { color: "#1f2a37" }, ticks: { color: "#8b9bb0", callback: x => x + "%" } } },
          plugins: { legend: { labels: { color: "#e6edf3", boxWidth: 12 } }, tooltip: { callbacks: { title: t => t.length ? fmtDate(new Date(t[0].parsed.x).toISOString().slice(0, 10), "Daily") : "", label: t => t.dataset.label + ": " + t.parsed.y.toFixed(1) + "%" } } } } }));
    });
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
    if (s.stats && s.stats.short != null) return statsCard(s);
    if (s.stats && s.stats.vs_ly !== undefined) return chokeCard(s, S);
    const tag = s.link ? "a" : "div", href = s.link ? ' href="' + esc(s.link) + '" target="_blank" rel="noopener noreferrer"' : "";
    const tip = (s.src_label || "FRED " + s.fred) + (L.release ? " · latest update after: " + L.release : "") + (s.error ? " · " + esc(s.error) : "");
    const dline = L.asof ? esc(L.target) + " · as of " + fmtDate(L.asof, "Daily").replace(/, \d{4}$/, "") + (L.mm != null ? " · m/m " + L.mm.toFixed(2) + "%" : "")
                : L.target ? esc(L.target) + " · as of " + fmtDate(L.date, "Daily") + (P ? " · prior " + fmtVal(P.value, s.fmt) : "")
                           : fmtDate(L.date, s.freq) + (P ? " · prior " + fmtVal(P.value, s.fmt) : "");
    return "<" + tag + href + ' class="kpi ' + (s.link ? "linked " : "") + (s.status !== "ok" ? s.status : "") + '" title="' + esc(tip) + '"><div class="t">' + esc(s.title) + (s.link ? " " + EXT : "") + '</div><div class="v">' + fmtVal(L.value, s.fmt) +
      '</div><div class="d">' + dline + (s.status === "stale" ? " · STALE" : "") + '</div><div class="c">' + c + "</div></" + tag + ">";
  }

  function cardShell(s, c, dline) {
    const tag = s.link ? "a" : "div", href = s.link ? ' href="' + esc(s.link) + '" target="_blank" rel="noopener noreferrer"' : "";
    return "<" + tag + href + ' class="kpi ' + (s.link ? "linked " : "") + (s.status !== "ok" ? s.status : "") + '" title="' + esc((s.src_label || "") + (s.error ? " · " + s.error : "")) + '"><div class="t">' + esc(s.title) + (s.link ? " " + EXT : "") +
      '</div><div class="v">' + fmtVal(s.stats.latest, s.fmt) + '</div><div class="d">' + dline + (s.status === "stale" ? " · STALE" : "") + '</div><div class="c">' + c + "</div></" + tag + ">";
  }
  // risk / uncertainty index: short average vs trailing-1Y average, and percentile of the short average vs history
  function statsCard(s) {
    const t = s.stats, daily = s.freq === "Daily", d = t.short - t.avg1y;
    const pc = t.pctile >= 90 ? "neg" : t.pctile <= 25 ? "pos" : "flat";
    const c = '<span class="' + (d > 0 ? "neg" : "pos") + '">' + (daily ? "30d" : "3m") + " avg " + fmtVal(t.short, s.fmt) + " vs 1Y " + fmtVal(t.avg1y, s.fmt) + '</span><span class="' + pc + '">' + Math.round(t.pctile) + ordSfx(Math.round(t.pctile)) + " pctile since " + esc(t.since) + "</span>";
    return cardShell(s, c, fmtDate(t.date, s.freq));
  }
  function ordSfx(n) { const m = n % 100; return (m >= 11 && m <= 13) ? "th" : ({ 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"); }
  // chokepoint transits (7-day avg): vs same dates last year and vs the 2019-2022 baseline; tanker/container split
  function chokeCard(s, S) {
    const t = s.stats, sg = v => (v > 0 ? "+" : "") + v.toFixed(0) + "%";
    const c = (t.vs_ly != null ? '<span class="' + (t.vs_ly < 0 ? "neg" : "pos") + '">' + sg(t.vs_ly) + " y/y</span>" : "") + (t.vs_base != null ? '<span class="' + (t.vs_base < 0 ? "neg" : "pos") + '">' + sg(t.vs_base) + " vs 2019-22</span>" : "");
    const comp = (s.companions || []).map(k => S[k] && S[k].latest ? (k.endsWith("_tank") ? "tankers " : "containers ") + S[k].latest.value.toFixed(1) : "").filter(Boolean).join(" · ");
    return cardShell(s, c, "7d avg to " + fmtDate(t.date, "Daily").replace(/, \d{4}$/, "") + (comp ? " · " + comp : ""));
  }
  // FDIC deposit pricing: cumulative betas per cycle leg + last-8-quarter-end rates
  // ---- SLOOS: latest survey table (net %, change vs prior survey) + CSV of full history ----
  const svy = t => t ? ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][+t.slice(5, 7) - 1] + " " + t.slice(0, 4) : "–";
  function sloosTable(C, S) {
    const v = x => x == null ? "–" : (x > 0 ? "+" : "") + x.toFixed(1);
    const cell = (k, pol) => { const r = S[k]; if (!r || !r.latest) return '<td class="r">–</td><td class="r">–</td><td class="r">–</td>';
      const L = r.latest.value, P = r.prior ? r.prior.value : null, d = P == null ? null : L - P;
      return '<td class="r b">' + v(L) + '</td><td class="r">' + v(P) + '</td><td class="r ' + (d == null || Math.abs(d) < 0.05 ? "" : (d * pol > 0 ? "pos" : "neg")) + '">' + (d == null ? "–" : (d > 0 ? "+" : "") + d.toFixed(1) + " pp") + "</td>"; };
    const any = S[C.rows[0].std] || {}, lt = any.latest && any.latest.date, pr = any.prior && any.prior.date;
    return '<div class="qbar"><h4 class="atit">Latest survey: ' + svy(lt) + ' <span class="hint">vs ' + svy(pr) + ' · net % of banks</span></h4><div class="qdl"><button class="btn sm" data-scsv="1">Download CSV</button></div></div>' +
      '<div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Loan category</th><th class="r">Standards<span class="dl" style="color:var(--mut)">net % tightening</span></th><th class="r">Prior</th><th class="r">Δ</th><th class="r">Demand<span class="dl" style="color:var(--mut)">net % stronger</span></th><th class="r">Prior</th><th class="r">Δ</th></tr></thead><tbody>' +
      C.rows.map(r => "<tr><td>" + esc(r.label) + "</td>" + cell(r.std, -1) + cell(r.dem, 1) + "</tr>").join("") +
      (C.extra || []).map(r => "<tr><td>" + esc(r.label) + "</td>" + cell(r.key, 1) + '<td class="r">–</td><td class="r">–</td><td class="r">–</td></tr>').join("") +
      '</tbody></table></div><p class="pnote">Green = easier standards / stronger demand vs the prior survey; red = tighter / weaker. CSV contains the full history of every series.</p>';
  }
  function sloosCsv(C, S) {
    const cols = C.rows.flatMap(r => [[r.std, r.label + " - standards (net % tightening)"], [r.dem, r.label + " - demand (net % stronger)"]]).concat((C.extra || []).map(r => [r.key, r.label]));
    const maps = cols.map(([k]) => new Map((S[k] && S[k].obs || []).map(o => [o[0], o[1]])));
    const dates = [...new Set(maps.flatMap(m => [...m.keys()]))].sort();
    const q = x => /[",\r\n]/.test(String(x)) ? '"' + String(x).replace(/"/g, '""') + '"' : String(x);
    const rows = [["Survey date"].concat(cols.map(c => c[1])), ["FRED id"].concat(cols.map(c => (S[c[0]] || {}).fred || ""))].concat(dates.map(d => [d].concat(maps.map(m => m.has(d) ? m.get(d) : ""))));
    const blob = new Blob([rows.map(r => r.map(q).join(",")).join("\r\n")], { type: "text/csv" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "sloos.csv"; document.body.appendChild(a); a.click(); a.remove();
  }

  function depositTables(P) {
    if (!P || P.error) return '<p class="err">Deposit pricing unavailable' + (P && P.error ? ": " + esc(P.error) : "") + "</p>";
    const mon = t => fmtDate(t, "Monthly"), prods = P.table.rows.filter(r => r.key !== "ff_m");
    let h = '<div class="dpgrid"><div><h4 class="atit">Cumulative deposit betas <span class="hint">Δ product rate ÷ Δ fed funds, %</span></h4><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Product</th>' +
      P.legs.map(L => '<th class="r">' + esc(L.kind) + '<span class="dl" style="color:var(--mut)">' + mon(L.start) + " → " + mon(L.end) + (L.end_is_latest ? "*" : "") + "<br>FF " + L.ff_start.toFixed(2) + " → " + L.ff_end.toFixed(2) + "%</span></th>").join("") + "</tr></thead><tbody>" +
      prods.map(r => "<tr><td>" + esc(r.label) + "</td>" + P.legs.map(L => { const b = L.betas[r.key];
        return '<td class="r b" title="' + (b ? b.r0.toFixed(2) + "% → " + b.r1.toFixed(2) + "% (" + (b.d_rate >= 0 ? "+" : "") + Math.round(b.d_rate * 100) + " bp)" : "") + '">' + (b ? b.beta.toFixed(0) + "%" : "–") + "</td>"; }).join("") + "</tr>").join("") +
      '</tbody></table></div><p class="pnote">' + esc(P.note || "") + " * still in progress (ends at the latest month). Hover a beta for the start/end rates.</p></div>";
    const T = P.table;
    h += '<div><h4 class="atit">Rates at quarter-end months <span class="hint">%, FDIC national rates; fed funds monthly avg</span></h4><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Product</th>' +
      T.quarters.map(q => '<th class="r">' + q.slice(0, 4) + " Q" + ((+q.slice(5, 7)) / 3) + "</th>").join("") + "</tr></thead><tbody>" +
      T.rows.map(r => "<tr" + (r.key === "ff_m" ? ' class="ffrow"' : "") + "><td>" + esc(r.label) + "</td>" + r.vals.map(v => '<td class="r">' + (v == null ? "–" : v.toFixed(2)) + "</td>").join("") + "</tr>").join("") + "</tbody></table></div></div></div>";
    return h;
  }

  // Treasury coupon auctions: upcoming + recent results vs the prior-6 same-tenor average
  function auctionsTable(A) {
    if (!A) return '<p class="err">No auction data.</p>';
    const f = (v, n) => v == null ? "–" : v.toFixed(n), dl = (v, n, inv) => v == null ? "" : '<span class="dl ' + ((inv ? -v : v) > 0 ? "pos" : (inv ? -v : v) < 0 ? "neg" : "flat") + '">' + (v > 0 ? "+" : "") + v.toFixed(n) + "</span>";
    const sd = x => fmtDate(x, "Daily");
    let h = "";
    if (A.upcoming && A.upcoming.length) h += '<h4 class="atit">Upcoming coupon auctions <span class="hint">TreasuryDirect; sizes appear once announced</span></h4><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Auction</th><th>Security</th><th class="r">Size</th><th>Announced</th><th>Issue</th></tr></thead><tbody>' +
      A.upcoming.map(u => "<tr><td>" + sd(u.date) + "</td><td><b>" + esc(u.tenor) + "</b>" + (u.reopening ? ' <span class="sid">reopening (' + esc(u.term) + ")</span>" : "") + '</td><td class="r">' + (u.size_bn ? "$" + u.size_bn + "bn" : "tbd") + "</td><td>" + (u.announced ? sd(u.announced) : "–") + "</td><td>" + (u.issue ? sd(u.issue) : "–") + "</td></tr>").join("") + "</tbody></table></div>";
    h += '<h4 class="atit">Recent results <span class="hint">small figures = change vs prior-6 same-tenor average' + (A.stale ? " · STALE" : "") + '</span></h4><div class="tblwrap"><table class="sumtbl atbl"><thead><tr><th>Date</th><th>Security</th><th class="r">Size</th><th class="r">High yield</th><th class="r">Bid-to-cover</th><th class="r">Indirect %</th><th class="r">Direct %</th><th class="r">Dealer %</th><th>vs last 6</th></tr></thead><tbody>' +
      A.recent.map(x => '<tr class="v-' + (x.verdict || "na").replace(" ", "") + '"><td>' + sd(x.date) + "</td><td><b>" + esc(x.tenor) + "</b>" + (x.reopening ? ' <span class="sid">reopen</span>' : "") + '</td><td class="r">$' + x.size_bn + 'bn</td><td class="r">' + (x.yield_kind === "disc. margin" ? f(x.yield, 3) + '% <span class="sid">DM</span>' : f(x.yield, 3) + "%") + '</td><td class="r b">' + f(x.btc, 2) + dl(x.d_btc, 2) +
        '</td><td class="r">' + f(x.indirect, 1) + dl(x.d_indirect, 1) + '</td><td class="r">' + f(x.direct, 1) + '</td><td class="r">' + f(x.dealer, 1) + dl(x.d_dealer, 1, true) + '</td><td><span class="vb">' + esc(x.verdict || "n/a") + "</span></td></tr>").join("") + "</tbody></table></div>" +
      (A.note ? '<p class="pnote">' + esc(A.note) + "</p>" : "");
    return h;
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
        if (p.since) pts = pts.filter(o => o.x >= Date.parse(p.since + "T00:00:00Z"));
        else if (cut) { const c = s.freq === "Quarterly" ? cut - 100 * 864e5 : cut; pts = pts.filter(o => o.x >= c); }
        const col = COLORS[n % COLORS.length], t = (p.types && p.types[n]) || (p.type === "bar" ? "bar" : "line");
        const ds = { type: t, label: (p.labels && p.labels[n]) || s.title, data: pts, borderColor: t === "bar" ? col : (p.types ? "#f0883e" : col), backgroundColor: t === "bar" ? pts.map(o => o.y < 0 ? "#f85149" : col) : (p.fill ? col + "22" : col), borderWidth: t === "bar" ? 0 : (p.types ? 2 : 1.6), pointRadius: t === "line" && p.types ? 1.5 : 0, tension: 0, fill: p.fill ? "origin" : false, order: t === "line" ? 0 : 1 };
        if (p.stacked) {  // component bars / areas keep their own colour; a line overlays as the total
          Object.assign(ds, { borderColor: col, backgroundColor: t === "bar" ? col + "c0" : (p.fill ? col + "99" : col), stack: t === "line" && !p.fill ? "total" : "parts",
            borderWidth: p.fill ? 1 : (t === "bar" ? 0 : 2), pointRadius: 0, fill: p.fill ? (n === 0 ? "origin" : "-1") : false, barPercentage: 1, categoryPercentage: 1 });
        }
        if (p.y2 && p.y2.includes(k)) ds.yAxisID = "y2";
        if (p.dashed && p.dashed.includes(k)) Object.assign(ds, { borderDash: [5, 4], borderColor: "#8b9bb0", backgroundColor: "#8b9bb0", borderWidth: 1.3 });
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

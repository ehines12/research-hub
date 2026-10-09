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
    const kpis = D.kpis ? D.kpis.map(chipTile).join("") : cfg.series.filter(s => s.kpi !== false).map(s => kpiCard(S[s.key])).join("");
    const secs = cfg.sections.map((sec, i) => "<h2>" + esc(sec.title) + '</h2><div class="panels' + (sec.cols === 2 ? " c2" : "") + '">' + sec.panels.map((p, j) =>
      '<div class="panel' + (p.wide ? " wide" : "") + (p.full ? " full" : "") + '"><h4>' + esc(p.title) + "</h4>" + (cfg.panel_latest ? panelLatest(p, S) : "") + '<div class="cv"><canvas id="c' + i + "_" + j + '"></canvas></div>' + (p.note ? '<div class="pnote">' + esc(p.note) + "</div>" : "") + '<div class="src">Source: ' + [...new Set(p.series.map(k => S[k].src_label || "FRED " + S[k].fred))].map(esc).join(" · ") + "</div></div>").join("") + "</div>").join("") +
      (D.summary ? summaryTable(D, cfg) : "");
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
    if (L.target) {  // nowcast: show target quarter, as-of date, change vs prior estimate for that quarter
      c = P ? '<span class="' + cls(L.value - P.value, s) + '">' + fmtChg(L.value - P.value, s.chg) + " vs " + fmtDate(P.date, "Daily").replace(/, \d{4}$/, "") + " est.</span>" : '<span class="flat">first estimate for ' + esc(L.target) + "</span>";
    }
    const tag = s.link ? "a" : "div", href = s.link ? ' href="' + esc(s.link) + '" target="_blank" rel="noopener noreferrer"' : "";
    const tip = (s.src_label || "FRED " + s.fred) + (L.release ? " · latest update after: " + L.release : "") + (s.error ? " · " + esc(s.error) : "");
    const dline = L.target ? esc(L.target) + " · as of " + fmtDate(L.date, "Daily") + (P ? " · prior " + fmtVal(P.value, s.fmt) : "")
                           : fmtDate(L.date, s.freq) + (P ? " · prior " + fmtVal(P.value, s.fmt) : "");
    return "<" + tag + href + ' class="kpi ' + (s.link ? "linked " : "") + (s.status !== "ok" ? s.status : "") + '" title="' + esc(tip) + '"><div class="t">' + esc(s.title) + (s.link ? " " + EXT : "") + '</div><div class="v">' + fmtVal(L.value, s.fmt) +
      '</div><div class="d">' + dline + (s.status === "stale" ? " · STALE" : "") + '</div><div class="c">' + c + "</div></" + tag + ">";
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

"""CNS nowcast: quarter-to-date AUM / revenue / EPS nowcast, backtest, Wealth flow tracker, pipeline conversion.
Writes data/cns_nowcast.json. Every source failure is a warning; the script never raises (exit 0) so the
weekday refresh job is not failed by it.  Real data only: CNS 8-K earnings releases (strategy AUM), CNS monthly
preliminary AUM press releases (PR Newswire), Yahoo Finance daily closes for index-proxy ETFs and fund net assets."""
import json, math, sys, datetime as dt, pathlib, traceback, statistics as st
import requests
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / "data" / "cns_nowcast.json"
SNAPS = ROOT / "data" / "cns_wealth_snaps.json"
WARN = []
def warn(m): WARN.append(m); print("::warning::cns_nowcast: " + m)

PROXY = {"usre": "VNQ", "glre": "REET", "infra": "IGF", "pref": "PFF", "oth": "GNR"}
PROXY_LBL = {"usre": "U.S. real estate (VNQ)", "glre": "Global/intl real estate (REET)", "infra": "Global listed infrastructure (IGF)",
             "pref": "Preferred securities (PFF)", "oth": "Multi-strategy real assets / other (GNR)"}
MAP = {"U.S. Real Estate": "usre", "Global/International Real Estate": "glre", "Global Listed Infrastructure": "infra",
       "Preferred Securities": "pref", "Other": "oth", "Multi-Strategy Real Assets": "oth", "Natural Resource Equities": "oth"}
# Fund universe for the Wealth tracker (fund-level net assets; one class per fund to avoid double counting)
FUNDS = {"CSRSX": "Realty Shares", "CSRIX": "Institutional Realty Shares", "CSDIX": "Real Estate Securities", "CSSPX": "Global Realty",
         "IRFIX": "International Realty", "CSUIX": "Global Infrastructure", "CPXIX": "Preferred Securities & Income",
         "LPXIX": "Low Duration Preferred & Income", "RAPIX": "Real Assets", "PISHX": "Preferred Sec. & Income SMA Shares",
         "CSRE": "Real Estate Active ETF", "CSPF": "Preferred & Income Opp. Active ETF", "CSNR": "Natural Resources Active ETF",
         "CSSD": "Short Duration Pref. Active ETF", "CSIO": "Infrastructure Opp. Active ETF", "CSEN": "Future of Energy Active ETF",
         "CSRA": "Real Assets Active ETF"}
ETFS = {"CSRE", "CSPF", "CSNR", "CSSD", "CSIO", "CSEN", "CSRA"}
S = requests.Session(); S.headers["User-Agent"] = "Mozilla/5.0"

def d(s): return dt.date.fromisoformat(s)
def qend(y, q): return dt.date(y, 3 * q, [31, 30, 30, 31][q - 1])
def qof(day): return day.year, (day.month - 1) // 3 + 1
def prevq(y, q): return (y, q - 1) if q > 1 else (y - 1, 4)
def nextq(y, q): return (y, q + 1) if q < 4 else (y + 1, 1)
def mend(y, m): return (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
def qlabel(y, q): return f"Q{q} {y}"

def yahoo_closes(sym, start="2021-06-01"):
    p1 = int(dt.datetime.combine(d(start), dt.time()).timestamp()); p2 = int(dt.datetime.now().timestamp()) + 86400
    r = S.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"period1": p1, "period2": p2, "interval": "1d", "events": "div"}, timeout=30).json()
    res = r["chart"]["result"][0]; ts = res["timestamp"]; ind = res["indicators"]
    c = ind["quote"][0]["close"]; a = ind["adjclose"][0]["adjclose"] if "adjclose" in ind else c
    out = {}
    for t, x, y in zip(ts, c, a):
        if x is not None: out[dt.datetime.fromtimestamp(t, dt.timezone.utc).date().isoformat()] = (x, y)
    return out

# ---------------- path model ----------------
def build_path(px, days, anchor_day, anchor_strat, month_ends, run_rate, asof):
    """Daily total AUM over `days` (trading days). anchor_strat: {bucket: $M} at anchor_day close.
    month_ends: {date: total $M} known actual month-end totals (> anchor_day, <= asof). Prices used through asof, flat after.
    run_rate: $M net flow per trading day applied after the last known anchor."""
    def p(b, day):
        k = min(day, asof)
        while k.isoformat() not in px[b]: k -= dt.timedelta(days=1)
        return px[b][k.isoformat()][0]
    anchors = [(anchor_day, dict(anchor_strat))]
    cur_day, cur = anchor_day, dict(anchor_strat)
    for me in sorted(month_ends):
        roll = {b: v * p(b, me) / p(b, cur_day) for b, v in cur.items()}
        f = month_ends[me] / sum(roll.values())
        cur = {b: v * f for b, v in roll.items()}; cur_day = me; anchors.append((me, dict(cur)))
    res = []
    for day in days:
        # segment
        seg = [a for a in anchors if a[0] <= day][-1] if any(a[0] <= day for a in anchors) else anchors[0]
        nxt = [a for a in anchors if a[0] > day]
        a_day, a_st = seg
        roll = sum(v * p(b, day) / p(b, a_day) for b, v in a_st.items())
        if nxt:
            n_day, n_st = nxt[0]
            roll_n = sum(v * p(b, n_day) / p(b, a_day) for b, v in a_st.items())
            fac = sum(n_st.values()) / roll_n
            w = (day - a_day).days / max(1, (n_day - a_day).days)
            res.append(roll * (1 + (fac - 1) * w))
        else:
            n = sum(1 for x in days if a_day < x <= day)
            res.append(roll + run_rate * n)
    return res

def strat_buckets(entry, prev_entry=None):
    s = {}
    for name, v in entry["strat"].items():
        if name == "Real Estate":  # combined from Q3 2026 -> split using last available US/global split
            us = prev_entry["strat"]["U.S. Real Estate"]["end"]; gl = prev_entry["strat"]["Global/International Real Estate"]["end"]
            s["usre"] = s.get("usre", 0) + v["end"] * us / (us + gl); s["glre"] = s.get("glre", 0) + v["end"] * gl / (us + gl)
        else:
            b = MAP.get(name)
            if b: s[b] = s.get(b, 0) + (v["end"] or 0)
    return s

def main():
    STRAT = json.loads((HERE / "cns_strategy.json").read_text())
    try:
        sys.path.insert(0, str(HERE)); import monthly; MON = monthly.main()
    except Exception as e:
        warn(f"monthly AUM releases fetch failed ({e}); using cached"); MON = json.loads((HERE / "cns_monthly.json").read_text())
    CO = json.loads((ROOT / "data" / "companies.json").read_text())
    rows = {r["end"]: r for r in [c for c in CO["companies"] if c["ticker"] == "CNS"][0]["rows"]}
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    px = {}
    for b, sym in PROXY.items():
        try: px[b] = yahoo_closes(sym)
        except Exception as e:
            warn(f"Yahoo closes {sym} failed: {e}"); 
    if len(px) < len(PROXY):
        warn("index proxies incomplete; keeping previous nowcast"); old["warnings"] = WARN; OUT.write_text(json.dumps(old, indent=1)); return
    tdays = sorted(d(x) for x in px["usre"])
    last_px = tdays[-1]
    ends = sorted(STRAT)
    prev_of = {ends[i]: ends[i - 1] for i in range(1, len(ends))}
    mon = {d(mend(int(k[:4]), int(k[5:])).isoformat()): v for k, v in MON.items()}

    def nowcast(y, q, asof, known_months, flows_q=None):
        """Return dict for quarter (y,q) given information as of `asof`. known_months: month-end dates whose release is known."""
        pe = qend(*prevq(y, q)); key = pe.isoformat()
        ent = STRAT[key]; pent = STRAT.get(prev_of.get(key, ""), None)
        anc = strat_buckets(ent, pent)
        qs = dt.date(y, 3 * q - 2, 1); qe = qend(y, q)
        days = [x for x in tdays if qs <= x <= qe]
        # project calendar trading days for the future part of the quarter (weekdays)
        k = max(days[-1] if days else pe, pe)
        while k < qe:
            k += dt.timedelta(days=1)
            if k.weekday() < 5 and k > last_px: days.append(k)
        me = {m: mon[m]["tot"]["end"] for m in known_months if m in mon}
        # run-rate: average of the last 3 monthly net flows released before asof
        rel = [m for m in sorted(mon) if m + dt.timedelta(days=10) <= asof][-3:]
        rr_m = st.mean(mon[m]["tot"]["net"] for m in rel) if rel else 0.0
        path = build_path(px, days, pe, anc, me, rr_m / 21.0, asof)
        return {"avg": sum(path) / len(path), "end": path[-1], "days": days, "path": path, "rr_month": rr_m, "anchor": anc}

    def fee_and_eps_models(target_end):
        hist = [r for e, r in sorted(rows.items()) if e < target_end]
        p = hist[-1]; pdays = (d(p["end"]) - qend(*prevq(*qof(d(p["end"]))))).days
        fee = p["rev"] / (p["aum_avg"] * 1000) / pdays  # $M revenue per $M avg AUM per calendar day
        h8 = hist[-8:]
        if len(h8) < 4: return fee, None, None
        xs = [r["rev"] for r in h8]; ys = [r["adj_eps"] for r in h8]
        mx, my = st.mean(xs), st.mean(ys); b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs); a = my - b * mx
        return fee, a, b

    def full(y, q, asof, known):
        nc = nowcast(y, q, asof, known)
        qe = qend(y, q); qd = (qe - qend(*prevq(y, q))).days
        fee, a, b = fee_and_eps_models(qe.isoformat())
        rev = fee * nc["avg"] * qd
        return nc, rev, (a + b * rev) if a is not None else None

    # ---------- backtest ----------
    bt = []
    for key in ends[1:]:
        qe = d(key); y, q = qof(qe)
        r = rows.get(key)
        if not r: continue
        m1, m2, m3 = mend(y, 3 * q - 2), mend(y, 3 * q - 1), qe
        pts = {"M1": (m1, []), "M2": (m2, [m1]), "QE": (m3, [m1, m2])}
        rec = {"q": qlabel(y, q), "end": key, "act_avg": r["aum_avg"], "act_rev": r["rev"], "act_eps": r["adj_eps"]}
        for nm, (asof, known) in pts.items():
            asof_eff = min(asof, last_px)
            try:
                nc, rev, eps = full(y, q, asof_eff, [k for k in known if k + dt.timedelta(days=10) <= asof])
                rec[nm] = {"avg": round(nc["avg"] / 1000, 2), "rev": round(rev, 1), "eps": round(eps, 3) if eps is not None else None}
            except Exception as e:
                warn(f"backtest {key} {nm}: {e}")
        bt.append(rec)
    def stats(nm, f, act):
        e = [(x[nm][f] / x[act] - 1) * 100 for x in bt if nm in x and x[act]]
        if not e: return None
        return {"n": len(e), "mape": round(st.mean(abs(v) for v in e), 2), "bias": round(st.mean(e), 2), "max": round(max(e, key=abs), 2)}
    def eps_stats(nm):
        e = [x[nm]["eps"] - x["act_eps"] for x in bt if nm in x and x[nm]["eps"] is not None]
        return {"n": len(e), "mae": round(st.mean(abs(v) for v in e), 3), "bias": round(st.mean(e), 3)} if e else None
    btstats = {nm: {"avg": stats(nm, "avg", "act_avg"), "rev": stats(nm, "rev", "act_rev"), "eps": eps_stats(nm)} for nm in ("M1", "M2", "QE")}

    # ---------- live nowcast ----------
    today = dt.date.today()
    ly, lq = qof(d(ends[-1])); cy, cq = nextq(ly, lq)
    known = [m for m in (mend(cy, 3 * cq - 2), mend(cy, 3 * cq - 1)) if m in mon]
    nc, rev, eps = full(cy, cq, last_px, known)
    # next quarter: anchor = projected end-of-quarter (flat prices) + run rate
    ny, nq = nextq(cy, cq); nqd = (qend(ny, nq) - qend(cy, cq)).days
    ndays = sum(1 for i in range(1, nqd + 1) if (qend(cy, cq) + dt.timedelta(days=i)).weekday() < 5)
    rr = nc["rr_month"] / 21.0
    n_avg = sum(nc["end"] + rr * i for i in range(1, ndays + 1)) / ndays
    fee, a, b = fee_and_eps_models(qend(cy, cq).isoformat())
    n_rev = fee * n_avg * nqd; n_eps = a + b * n_rev
    qtd = {PROXY_LBL[bk]: round((px[bk][last_px.isoformat()][0] / px[bk][ends[-1]][0] - 1) * 100, 2) for bk in PROXY}
    anc_tot = sum(nc["anchor"].values())
    wts = {PROXY_LBL[bk]: round(v / anc_tot * 100, 1) for bk, v in nc["anchor"].items()}
    path = [{"d": x.isoformat(), "aum": round(v / 1000, 3), "proj": x > last_px} for x, v in zip(nc["days"], nc["path"])]

    # ---------- Wealth flow tracker (weekly snapshots of fund net assets) ----------
    wealth = wealth_tracker(rows, today)
    # ---------- pipeline conversion ----------
    pipe = pipeline_model(rows)

    cons = json.loads((HERE / "consensus.json").read_text())
    out = {"asof_prices": last_px.isoformat(), "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
           "current": {"q": qlabel(cy, cq), "avg_aum": round(nc["avg"] / 1000, 2), "end_aum_flat": round(nc["end"] / 1000, 2),
                       "rev": round(rev, 1), "eps": round(eps, 2), "known_months": [k.isoformat() for k in known],
                       "run_rate_month": round(nc["rr_month"], 0), "fee_bps": round(fee * 365 * 1e4, 2), "eps_model": {"a": round(a, 4), "b": round(b, 5)},
                       "anchor": ends[-1], "anchor_aum": round(anc_tot / 1000, 2), "weights": wts, "qtd_proxy": qtd, "path": path},
           "next": {"q": qlabel(ny, nq), "avg_aum": round(n_avg / 1000, 2), "rev": round(n_rev, 1), "eps": round(n_eps, 2)},
           "consensus": cons, "backtest": bt, "bt_stats": btstats, "wealth": wealth, "pipeline": pipe, "warnings": WARN,
           "sources": {"strategy": {k: v["src"] for k, v in STRAT.items()}, "monthly": {k: v["url"] for k, v in MON.items()},
                       "proxies": PROXY}}
    OUT.write_text(json.dumps(out, indent=1))
    print("cns_nowcast:", out["current"]["q"], out["current"]["avg_aum"], out["current"]["rev"], out["current"]["eps"], btstats)

def wealth_tracker(rows, today):
    snaps = json.loads(SNAPS.read_text()) if SNAPS.exists() else {}
    try:
        S.get("https://fc.yahoo.com", timeout=10); crumb = S.get("https://query1.finance.yahoo.com/v1/test/getcrumb", timeout=10).text
        q = S.get("https://query1.finance.yahoo.com/v7/finance/quote", params={"symbols": ",".join(FUNDS), "crumb": crumb}, timeout=20).json()["quoteResponse"]["result"]
        snap = {x["symbol"]: {"na": x.get("netAssets"), "px": x.get("regularMarketPrice")} for x in q}
        trs = {}
        for s in FUNDS:
            try:
                c = yahoo_closes(s, (today - dt.timedelta(days=30)).isoformat()); k = max(c); trs[s] = c[k][1]
            except Exception: pass
        for s in snap: snap[s]["tr"] = trs.get(s)
        snaps[today.isoformat()] = snap
        SNAPS.write_text(json.dumps(dict(sorted(snaps.items())), indent=0))
    except Exception as e:
        warn(f"Wealth tracker snapshot failed: {e}")
    dates = sorted(snaps)
    # weekly implied flows: last snapshot of each ISO week vs previous week's last snapshot
    wk = {}
    for x in dates: wk[dt.date.fromisoformat(x).isocalendar()[:2]] = x
    wd = sorted(wk.values())
    weeks = []
    for a, b in zip(wd, wd[1:]):
        A, B = snaps[a], snaps[b]; fl = 0.0; n = 0; stale = 0
        for s in FUNDS:
            if s in A and s in B and A[s].get("na") and B[s].get("na") and A[s].get("tr") and B[s].get("tr"):
                if A[s]["na"] == B[s]["na"]: stale += 1
                fl += B[s]["na"] - A[s]["na"] * B[s]["tr"] / A[s]["tr"]; n += 1
        weeks.append({"from": a, "to": b, "flow_m": round(fl / 1e6, 1), "funds": n, "stale": stale})
    last = snaps[dates[-1]] if dates else {}
    mf = sum((v.get("na") or 0) for s, v in last.items() if s not in ETFS) / 1e9
    et = sum((v.get("na") or 0) for s, v in last.items() if s in ETFS) / 1e9
    return {"snapshots": len(dates), "first": dates[0] if dates else None, "last": dates[-1] if dates else None, "weeks": weeks,
            "cov_mf_bn": round(mf, 2), "cov_etf_bn": round(et, 2), "rep_mf_bn": 40.012, "rep_etf_bn": 1.310, "rep_asof": "2026-09-30",
            "funds": [{"sym": s, "name": n, "na_bn": round((last.get(s, {}).get("na") or 0) / 1e9, 3) if last.get(s, {}).get("na") else None, "etf": s in ETFS} for s, n in FUNDS.items()]}

def pipeline_model(rows):
    R = [r for e, r in sorted(rows.items())]
    def ols(xs, ys):
        mx, my = st.mean(xs), st.mean(ys); sxx = sum((x - mx) ** 2 for x in xs)
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx; a = my - b * mx
        ss = sum((y - a - b * x) ** 2 for x, y in zip(xs, ys)); tt = sum((y - my) ** 2 for y in ys)
        n = len(xs); se = math.sqrt(ss / (n - 2) / sxx) if n > 2 else None
        return {"a": round(a, 3), "b": round(b, 3), "r2": round(1 - ss / tt, 3), "n": n, "t": round(b / se, 2) if se else None, "resid_sd": round(math.sqrt(ss / (n - 2)), 3)}
    pts = [(R[i]["pipe"], R[i + 1]["flow_inst"]) for i in range(len(R) - 1) if R[i].get("pipe") is not None]
    pts2 = [(R[i]["pipe"], R[i + 1]["flow_inst"] + R[i + 2]["flow_inst"]) for i in range(len(R) - 2) if R[i].get("pipe") is not None]
    m1 = ols(*zip(*pts)); m2 = ols(*zip(*pts2)); cur = R[-1]["pipe"]
    return {"next1": m1, "next2": m2, "pipe_now": cur, "implied_next_q": round(m1["a"] + m1["b"] * cur, 2), "implied_next_2q": round(m2["a"] + m2["b"] * cur, 2),
            "points": [{"q": R[i]["q"], "pipe": R[i]["pipe"], "next_inst": R[i + 1]["flow_inst"]} for i in range(len(R) - 1)]}

if __name__ == "__main__":
    try: main()
    except Exception:
        traceback.print_exc(); print("::warning::cns_nowcast failed; previous data/cns_nowcast.json kept")
    sys.exit(0)

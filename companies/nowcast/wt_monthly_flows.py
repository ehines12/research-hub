"""WT monthly AUM & net flows -> data/wt_monthly_flows.json (+ data/company-WT-monthly-flows.xlsx).

Source: WisdomTree's "WisdomTree Reports Monthly Metrics for <Month> <Year>" press releases on
ir.wisdomtree.com (the AUM rollforward table, ETP / tokenized AUM; excludes Ceres private assets).
WisdomTree does not furnish these monthly releases on Form 8-K (only quarterly results are), so the IR
release page is the primary source; its URL is stored per month. Every number is stored as reported
($ millions). Nothing is plugged: a month with no release, or a row/column the release does not show,
is stored as null and listed. Roll-forward / month-chain checks are recorded, never applied.
Derived (labelled as such): organic growth = net flows / beginning-of-month AUM x 12, and trailing
6-month averages (only when all 6 months are disclosed).

Run: python3 companies/nowcast/wt_monthly_flows.py   (incremental; --full re-fetches every month)
Warn-only in the weekday refresh: on any failure the previous JSON is kept.
"""
import calendar, datetime as dt, html, json, pathlib, re, sys, time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "wt_monthly_flows.json"
XLSX = ROOT / "data" / "company-WT-monthly-flows.xlsx"
START = "2024-01"
LIST = "https://ir.wisdomtree.com/news-events/press-releases?page={p}"
UA = {"User-Agent": "Mozilla/5.0 (research-hub WT monthly metrics; +https://ehines12.github.io/research-hub/)"}
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
LINK = re.compile(r'https://ir\.wisdomtree\.com/news-events/press-releases/detail/\d+/wisdomtree-reports-monthly-metrics-for-([a-z]+)-(\d{4})[^"#?]*')
MONEY = r"\(?\$[\d,]+(?:\.\d+)?\)?"
PCT = r"\(?-?[\d.]+%\)?"
CATS = ["U.S. Equity", "International Dev. Mkt Equity", "Emerging Market Equity", "Fixed Income",
        "Commodity & Currency", "Alternatives", "Cryptocurrency", "Leveraged & Inverse"]
WIN = 6


def get(url, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def clean(t):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t)


def num(s):
    s = s.replace("$", "").replace(",", "").replace("%", "")
    neg = s.startswith("(") or s.startswith("-")
    x = float(s.strip("()-"))
    return -x if neg else x


def links(full):
    """month -> release URL from the IR press-release listing (newest first, ~10 per page)."""
    out, start = {}, START
    for p in range(1, 60):
        t = get(LIST.format(p=p)) or ""
        found = LINK.findall(t)
        for m in LINK.finditer(t):
            mon, y = m.group(1), m.group(2)
            if mon in MONTHS: out.setdefault(f"{y}-{MONTHS[mon]:02d}", m.group(0))
        if "detail/" not in t: break
        if out and min(out) < start: break
        if not full and p >= 2 and found: break   # incremental: newest pages are enough
    return out


def parse(page, month):
    t = clean(page)
    y, mo = map(int, month.split("-"))
    asof = f"As of {calendar.month_name[mo]} {calendar.monthrange(y, mo)[1]}, {y}"
    i = t.find(asof)
    if i < 0: raise ValueError(f"{month}: '{asof}' not found")
    hdr = re.search(r"Annualized Flow Rate (.*?) Beginning of Period Total AUM", t[i:i + 600])
    j = t.find("Beginning of Period Total AUM", i)
    k = t.find("Blended Total Average Fee Rate", j)
    if j < 0 or k < 0: raise ValueError(f"{month}: rollforward table not found")
    tab = t[j:k + 80]
    cur = re.search(r"Current Total AUM ((?:" + MONEY + r"\s*)+)", tab)
    ncol = len(re.findall(MONEY, cur.group(1)))
    def row(label, after=0):
        m = re.compile(re.escape(label) + r" ((?:" + MONEY + r"\s*)+)((?:" + PCT + r"\s*)*)").search(tab, after)
        if not m: return None, [], [], after
        return m, [num(x) for x in re.findall(MONEY, m.group(1))], [num(x) for x in re.findall(PCT, m.group(2))], m.end()
    _, beg, _, _ = row("Beginning of Period Total AUM")
    lev = tab.find("Leveraged & Inverse")
    _, net, net_rate, _ = row("Total Net Flows", lev if lev > 0 else 0)
    _, mkt, _, _ = row("Market Move")
    _, acq, _, _ = row("Acquired AUM")
    _, end, _, _ = row("Current Total AUM")
    _, avg, _, _ = row("Average Total AUM")
    fee = [num(x) for x in re.findall(r"(\d+) bps", tab[tab.find("Blended Total Average Fee Rate"):])]
    cats = {}
    for c in CATS:
        _, v, r, _ = row(c)
        if v: cats[c] = {"net": v[0], "ann_rate_rep_pct": r[0] if r else None}
    def first(v): return v[0] if len(v) == ncol else (v[0] if ncol == 1 and v else None)
    rec = {
        "columns": (hdr.group(1).strip() if hdr else None), "ncol": ncol,
        "beg": first(beg), "net": first(net), "mkt": first(mkt),
        # 'Acquired AUM' row: the MTD cell is blank in months without an acquisition (value only in QTD/YTD)
        # -> null (blank as published, not zero-filled)
        "acq": acq[0] if len(acq) == ncol else None,
        "end": first(end), "avg": first(avg),
        "ann_rate_rep_pct": net_rate[0] if len(net_rate) == ncol else None,
        "fee_bps": fee[0] if len(fee) == ncol else None,
        "ytd_net": net[-1] if net else None,
        "categories": cats,
    }
    if rec["beg"] is None or rec["net"] is None:
        raise ValueError(f"{month}: beginning AUM / net flows not parsed")
    m = re.search(r"Monthly Metrics for [A-Za-z]+ \d{4} ([A-Z][a-z]+ \d{1,2}, \d{4})", t)
    rec["release_date"] = dt.datetime.strptime(m.group(1), "%B %d, %Y").date().isoformat() if m else None
    return rec


def months_due(today):
    y, m = map(int, START.split("-")); out = []
    while (y, m) < (today.year, today.month):
        out.append(f"{y}-{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


def derive(months):
    by = {r["month"]: r for r in months}
    prev = None
    for r in months:
        r["og_ann_pct"] = round(r["net"] / r["beg"] * 12 * 100, 2) if r.get("net") is not None and r.get("beg") else None
        c = []
        s = r["beg"] + r["net"] + (r["mkt"] or 0) + (r["acq"] or 0) if r.get("end") is not None else None
        if s is not None and abs(s - r["end"]) > 2: c.append(f"beg+net+market+acquired = {s:,.0f} vs reported end {r['end']:,.0f}")
        r["prior_end"] = None
        if prev and prev.get("end") is not None:
            r["prior_end"] = prev["end"]
            if abs(prev["end"] - r["beg"]) > 2: c.append(f"beginning AUM {r['beg']:,.0f} vs prior release's ending {prev['end']:,.0f} (revised)")
        cs = sum(v["net"] for v in r["categories"].values())
        if r["categories"] and abs(cs - r["net"]) > 2: c.append(f"category flows sum {cs:,.0f} vs total {r['net']:,.0f}")
        r["checks"] = c; prev = r
    keys = sorted(by)
    for idx, mth in enumerate(keys):
        r = by[mth]; win = keys[max(0, idx - WIN + 1): idx + 1]
        ok = len(win) == WIN and all(by[w].get("og_ann_pct") is not None for w in win) and \
            win == month_range(win[0], mth)
        r["t6_og_pct"] = round(sum(by[w]["og_ann_pct"] for w in win) / WIN, 2) if ok else None
        r["t6_net"] = round(sum(by[w]["net"] for w in win) / WIN, 1) if ok else None


def month_range(a, b):
    y, m = map(int, a.split("-")); out = []
    while f"{y}-{m:02d}" <= b:
        out.append(f"{y}-{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


def write_xlsx(D):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font
    except ImportError:
        print("openpyxl missing; Excel not written", file=sys.stderr); return
    wb = Workbook(); ws = wb.active; ws.title = "Monthly flows"
    hdr = ["Month", "Release date", "Beginning AUM ($M)", "Net flows ($M)", "Market move ($M)", "Acquired AUM ($M)", "Ending AUM ($M)",
           "Average AUM ($M)", "Organic growth % ann. (derived: net/beg x12)", "WT-reported annualized flow rate %",
           "Trailing 6M avg organic growth % (derived)", "Trailing 6M avg net flows ($M, derived)", "Fee rate (bps)"] + [c + " net flows ($M)" for c in CATS] + ["Source", "Checks"]
    ws.append(hdr)
    for c in ws[1]: c.font = Font(bold=True)
    for r in reversed(D["months"]):
        if r.get("missing"):
            ws.append([r["month"], None] + [None] * (len(hdr) - 4) + [None, "not disclosed: " + r["missing"]]); continue
        ws.append([r["month"], r.get("release_date"), r["beg"], r["net"], r["mkt"], r["acq"], r["end"], r["avg"], r["og_ann_pct"], r["ann_rate_rep_pct"],
                   r["t6_og_pct"], r["t6_net"], r["fee_bps"]] + [r["categories"].get(c, {}).get("net") for c in CATS] + [r["url"], "; ".join(r["checks"])])
    ws.freeze_panes = "C2"
    n = wb.create_sheet("Notes")
    for x in D["notes"]: n.append([x])
    wb.save(XLSX)


def main(full=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    have = {r["month"]: r for r in old.get("months", []) if not r.get("missing")} if not full else {}
    due = months_due(dt.date.today())
    todo = [m for m in due if m not in have]
    warnings = []
    L = {}
    if todo:
        try: L = links(full or any(m < due[-3] for m in todo))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"listing: {e}")
    for m in todo:
        u = L.get(m)
        if not u: continue
        try:
            rec = parse(get(u) or "", m)
            have[m] = {"month": m, "url": u, **rec}; print("  parsed", m)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{m}: {e}")
    months = [have[m] for m in sorted(have) if m >= START]
    for r in months:
        for k in ("og_ann_pct", "t6_og_pct", "t6_net", "checks", "prior_end"): r.pop(k, None)
    derive(months)
    gaps = [m for m in due if m not in have]
    # the newest month is 'not yet released' (WT posts ~8th business day), not a disclosure gap
    pending = [m for m in gaps if m == due[-1]]
    missing = [m for m in gaps if m not in pending]
    rows = sorted(months + [{"month": m, "missing": "no WisdomTree monthly metrics release found for this month"} for m in missing], key=lambda r: r["month"])
    D = {
        "units": "$ millions",
        "coverage": {"from": months[0]["month"] if months else None, "to": months[-1]["month"] if months else None,
                     "n": len(months), "missing": missing, "pending": pending},
        "notes": [
            "Source: WisdomTree 'Reports Monthly Metrics' press releases (ir.wisdomtree.com), AUM rollforward table, $ millions as reported. One link per month. WisdomTree does not file these monthly releases on Form 8-K (EDGAR shows only quarterly-results 8-Ks), so the IR release is the primary source.",
            "Scope: ETP and tokenized AUM; excludes private assets managed by Ceres Partners (~$2.1bn at Sep 30, 2026), which WisdomTree reports only with quarterly results. So monthly AUM here will not tie exactly to the quarterly company-total AUM above.",
            "Beginning AUM = 'Beginning of Period Total AUM' (MTD column) in each month's release. It occasionally differs by a few $M from the prior release's ending AUM (WisdomTree revisions); both are stored and differences flagged.",
            "Acquired AUM: May 2026 includes $4,134M of acquired AUM (later shown as $4,101M in QTD/YTD columns); it is excluded from net flows, as WisdomTree reports it.",
            "DERIVED (not reported): organic growth, annualized = net flows / beginning AUM x 12; trailing 6-month averages = simple mean of the latest 6 months, shown only when all 6 months are disclosed. WisdomTree's own 'Annualized Flow Rate' is shown alongside for reference (it annualizes by day count, so it differs slightly from x12).",
        ],
        "warnings": warnings,
        "months": rows,
    }
    same = {k: v for k, v in old.items() if k not in ("generated",)} == D
    if same and OUT.exists():
        print("no change"); return D
    D = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), **D}
    if not months:
        print("nothing parsed; previous file kept", warnings); return D
    OUT.write_text(json.dumps(D, indent=1))
    write_xlsx(D)
    print(f"{len(months)} months {D['coverage']['from']} -> {D['coverage']['to']}; missing {missing}; pending {pending}; warnings {warnings}")
    return D


if __name__ == "__main__":
    main(full="--full" in sys.argv)

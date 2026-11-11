"""Bank M&A tracker -> data/bank-ma.json (+ data/bank-ma.xlsx).

Scope (v1, per Eric): US bank & thrift whole-company acquisitions ANNOUNCED in calendar 2024 with an
aggregate deal value above $500M at announcement. Branch deals, partial deals, non-bank targets and
FDIC-assisted deals are excluded.

Deal terms live in companies/bank_ma/deals_2024.json, curated by hand from each deal's announcement
8-K exhibits (merger press release and investor presentation). Every field there carries its source
URL and the verbatim snippet it came from; anything the documents do not disclose is left out (blank),
never estimated. Metrics are AS ANNOUNCED (pre-close, management estimates).

Automation (warn-only in the weekday refresh): status and close date only. For any deal not yet
closed/terminated, the acquirer's EDGAR 8-Ks filed after announcement are checked for Item 2.01
(completion) or an 8.01/7.01 completion notice naming the target, and Item 1.02 (termination).
The script NEVER adds deals; new deals are added only by editing the curated file.

Run: python3 companies/nowcast/bank_ma.py          (refresh pending deals, rebuild outputs)
     python3 companies/nowcast/bank_ma.py --full   (re-verify close status of every deal)
     python3 companies/nowcast/bank_ma.py --offline (rebuild outputs only, no network)
"""
import datetime as dt, html, json, pathlib, re, statistics, sys, time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CUR = ROOT / "companies" / "bank_ma" / "deals_2024.json"
OUT = ROOT / "data" / "bank-ma.json"
XLSX = ROOT / "data" / "bank-ma.xlsx"
# SEC asks automated clients to identify themselves and stay under 10 requests/second.
UA = {"User-Agent": "Eric Hines research-hub bank M&A tracker hub@example.com"}
PAUSE = 0.25
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"
CIK = {"WTFC": 1015328, "UMBF": 101382, "SSB": 764038, "WSBC": 203596, "RNST": 715072, "BUSE": 314489,
       "AUB": 883948, "ONB": 707179, "INDB": 776901, "BHLB": 1108134}
# words that identify the target inside a completion 8-K (first match wins)
TNAME = {"wtfc-mcbc": "Macatawa", "umbf-htlf": "Heartland|HTLF", "ssb-ibtx": "Independent Bank Group", "wsbc-pfc": "Premier Financial",
         "rnst-fbms": "The First", "buse-cfb": "CrossFirst", "aub-sasr": "Sandy Spring", "onb-bremer": "Bremer",
         "indb-ebtc": "Enterprise", "bhlb-brkl": "Brookline"}

# column spec: key, label, unit/format, summary stats?
COLS = [
    ("deal_value_m", "Deal value ($M)", "m", True), ("price_per_share", "Price / share ($)", "usd", False),
    ("premium", "Premium to unaffected (%)", "pct1", True), ("consideration", "Consideration", "txt", False),
    ("p_tbv", "P/TBV (x)", "x2", True), ("p_ltm_eps", "P/LTM EPS (x)", "x1", True), ("p_fwd_eps", "P/forward EPS (x)", "x1", True),
    ("cdp", "Core deposit premium (%)", "pct1", True),
    ("tgt_assets_b", "Target assets ($B)", "b", True), ("tgt_deposits_b", "Target deposits ($B)", "b", True), ("tgt_loans_b", "Target loans ($B)", "b", True),
    ("tgt_roaa", "Target ROAA (%)", "pct2", True), ("tgt_npa", "Target NPAs/assets (%)", "pct2", True), ("tgt_cre", "Target CRE concentration (%)", "pct0", True),
    ("eps_accr", "EPS accretion, fully phased (%)", "pct1", True), ("tbv_dil", "TBV dilution at close (%)", "pct1", True),
    ("earnback", "TBV earnback (yrs)", "n1", True), ("cost_saves", "Cost saves (% of target opex)", "pct1", True),
    ("credit_mark_pct", "Credit mark (% loans)", "pct2", True), ("credit_mark_m", "Credit mark ($M)", "m", True),
    ("rate_mark_m", "Loan rate mark ($M)", "m", True), ("pf_cet1", "Pro forma CET1 at close (%)", "pct1", True),
    ("tgt_own", "Target ownership of pro forma (%)", "pct1", True),
]


def get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                time.sleep(PAUSE)
                return r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def clean(t):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ").replace("\u200b", " ")
    return re.sub(r"\s+", " ", t)


def iso(s):
    return dt.datetime.strptime(s, "%B %d, %Y").date().isoformat()


def close_check(d):
    """Return dict(status, close_date, src, q) from the acquirer's 8-Ks, or None if nothing found."""
    cik = CIK[d["acq_ticker"]]
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
    name = TNAME[d["id"]]
    cands = []
    for i, form in enumerate(sub["form"]):
        if form not in ("8-K", "8-K/A") or sub["filingDate"][i] <= d["announced"]: continue
        items = sub["items"][i] or ""
        if "2.01" in items or "1.02" in items or "8.01" in items:
            cands.append((sub["filingDate"][i], sub["accessionNumber"][i], sub["primaryDocument"][i], items))
    cands.sort(key=lambda c: ("2.01" not in c[3] and "1.02" not in c[3], c[0]))  # completion/termination items first
    for fd, acc, fn, items in cands[:40]:
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fn}"
        t = clean(get(url))
        if not re.search(name, t): continue
        if "1.02" in items:
            m = re.search(r"[^.]{0,200}terminat[^.]{0,250}" + "", t, re.I)
            if m and re.search(name, m.group(0)):
                dm = re.search(MONTH, m.group(0))
                return {"status": "terminated", "close_date": iso(dm.group(0)) if dm else fd, "close_src": url, "close_q": m.group(0).strip()[:300], "close_filed": fd}
        t2 = re.sub(r"\b(Inc|Corp|Co|Ltd|N\.A)\.", r"\1", t)
        pats = [r"completion(?: \(the “Closing”\))? on (" + MONTH + r")[^.]{0,250}",
                r"(?:On|Effective as of|Effective) (" + MONTH + r")[^.]{0,300}?complet[^.]{0,200}"]
        hits = []
        for p in pats:
            for m in re.finditer(p, t2):
                g = m.group(0); score = (bool(re.search(name, g)), "previously" in g)
                if not re.search(r"complet(?:ed|ion)", g) or re.search(r"expect|anticipat|will ", g): continue
                if score[0] or ("2.01" in items and score[1]): hits.append((score, m.start(), g, m.group(1)))
        if hits:
            hits.sort(key=lambda h: (not h[0][0], not h[0][1], h[1]))
            _, _, g, ds = hits[0]
            return {"status": "closed", "close_date": iso(ds), "close_src": url, "close_q": g.strip()[:300], "close_filed": fd}
    return None


def stats(deals):
    out = {}
    for k, lab, f, s in COLS:
        if not s: continue
        xs = [d["f"][k]["v"] for d in deals if k in d["f"] and isinstance(d["f"][k]["v"], (int, float))]
        out[k] = {"n": len(xs), "median": round(statistics.median(xs), 3) if xs else None, "mean": round(statistics.fmean(xs), 3) if xs else None}
    return out


def write_xlsx(D):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    wb = Workbook(); ws = wb.active; ws.title = "Deals"
    hdr = ["Announced", "Status", "Close date (actual)", "Expected close (at announcement)", "Acquirer", "Acquirer ticker", "Target", "Target ticker", "Target state", "Deal type"] + [c[1] for c in COLS] + ["EPS accretion basis", "Press release", "Investor presentation", "Close source"]
    ws.append(hdr)
    for c in ws[1]: c.font = Font(bold=True); c.alignment = Alignment(wrap_text=True, vertical="top")
    def val(d, k): x = d["f"].get(k); return x["v"] if x else None
    srcs = lambda d, i: list(d["sources"].values())[i] if len(d["sources"]) > i else None
    for d in D["deals"]:
        ws.append([d["announced"], d["status"], d.get("close_date"), val(d, "expected_close"), d["acquirer"], d["acq_ticker"], d["target"], d["tgt_ticker"], val(d, "tgt_state"), d.get("deal_type", "Acquisition")] +
                  [val(d, c[0]) for c in COLS] + [(d["f"].get("eps_accr") or {}).get("note") or (d["f"].get("eps_note") or {}).get("v"), srcs(d, 0), srcs(d, 1), d.get("close_src")])
    n0 = ws.max_row
    for lab, key in (("Median", "median"), ("Average", "mean")):
        ws.append([lab + " (all deals)"] + [None] * 9 + [D["summary"][c[0]][key] if c[3] else None for c in COLS])
        for c in ws[ws.max_row]: c.font = Font(bold=True)
    ws.append(["n disclosed"] + [None] * 9 + [D["summary"][c[0]]["n"] if c[3] else None for c in COLS])
    ws.freeze_panes = "H2"
    for col in ws.columns: ws.column_dimensions[col[0].column_letter].width = 14
    p = wb.create_sheet("Provenance")
    p.append(["Deal", "Field", "Value", "Note", "Source URL", "Verbatim snippet from source"])
    for c in p[1]: c.font = Font(bold=True)
    labels = {c[0]: c[1] for c in COLS}; labels.update(tgt_state="Target state", expected_close="Expected close", eps_note="EPS impact (not quantified)")
    for d in D["deals"]:
        nm = f"{d['acq_ticker']} / {d['tgt_ticker'] if d['tgt_ticker'] != 'private' else d['target']}"
        for k, x in d["f"].items():
            p.append([nm, labels.get(k, k), x["v"], x.get("note"), x["src"], x["q"]])
        if d.get("close_src"): p.append([nm, "Status / close date", f"{d['status']} {d.get('close_date') or ''}".strip(), "From acquirer 8-K (auto-checked)", d["close_src"], d.get("close_q")])
    n = wb.create_sheet("Notes")
    for x in D["notes"] + D["exclusions"]: n.append([x])
    wb.save(XLSX)


def main(full=False, offline=False):
    cur = json.loads(CUR.read_text())
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev = {d["id"]: d for d in old.get("deals", [])}
    warnings, deals = [], []
    for d in cur["deals"]:
        d = dict(d); p = prev.get(d["id"], {})
        for k in ("status", "close_date", "close_src", "close_q", "close_filed", "checked"):
            if k in p: d[k] = p[k]
        d.setdefault("status", "pending")
        d.setdefault("deal_type", "Acquisition")
        for x in d["f"].values():
            if x.get("q"): x["q"] = x["q"].replace("â”,", "")
        if not offline and (full or d["status"] == "pending"):
            try:
                r = close_check(d)
                if r: d.update(r)
                elif d["status"] != "pending": warnings.append(f"{d['id']}: no completion 8-K found on re-check; kept {d['status']}")
                d["checked"] = dt.date.today().isoformat()
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{d['id']}: close check failed: {e}")
        deals.append(d)
    deals.sort(key=lambda d: d["announced"])
    D = {
        "scope": cur.get("scope") or "US bank & thrift whole-company acquisitions announced 2024-01-01 to 2024-12-31, aggregate deal value > $500M at announcement",
        "notes": [
            "Metrics are AS ANNOUNCED: deal value, price per share, multiples and pro forma estimates are from the announcement-day merger press release and investor presentation (8-K exhibits), based on the acquirer's share price before announcement. Final closing values differ for stock deals.",
            "Nothing is estimated. A blank (–) means the announcement documents did not disclose that metric. Hover a value (or open a row) to see the verbatim source text; every row links to its source documents on SEC EDGAR.",
            "P/forward EPS uses the year the company disclosed (mostly 2025E consensus; INDB/EBTC is 2026E per INDB management). No deal in this set disclosed a P/LTM EPS multiple, so that column is blank.",
            "EPS accretion is the headline figure as disclosed, which in every case assumes fully phased-in cost savings and excludes one-time merger charges (the year is shown in the row detail). No deal disclosed a separate partially-phased year-1 figure; Wintrust/Macatawa gave no number ('accretive in first year').",
            "Core deposit premium is shown only where the company labelled it as such (RNST/FBMS, AUB/SASR); core deposit intangible assumptions are not substituted for it.",
            "Cost saves are % of the target's noninterest expense, except BHLB/BRKL (merger of equals), which disclosed 12.6% of the combined company's expense base. Pro forma CET1 is the consolidated ratio at close except WSBC/PFC (bank-level Tier 1 common, the figure disclosed).",
            "Target ROAA, NPAs/assets and CRE concentration are as of the latest quarter cited in each deck (period shown in row detail); HTLF ROAA is the adjusted (non-GAAP) figure UMB disclosed.",
            "Status and actual close date are checked automatically against each acquirer's EDGAR 8-K filings (Item 2.01 completion). New deals are never added automatically; the deal list is curated.",
        ],
        "exclusions": [
            "Excluded: Capital One / Discover Financial (announced Feb 2024, ~$35.3B) - Discover is a card network and consumer lender rather than a bank/thrift franchise, and its size would dominate the averages.",
            "Excluded: National Bank of Canada / Canadian Western Bank (non-US target); FirstSun / HomeStreet (below $500M and later terminated); FDIC-assisted transactions; branch, partial and non-bank (wealth, fintech, insurance) acquisitions.",
            "Below the $500M threshold in 2024 (not shown): e.g. German American / Heartland BancCorp (~$330M), ConnectOne / First of Long Island (~$284M).",
            "Coverage limits: the deal list was built from SEC EDGAR filings (merger 8-Ks, Forms 425/S-4/DEFM14A filed by bank holding companies). A deal whose acquirer and target both file only with bank regulators (not the SEC) could be missed.",
        ],
        "warnings": warnings,
        "summary": stats(deals),
        "columns": [{"key": k, "label": lab, "fmt": f, "stat": s} for k, lab, f, s in COLS],
        "deals": deals,
    }
    same = {k: v for k, v in old.items() if k != "generated"} == {k: v for k, v in D.items()}
    if same and XLSX.exists():
        print("no change", warnings); return D
    D = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"), **D}
    OUT.write_text(json.dumps(D, indent=1, ensure_ascii=False))
    write_xlsx(D)
    from collections import Counter
    print(f"{len(deals)} deals; status {dict(Counter(d['status'] for d in deals))}; warnings {warnings}")
    return D


if __name__ == "__main__":
    main(full="--full" in sys.argv, offline="--offline" in sys.argv)

"""Bank M&A tracker -> data/bank-ma.json (+ data/bank-ma.xlsx).

Scope (per Eric): US bank & thrift whole-company acquisitions ANNOUNCED from 2024-01-01 through
2026-11-11 with an aggregate deal value above $500M at announcement. Branch deals, partial deals,
non-bank targets and FDIC-assisted deals are excluded. Pre-2024 deals are deliberately held off the page.

Deal terms live in companies/bank_ma/deals_*.json (deals_2024.json, deals_2025_2026.json), curated by
hand from each deal's announcement
8-K exhibits (merger press release and investor presentation). Every field there carries its source
URL and the verbatim snippet it came from; anything the documents do not disclose is left out (blank),
never estimated. Metrics are AS ANNOUNCED (pre-close, management estimates).

Automation (warn-only in the weekday refresh):
  * Status / close date: for any deal not yet closed/terminated, the acquirer's EDGAR 8-Ks filed after
    announcement (and the target's, when the target is an SEC filer) are checked for Item 2.01
    (completion) or an 8.01 completion notice naming the other party, and Item 1.02 (termination).
    The latest "expected to close ..." sentence from those 8-Ks is kept as an expected-close update.
  * Review candidates: 8-Ks from bank/thrift SIC codes filed in the last 45 days that announce a
    merger agreement with a stated value >= $500M (or no parsable value) are listed as review
    candidates in data/bank-ma.json. They are NEVER added to the deal table automatically.
New deals are added only by editing the curated files.

Run: python3 companies/nowcast/bank_ma.py          (refresh pending deals, rebuild outputs)
     python3 companies/nowcast/bank_ma.py --full   (re-verify close status of every deal)
     python3 companies/nowcast/bank_ma.py --offline (rebuild outputs only, no network)
"""
import datetime as dt, html, json, pathlib, re, statistics, sys, time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
CURDIR = ROOT / "companies" / "bank_ma"  # deals_*.json
OUT = ROOT / "data" / "bank-ma.json"
XLSX = ROOT / "data" / "bank-ma.xlsx"
# SEC asks automated clients to identify themselves and stay under 10 requests/second.
UA = {"User-Agent": "Eric Hines research-hub bank M&A tracker hub@example.com"}
PAUSE = 0.25
MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}"
CIK = {"WTFC": 1015328, "UMBF": 101382, "SSB": 764038, "WSBC": 203596, "RNST": 715072, "BUSE": 314489,
       "AUB": 883948, "ONB": 707179, "INDB": 776901, "BHLB": 1108134,
       "COLB": 887343, "SBCF": 730708, "CBSH": 22356, "HBAN": 49196, "PNFP": 1115055, "PNC": 713676, "FITB": 35527,
       "NIC": 1174850, "FSUN": 1709442, "ASB": 7789, "CVBF": 354647, "OCFC": 1004702, "PB": 1068851, "CLBK": 1723596,
       "WAFD": 936528, "PEBO": 318300, "FHB": 36377}
# Target CIKs (SEC-filing targets) -- their own completion/termination 8-Ks are checked too.
# Banco Santander files 6-Ks as a foreign private issuer, so Santander/Webster relies on Webster's 8-Ks.
TCIK = {"colb-ppbi": 1028918, "hban-vbtx": 1501570, "pnfp-snv": 18349, "fitb-cma": 28412, "nic-mofg": 1412665,
        "fsun-ffwm": 1413837, "hban-cade": 1299939, "cvbf-htbk": 1053352, "ocfc-ffic": 923139, "pb-stel": 1473844,
        "clbk-nfbk": 1493225, "san-wbs": 801337, "fhb-tcbk": 356171, "pebo-cbnk": 1419536, "cbsh-finemark": 1586628}
# words that identify the acquirer inside a target-filed 8-K
ANAME = {"colb-ppbi": "Columbia Banking", "hban-vbtx": "Huntington", "pnfp-snv": "Pinnacle", "fitb-cma": "Fifth Third",
         "nic-mofg": "Nicolet", "fsun-ffwm": "FirstSun", "hban-cade": "Huntington", "cvbf-htbk": "CVB Financial",
         "ocfc-ffic": "OceanFirst", "pb-stel": "Prosperity", "clbk-nfbk": "Columbia Financial", "san-wbs": "Santander",
         "fhb-tcbk": "First Hawaiian", "pebo-cbnk": "Peoples Bancorp", "cbsh-finemark": "Commerce Bancshares"}
# words that identify the target inside a completion 8-K (first match wins)
TNAME = {"wtfc-mcbc": "Macatawa", "umbf-htlf": "Heartland|HTLF", "ssb-ibtx": "Independent Bank Group", "wsbc-pfc": "Premier Financial",
         "rnst-fbms": "The First", "buse-cfb": "CrossFirst", "aub-sasr": "Sandy Spring", "onb-bremer": "Bremer",
         "indb-ebtc": "Enterprise", "bhlb-brkl": "Brookline",
         "colb-ppbi": "Pacific Premier", "sbcf-villages": "Villages Bancorporation|Citizens First", "cbsh-finemark": "FineMark",
         "hban-vbtx": "Veritex", "pnfp-snv": "Synovus", "pnc-firstbank": "FirstBank", "fitb-cma": "Comerica",
         "nic-mofg": "MidWest ?One", "fsun-ffwm": "First Foundation", "hban-cade": "Cadence", "asb-anb": "American National",
         "cvbf-htbk": "Heritage Commerce|Heritage Bank of Commerce", "ocfc-ffic": "Flushing", "pb-stel": "Stellar",
         "clbk-nfbk": "Northfield", "san-wbs": "Webster", "fhb-tcbk": "TriCo", "wafd-everbank": "EverBank",
         "pebo-cbnk": "Capital Bancorp|Capital Bank", "umbf-eldorado": "El Dorado"}
BANK_SIC = {"6021", "6022", "6035", "6036"}

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


def _filings(cik, after):
    sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json"))["filings"]["recent"]
    out = []
    for i, form in enumerate(sub["form"]):
        if form not in ("8-K", "8-K/A") or sub["filingDate"][i] <= after: continue
        out.append((sub["filingDate"][i], sub["accessionNumber"][i], sub["primaryDocument"][i], sub["items"][i] or ""))
    return out


def close_check(d):
    """Return dict(status, close_date, src, q) from acquirer/target 8-Ks; or {'exp_update': ...}; or None."""
    checks = []
    if d["acq_ticker"] in CIK: checks.append((CIK[d["acq_ticker"]], TNAME[d["id"]]))
    if d["id"] in TCIK: checks.append((TCIK[d["id"]], ANAME[d["id"]]))
    exp = None
    for cik, name in checks:
        cands = [c for c in _filings(cik, d["announced"]) if re.search(r"2\.01|1\.02|8\.01|7\.01|3\.01|5\.01", c[3])]
        cands.sort(key=lambda c: ("2.01" not in c[3] and "1.02" not in c[3], c[0]))  # completion/termination items first
        for fd, acc, fn, items in cands[:40]:
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{fn}"
            t = clean(get(url))
            if not re.search(name, t): continue
            t2 = re.sub(r"\b(Inc|Corp|Co|Ltd|N\.A|S\.A)\.", r"\1", t)
            if "1.02" in items or re.search(r"(mutual(ly)? (agreed|agreement) to terminate|terminat\w+ (of )?the (merger|agreement))", t2, re.I):
                m = re.search(r"[^.]{0,200}terminat[^.]{0,250}", t2, re.I)
                if m and re.search(name, m.group(0)) and not re.search(r"could|may give rise|right to terminate", m.group(0)):
                    dm = re.search(MONTH, m.group(0))
                    return {"status": "terminated", "close_date": iso(dm.group(0)) if dm else fd, "close_src": url, "close_q": m.group(0).strip()[:300], "close_filed": fd}
            CD = r"\(the “ ?Closing Date ?”\)"
            pats = [r"completion(?: \(the “Closing”\))? on (" + MONTH + r")[^.]{0,250}",
                    r"(?:On|Effective(?: as of| on)?) (" + MONTH + r")[^.]{0,300}?(?:complet|consummat)[^.]{0,200}",
                    r"[^.]{0,120}closing on (" + MONTH + r") " + CD + r"[^.]{0,200}",
                    r"[^.]{0,120}(" + MONTH + r") " + CD + r"[^.]{0,200}"]
            hits = []
            for p in pats:
                for m in re.finditer(p, t2):
                    g = m.group(0); score = (bool(re.search(name, g)), "previously" in g)
                    if not re.search(r"complet(?:ed|ion)|consummat|Closing Date", g) or re.search(r"expect|anticipat|will |recently", g): continue
                    if score[0] or ("2.01" in items and (score[1] or "Closing Date" in g)) or re.search(r"announc\w* the completion of the (?:Merger|merger|acquisition|Acquisition)", g): hits.append((score, m.start(), g, m.group(1)))
            if hits:
                hits.sort(key=lambda h: (not h[0][0], not h[0][1], h[1]))
                _, _, g, ds = hits[0]
                return {"status": "closed", "close_date": iso(ds), "close_src": url, "close_q": g.strip()[:300], "close_filed": fd}
            # latest expected-close statement (8.01/7.01 approval or update releases)
            for m in re.finditer(r"[^.]{0,160}(?:expect|anticipat)\w* (?:to|that)[^.]{0,60}(?:close|clos\w+|complet\w+)[^.]{0,120}", t2):
                g = m.group(0)
                if re.search(r"forward-looking|risk|may not|could", g, re.I) or not re.search(r"20\d\d|quarter|month|year|soon|shortly|on or about", g): continue
                if exp is None or fd > exp["filed"]: exp = {"q": g.strip()[:300], "src": url, "filed": fd}
                break
    return {"exp_update": exp} if exp else None


VALRX = re.compile(r"[^.]{0,120}(?:valued at|transaction value|aggregate (?:deal |transaction )?value|deal value|aggregate (?:merger )?consideration)[^.$]{0,40}?\$\s?([\d.,]+)\s?(billion|million|bn|mm)\b[^.]{0,80}", re.I)


def candidates(known):
    """Warn-only: recent bank/thrift 8-Ks (Item 1.01) announcing a merger agreement whose stated deal value is
    >= $500M, or whose value could not be parsed. Never added to the deal table."""
    import urllib.parse
    end = dt.date.today(); start = end - dt.timedelta(days=45); groups = {}
    for q in ('"definitive merger agreement"', '"definitive agreement"', '"agreement and plan of merger"', '"agreement and plan of reorganization"'):
        u = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode({"q": q, "forms": "8-K", "dateRange": "custom", "startdt": start.isoformat(), "enddt": end.isoformat()})
        try: hits = json.loads(get(u))["hits"]["hits"]
        except Exception as e: return [{"error": f"full-text search failed: {e}"}]  # noqa: BLE001
        for h in hits:
            s_ = h["_source"]
            if not BANK_SIC & set(s_.get("sics") or []) or "1.01" not in (s_.get("items") or []): continue
            acc, fn = h["_id"].split(":", 1); ciks = [int(c) for c in s_.get("ciks") or []]
            fdt = s_.get("file_date") or ""
            if any(c == kc and abs((dt.date.fromisoformat(fdt) - dt.date.fromisoformat(ka)).days) <= 21 for c in ciks for kc, ka in known): continue
            g = groups.setdefault(acc, {"filed": fdt, "company": (s_.get("display_names") or [""])[0], "cik": ciks[0], "docs": set()})
            g["docs"].add(fn)
    out = []
    for acc, g in sorted(groups.items(), key=lambda kv: kv[1]["filed"], reverse=True)[:15]:
        base = f"https://www.sec.gov/Archives/edgar/data/{g['cik']}/{acc.replace('-', '')}/"
        docs = sorted(g["docs"], key=lambda f: ("99" not in f, f))[:3]
        val = q2 = None; url = base + docs[0]
        for fn in docs:
            try: t = clean(get(base + fn))
            except Exception: continue  # noqa: BLE001
            if not re.search(r"bank|bancorp|bancshares|financial", t, re.I) or not re.search(r"merger|acqui", t, re.I): continue
            m = VALRX.search(t)
            if m:
                n = float(m.group(1).replace(",", "")); val = n * 1000 if m.group(2).lower() in ("billion", "bn") else n
                q2 = m.group(0).strip()[:250]; url = base + fn; break
        if val is not None and val < 500: continue
        out.append({"filed": g["filed"], "company": g["company"], "url": url, "value_m": val, "q": q2 or "Deal value not stated in the 8-K text (check exhibits)"})
    return out


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
        if d.get("exp_update"): p.append([nm, "Expected close (latest filing)", None, f"From 8-K filed {d['exp_update']['filed']} (auto-checked)", d["exp_update"]["src"], d["exp_update"]["q"]])
        if d.get("close_src"): p.append([nm, "Status / close date", f"{d['status']} {d.get('close_date') or ''}".strip(), "From acquirer 8-K (auto-checked)", d["close_src"], d.get("close_q")])
    if D.get("candidates"):
        c = wb.create_sheet("Review candidates")
        c.append(["Filed", "Company", "Stated value ($M)", "Snippet", "Source URL", "NOT included in the deal table - for manual review only"])
        for x in D["candidates"]:
            if "error" not in x: c.append([x.get("filed"), x.get("company"), x.get("value_m"), x.get("q"), x.get("url")])
    n = wb.create_sheet("Notes")
    for x in D["notes"] + D["exclusions"]: n.append([x])
    wb.save(XLSX)


def main(full=False, offline=False):
    cur = {"deals": [d for f in sorted(CURDIR.glob("deals_*.json")) for d in json.loads(f.read_text())["deals"]]}
    assert all(d["announced"] >= "2024-01-01" for d in cur["deals"]), "pre-2024 deals are held off the page"
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    prev = {d["id"]: d for d in old.get("deals", [])}
    warnings, deals = [], []
    for d in cur["deals"]:
        d = dict(d); p = prev.get(d["id"], {})
        for k in ("status", "close_date", "close_src", "close_q", "close_filed", "checked", "exp_update"):
            if k in p: d[k] = p[k]
        d.setdefault("status", "pending")
        d.setdefault("deal_type", "Acquisition")
        for x in d["f"].values():
            if x.get("q"): x["q"] = x["q"].replace("â”,", "")
        if not offline and (full or d["status"] == "pending"):
            try:
                r = close_check(d)
                if r and "status" in r: d.pop("exp_update", None)
                if r: d.update(r)
                elif d["status"] != "pending": warnings.append(f"{d['id']}: no completion 8-K found on re-check; kept {d['status']}")
                d["checked"] = dt.date.today().isoformat()
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{d['id']}: close check failed: {e}")
        deals.append(d)
    deals.sort(key=lambda d: d["announced"])
    cands = old.get("candidates", [])
    if not offline:
        try:
            known = [(c, d["announced"]) for d in deals for c in ([CIK.get(d["acq_ticker"])] + [TCIK.get(d["id"])]) if c]
            cands = candidates(known)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"review-candidate scan failed: {e}")
    D = {
        "scope": "US bank & thrift whole-company acquisitions announced 2024-01-01 to 2026-11-11, aggregate deal value > $500M at announcement",
        "notes": [
            "Metrics are AS ANNOUNCED: deal value, price per share, multiples and pro forma estimates are from the announcement-day merger press release and investor presentation (8-K exhibits / Rule 425 filings), based on the acquirer's share price before announcement. Final closing values differ for stock deals.",
            "Nothing is estimated or derived. A blank (–) means the announcement documents did not disclose that metric (or disclosed it only qualitatively, e.g. 'modestly accretive' — see row detail). Every value links to its EDGAR source with the verbatim text it came from.",
            "Two investor decks were filed as slide images only (PNC/FirstBank, HBAN/Cadence): values from them are transcribed from the slide image and flagged in the row detail; the EDGAR link points to the filed exhibit.",
            "P/forward EPS uses the year the company disclosed: mostly next-year consensus (2025E for 2024 deals, 2026E for 2025 deals); CVBF/HTBK and FHB/TCBK disclosed only 2027E. P/LTM EPS is shown where disclosed (COLB/PPBI, SBCF/Villages, PB/STEL, PEBO/CBNK).",
            "EPS accretion is the headline figure as disclosed, assuming fully phased-in cost savings and excluding one-time charges; the year (2025E–2028E) is in the row detail. Santander/Webster disclosed only a group-level range (c.7–8% by 2028), so it is left blank.",
            "TBV dilution is shown as a positive number; FITB/CMA disclosed TBVPS ACCRETION (0.1%), shown as -0.1. Core deposit premium is shown only where the company labelled it as such.",
            "Cost saves are % of the target's noninterest expense, except mergers where only a combined-base figure was disclosed: BHLB/BRKL (12.6%), PNFP/SNV (10%), WAFD/EverBank (~11%) and Santander/Webster (~19% of the combined U.S. cost base).",
            "Pro forma CET1 is the consolidated ratio at close as disclosed (WSBC/PFC bank-level; HBAN/Cadence adjusted CET1 incl. AOCI; Santander/Webster is Santander group CET1; FSUN/FFWM is the 2027 pro forma figure).",
            "Target ROAA, NPAs/assets, CRE concentration, assets, deposits and loans are as of the latest quarter cited in each deck (period shown in row detail).",
            "WaFd/EverBank is a reverse merger: WaFd is the legal acquirer and issues shares, EverBank is the accounting acquirer and its holders own ~59%. Purchase-accounting marks there apply to WaFd, so the mark columns are blank for that row. Columbia Financial/Northfield metrics are at the midpoint of the preliminary appraisal for Columbia's second-step conversion.",
            "Status and actual close date are checked automatically each weekday against EDGAR 8-K filings by the acquirer and (where it files with the SEC) the target: Item 2.01 completion, Item 1.02 termination. The latest 'expected to close' statement from those filings is shown for pending deals. New deals are never added automatically; the deal list is curated.",
        ],
        "exclusions": [
            "Not shown: deals announced before 2024 (held off the page by design).",
            "Excluded: Capital One / Discover Financial (announced Feb 2024, ~$35.3B) - Discover is a card network and consumer lender rather than a bank/thrift franchise, and its size would dominate the averages.",
            "Excluded: non-US targets (e.g. National Bank of Canada / Canadian Western Bank; foreign deals by US-listed banks); FDIC-assisted transactions; branch, partial and non-bank (wealth, fintech, insurance) acquisitions; Green Dot / CommerceOne / Smith Ventures (fintech-bank split transaction).",
            "Below the $500M threshold at announcement (not shown), e.g.: 2024 - German American / Heartland BancCorp (~$330M), ConnectOne / First of Long Island (~$284M), FirstSun / HomeStreet (later terminated); 2025-26 - Glacier / Guaranty Bancshares ($476M at announcement; ~$537M at close), Eastern / HarborOne (~$490M), FB Financial / Southern States (~$381M), Burke & Herbert / LINKBANCORP (~$354M), Home BancShares / Mountain Commerce (~$150M).",
            "Coverage limits: the deal list was built from SEC EDGAR filings (merger 8-Ks, Forms 425/S-4/DEFM14A, full-text search through 2026-11-11). A deal whose acquirer and target both file only with bank regulators (not the SEC) could be missed.",
        ],
        "warnings": warnings,
        "candidates": cands,
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
    print(f"{len(deals)} deals; status {dict(Counter(d['status'] for d in deals))}; warnings {warnings}; candidates {len(cands)}")
    for c in cands: print("  review candidate:", c)
    return D


if __name__ == "__main__":
    main(full="--full" in sys.argv, offline="--offline" in sys.argv)

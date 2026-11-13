"""Houlihan Lokey (HLI) quarterly KPIs -> companies/raw/hli_raw.json, then rebuilds data/companies.json (+ data/company-HLI.xlsx).

Source: HLI quarterly earnings releases, SEC Form 8-K (Item 2.02) Exhibit 99.1, via EDGAR's submissions API.
Fiscal year ends March 31: quarter ended Jun 30 = FQ1, Sep 30 = FQ2, Dec 31 = FQ3, Mar 31 = FQ4 (FY = calendar year of the
following March), labelled e.g. FQ2'27 as on the page. Each quarter is stored as first reported (current-quarter column):
  * Selected Financial Data: revenues by segment (Corporate Finance, Financial Restructuring, Financial and Valuation
    Advisory) and total revenues. Releases through FQ4'26 are in $ thousands, from FQ1'27 in whole $ millions.
  * Corporate Finance segment block: revenues, # of Managing Directors, # of closed transactions.
  * Adjusted (non-GAAP) compensation and non-compensation % of revenues (three-month expense table).
  * Reconciliation: operating income (adjusted), net income attributable (adjusted), fully diluted shares (adjusted),
    diluted EPS (adjusted).
A new quarter is accepted only if all tie-outs pass: segments sum to total revenues; CF block revenue equals the segment
table; adjusted op income = revenues - adjusted comp - adjusted non-comp; reported adjusted comp / non-comp % match the
dollar amounts; adjusted EPS = adjusted net income / adjusted diluted shares. Otherwise it warns and keeps old data.

Incremental and warn-only in the weekday refresh (most runs only read the EDGAR submissions index).
  python3 companies/nowcast/hli_quarterly.py           new releases only
  python3 companies/nowcast/hli_quarterly.py --check   re-parse every stored quarter and diff against hli_raw.json (no writes)
"""
import gzip, json, pathlib, re, sys, time, urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from evr_quarterly import to_text, nums, find  # shared release-text helpers

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "companies" / "raw" / "hli_raw.json"
CIK = 1302215
UA = {"User-Agent": "Eric Hines research-hub HLI quarterly KPIs hub@example.com", "Accept-Encoding": "gzip"}
PAUSE = 0.25
MON = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
    b = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        b = gzip.decompress(b)
    time.sleep(PAUSE)
    return b


def fq_label(end):
    y, m = int(end[:4]), int(end[5:7])
    fq, fy = {6: (1, y + 1), 9: (2, y + 1), 12: (3, y + 1), 3: (4, y)}[m]
    return f"FQ{fq}'{fy % 100:02d}"


def first(L, pred, start=0):
    return next((i for i in range(start, len(L)) if pred(L[i])), None)


def parse(L, filed, url, need_eps_tie=True):
    t = " ".join(L)
    m = re.search(r"quarter ended (\w+) (\d{1,2}), (\d{4})", t)
    if not m:
        raise ValueError("period not found")
    end = f"{m.group(3)}-{MON[m.group(1)]:02d}-{int(m.group(2)):02d}"
    g = first(L, lambda l: l.strip().startswith("Selected Financial Data"))
    u = first(L, lambda l: re.match(r"\(In (thousands|millions)", l.strip()), g or 0)
    if g is None or u is None:
        raise ValueError("selected financial data table not found")
    k = 1000.0 if "thousands" in L[u] else 1.0   # divisor to $M
    tol = 3 if k > 1 else 1                     # rounding tolerance in release units
    v = lambda x: None if x is None else x / k
    def find2(pat, start=0, idx=0):  # label anywhere in the line (some releases flatten several rows into one); numbers after it
        for i in range(start or 0, len(L)):
            m = re.search(pat, L[i])
            if m:
                n = nums(L[i][m.end():])
                if len(n) > idx:
                    return n[idx]
        return None
    def seg(name):  # segment block: "<Segment> |" header followed by "Revenues | ..."
        h = first(L, lambda l: l.strip() == name + " |", g)
        return (find(L, r"Revenues\s*\|", h), h) if h is not None else (None, None)
    (cf, b), (fr, _), (fva, _) = seg("Corporate Finance"), seg("Financial Restructuring"), seg("Financial and Valuation Advisory")
    tot = find(L, r"Revenues\s*\|", g)
    cf_tbl = find(L, r"Corporate Finance \|", g)   # segment line in Selected Financial Data (absent in some FQ4/FQ1 releases)
    md = find(L, r"# of Managing Directors", b) if b is not None else None
    txn = find(L, r"# of Closed transactions", b) if b is not None else None
    # three-month GAAP/adjusted expense table (FQ4 releases show the fiscal-year table first)
    a = next((i for i in range(g, len(L)) if "Adjusted (Non-GAAP)" in L[i] and any("Three Months Ended" in x for x in L[i + 1:i + 4])), None)
    ia = first(L, lambda l: l.strip().startswith("% of Revenues"), a) if a is not None else None
    comp_p = find(L, r"% of Revenues", ia, 2) if ia is not None else None
    nc_p = find(L, r"% of Revenues", ia + 1, 2) if ia is not None else None
    comp_d = find2(r"(Employee compensation and benefits expenses|Compensation expenses) \(adjusted\)")
    nc_d = find2(r"Non-compensation expenses \(adjusted\)"); oi = find2(r"Operating income \(adjusted\)")
    ni = find2(r"Net income attributable to Houlihan Lokey, Inc\. \(adjusted\)")
    if ni is None:  # releases before FQ4'26 label it "Net income (adjusted)"
        ni = find2(r"Net income \(adjusted\)")
    sh = find2(r"(Fully diluted shares outstanding|Weighted average shares[^|]*diluted[^|]*) \(adjusted\)")
    eps = find2(r"(Fully diluted|Diluted) EPS[^|]*\(adjusted\)")
    r = {"q": fq_label(end), "end": end, "filed": filed, "src": url,
         "total": v(tot), "cf_rev": v(cf), "fr": v(fr), "fva": v(fva), "cf_txn": int(txn) if txn is not None else None, "cf_md": int(md) if md is not None else None,
         "eps": eps, "comp_tbl": comp_p, "nc_tbl": nc_p, "opm_adj": round(oi / tot * 100, 1) if oi and tot else None}
    miss = [x for x in ("total", "cf_rev", "fr", "fva", "cf_txn", "cf_md", "eps", "comp_tbl", "nc_tbl") if r[x] is None]
    if miss:
        raise ValueError(f"missing {miss}")
    errs = []
    if abs(cf + fr + fva - tot) > tol: errs.append(f"segments {cf + fr + fva} != total {tot}")
    if cf_tbl is not None and cf_tbl != cf: errs.append(f"CF block revenue {cf} != segment table {cf_tbl}")
    if None in (comp_d, nc_d, oi): errs.append("adjusted comp / non-comp / op income not found")
    else:
        if abs(tot - comp_d - nc_d - oi) > tol: errs.append(f"adj op income {oi} != rev - comp - noncomp {tot - comp_d - nc_d}")
        pp = 0.1 if k > 1 else 0.3   # $M releases: % is computed on unrounded amounts
        if abs(comp_d / tot * 100 - comp_p) > pp: errs.append(f"adj comp % {comp_p} vs {comp_d / tot * 100:.2f}")
        if abs(nc_d / tot * 100 - nc_p) > pp: errs.append(f"adj non-comp % {nc_p} vs {nc_d / tot * 100:.2f}")
    if ni is None or sh is None:
        if need_eps_tie: errs.append("adjusted net income / shares not found (EPS check)")
    else:
        shm = sh / 1e6 if sh > 1e5 else sh; nim = ni / k
        if abs(nim / shm - eps) > 0.03: errs.append(f"adj EPS {eps} vs NI/shares {nim / shm:.3f}")
    if errs:
        raise ValueError("; ".join(errs))
    return r


def filings():
    d = json.loads(get(f"https://data.sec.gov/submissions/CIK{CIK:010d}.json"))["filings"]["recent"]
    return sorted((d["filingDate"][i], d["accessionNumber"][i].replace("-", "")) for i, f in enumerate(d["form"])
                  if f == "8-K" and "2.02" in d["items"][i])


def exhibit_url(acc):
    base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc}/"
    docs = [x["name"] for x in json.loads(get(base + "index.json"))["directory"]["item"]]
    ex = [d for d in docs if re.search(r"ex-?99", d.lower()) and d.endswith(".htm")]
    return base + ex[0] if ex else None


def main():
    data = json.loads(RAW.read_text())
    rows = data["quarters"]
    if "--check" in sys.argv:   # parser vs stored history, no writes
        bad = 0
        for r in rows:
            L = to_text(get(r["src"]).decode("utf-8", "ignore")); tag = ""
            try:
                p = parse(L, r["filed"], r["src"])
            except Exception as e:
                try:   # FY22-FY23 releases have no adjusted diluted share count; retry without that one tie-out
                    p = parse(L, r["filed"], r["src"], need_eps_tie=False); tag = " (no adj. share count in release; EPS tie-out n/a)"
                except Exception:
                    print(f"{r['q']}: parse failed: {e}"); bad += 1; continue
            diff = {x: (r[x], p[x]) for x in ("total", "cf_rev", "fr", "fva", "cf_txn", "cf_md", "eps", "comp_tbl", "nc_tbl")
                    if abs(float(r[x]) - float(p[x])) > 1e-9}
            diff.update({x: (r[x], p[x]) for x in ("q", "end") if r[x] != p[x]})
            print(f"{r['q']}: {'EXACT' if not diff else diff}{tag}  adj op margin {p['opm_adj']}%"); bad += bool(diff)
        sys.exit(1 if bad else 0)
    seen = {r["filed"] for r in rows}; last_end = max(r["end"] for r in rows); new = []
    for filed, acc in filings():
        if filed in seen or filed < rows[-1]["filed"]:
            continue
        url = exhibit_url(acc)
        if not url:
            print(f"::warning::HLI {filed}: no Exhibit 99.1 found"); continue
        try:
            r = parse(to_text(get(url).decode("utf-8", "ignore")), filed, url)
        except Exception as e:
            print(f"::warning::HLI {filed}: parse/tie-out failed ({e}); quarter skipped, previous data kept"); continue
        if r["end"] <= last_end:
            print(f"HLI {filed}: {r['q']} already stored; skipped"); continue
        new.append(r); last_end = r["end"]; print(f"HLI {r['q']} parsed from {url}")
    if not new:
        print("HLI: no new releases."); return
    data["quarters"] = rows + new
    RAW.write_text(json.dumps(data, indent=1))
    sys.path.insert(0, str(ROOT / "companies"))
    import build_companies
    build_companies.main()


if __name__ == "__main__":
    main()

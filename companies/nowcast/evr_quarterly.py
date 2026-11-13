"""Evercore (EVR) quarterly KPIs -> companies/raw/evr_raw.json, then rebuilds data/companies.json (+ data/company-EVR.xlsx).

Source: Evercore's quarterly earnings releases, SEC Form 8-K (Item 2.02) Exhibit 99.1, found via EDGAR's submissions API.
Each quarter is stored AS FIRST REPORTED in its own release (current-quarter column only):
  * U.S. GAAP net revenues by line (dollars in thousands): Advisory, Underwriting, Commissions & Related Revenue
    (Investment Banking & Equities), Asset Management & Administration Fees (Investment Management), Other Revenue, net.
  * Page A-2 reconciliation: Net Revenues GAAP / Adjusted, Operating Income - Adjusted, Net Income - Adjusted,
    Diluted Shares Outstanding (GAAP / Adjusted), Diluted EPS (GAAP / Adjusted), Operating Margin - Adjusted.
  * "Adjusted Expenses" table: adjusted compensation and non-compensation ratios.
  * Segment reconciliation: Investment Management segment Net Revenues, Non-GAAP Adjusted Basis.
  * Number of advisory & underwriting client fees (total, and >= $1M); Wealth Management AUM ($mm, period end).
  * Senior Managing Director headcount sentence ("employed X(1) ... total ... SMDs, of which Y(1) ... were
    Advisory / Investment Banking SMDs").
Validation per quarter (parse rejected otherwise): revenue lines sum to GAAP net revenues (+-$2K rounding),
GAAP table total == A-2 GAAP total, adjusted op income / adjusted revenue == reported adjusted margin (+-0.1pp).

Incremental and warn-only in the weekday refresh: most runs only hit the EDGAR submissions index. When a new release
is parsed, evr_raw.json is updated and companies/build_companies.py is re-run. --full re-parses every release.
"""
import gzip, html, json, pathlib, re, sys, time, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "companies" / "raw" / "evr_raw.json"
CIK = 1360901
UA = {"User-Agent": "Eric Hines research-hub EVR quarterly KPIs hub@example.com", "Accept-Encoding": "gzip"}
PAUSE = 0.25
FIRST_FILED = "2022-01-01"   # Q4 2021 onward (20 quarters through Q3 2026)
MON = {m: i + 1 for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"])}


def get(url):
    r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60)
    b = r.read()
    if r.headers.get("Content-Encoding") == "gzip":
        b = gzip.decompress(b)
    time.sleep(PAUSE)
    return b


def to_text(h):
    t = re.sub(r"(?is)<(script|style).*?</\1>", "", h)
    t = re.sub(r"(?i)</(tr|p|div|br)[^>]*>", "\n", t)
    t = re.sub(r"(?i)</t[dh]>", " | ", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = html.unescape(t).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"(\| *)+", "| ", t)
    t = re.sub(r"\n\s*\n+", "\n", t)
    out = []
    for l in t.split("\n"):  # re-join a label whose numbers wrapped to the next line (footnote markers)
        if out and l.startswith(" |") and re.search(r"\d", l) and not out[-1].strip().endswith("|"):
            out[-1] = out[-1].rstrip() + " " + l
        else:
            out.append(l)
    return out


def nums(line):
    v = []
    for p in (p.strip() for p in line.split("|")[1:]):
        if p in ("$", "%", "%)", "", "NM") or re.fullmatch(r"\(\d\w?\)", p):
            continue
        if p in ("—", "-", "–"):
            v.append(0.0); continue
        m = re.fullmatch(r"\(?\$?\s*([\d,]+\.?\d*)\)?", p)
        if m:
            x = float(m.group(1).replace(",", ""))
            v.append(-x if p.startswith("(") else x)
    return v


def find(L, pat, start=0, idx=0):
    for i in range(start or 0, len(L)):
        if re.match(pat, L[i].strip()):
            n = nums(L[i])
            if len(n) > idx:
                return n[idx]
    return None


def first_idx(L, pred):
    return next((i for i, l in enumerate(L) if pred(l)), None)


def parse(text_lines, filed, url):
    L = text_lines; t = " ".join(L)
    m = re.search(r"results for the (first|second|third|fourth quarter|full year)[^.]*?ended (\w+) (\d{1,2}), (\d{4})", t)
    if not m:
        raise ValueError("period not found")
    mo, yr = MON[m.group(2)], int(m.group(4))
    end = f"{yr}-{mo:02d}-{int(m.group(3)):02d}"
    r = {"q": f"Q{(mo - 1) // 3 + 1} {yr}", "end": end, "filed": filed, "src": url}
    g = first_idx(L, lambda l: "Selected Financial Data" in l and "GAAP" in l)
    r["adv"] = find(L, r"Advisory Fees( \||\(\d\))", g); r["uw"] = find(L, r"Underwriting Fees", g)
    r["comm"] = find(L, r"Commissions and Related (Revenue|Fees)", g); r["amf"] = find(L, r"Asset Management and Administration Fees", g)
    r["oth"] = find(L, r"Other Revenue, net", g); r["net"] = find(L, r"Net Revenues \|", g)
    r["adv_py"] = find(L, r"Advisory Fees( \||\(\d\))", g, 1)  # year-ago quarter, as shown in this release (feeds early trailing-4Q sums)
    for k, p in [("rev_gaap", r"Net Revenues - U\.S\. GAAP"), ("rev_adj", r"Net Revenues - Adjusted"), ("oi_adj", r"Operating Income - Adjusted"),
                 ("ni_adj", r"Net Income Attributable to Evercore Inc\. - Adjusted"), ("sh_gaap", r"Diluted Shares Outstanding - U\.S\. GAAP"),
                 ("sh_adj", r"Diluted Shares Outstanding - Adjusted"), ("eps_gaap", r"Diluted Earnings Per Share - U\.S\. GAAP"),
                 ("eps_adj", r"Diluted Earnings Per Share - Adjusted"), ("opm_adj", r"Operating Margin - Adjusted")]:
        r[k] = find(L, p)
    a = first_idx(L, lambda l: l.strip().startswith("Adjusted Expenses"))
    r["comp_adj"] = find(L, r"Compensation Ratio", a); r["nc_adj"] = find(L, r"Non-Compensation Ratio", a)
    s = first_idx(L, lambda l: "Investment Management Segment" in l)
    r["im_adj"] = find(L, r"Net Revenues \|", s, 2) if s is not None else None
    r["nfee"] = find(L, r"Total Number of Fees from Advisory"); r["nfee1m"] = find(L, r"Total Number of Fees of at Least")
    am = first_idx(L, lambda l: l.strip().startswith("Assets Under Management ($ mm)")); r["aum"] = None
    if am is not None:
        for j in range(am, am + 8):
            n = nums(L[j])
            if n and n[0] > 1000:
                r["aum"] = n[0]; break
    m = re.search(r"employed (\d+)\(1\) and (\d+)\(2\) total[^.]*?of which (\d+)\(1\) and (\d+)\(2\)[^.]*?were (Advisory|Investment Banking) Senior", t)
    r["smd_tot"], r["smd_ib"] = (int(m.group(1)), int(m.group(3))) if m else (None, None)
    r["smd_label"] = m.group(5) if m else None
    # validation
    need = ["adv", "uw", "comm", "amf", "oth", "net", "rev_gaap", "rev_adj", "oi_adj", "eps_gaap", "eps_adj", "opm_adj", "comp_adj", "nc_adj", "sh_adj"]
    miss = [k for k in need if r.get(k) is None]
    if miss:
        raise ValueError(f"missing {miss}")
    if abs(r["adv"] + r["uw"] + r["comm"] + r["amf"] + r["oth"] - r["net"]) > 2 or abs(r["net"] - r["rev_gaap"]) > 2:
        raise ValueError("revenue lines do not sum to net revenues")
    if abs(r["oi_adj"] / r["rev_adj"] * 100 - r["opm_adj"]) > 0.1:
        raise ValueError("adjusted margin check failed")
    return r


def filings():
    d = json.loads(get(f"https://data.sec.gov/submissions/CIK{CIK:010d}.json"))["filings"]["recent"]
    out = []
    for i, f in enumerate(d["form"]):
        if f == "8-K" and "2.02" in d["items"][i] and d["filingDate"][i] >= FIRST_FILED:
            out.append((d["filingDate"][i], d["accessionNumber"][i].replace("-", "")))
    return sorted(out)


def main():
    full = "--full" in sys.argv
    have = json.loads(RAW.read_text()) if RAW.exists() and not full else []
    seen = {r["filed"] for r in have}
    new = []
    for filed, acc in filings():
        if filed in seen:
            continue
        base = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc}/"
        docs = [x["name"] for x in json.loads(get(base + "index.json"))["directory"]["item"]]
        ex = [d for d in docs if "earningsrelease" in d.lower() and d.endswith(".htm")]
        if not ex:
            print(f"::warning::EVR {filed}: no earnings-release exhibit found in {base}"); continue
        url = base + ex[0]
        try:
            r = parse(to_text(get(url).decode("utf-8", "ignore")), filed, url)
        except Exception as e:
            print(f"::warning::EVR {filed}: parse/validation failed ({e}); quarter skipped, previous data kept"); continue
        new.append(r); print(f"EVR {r['q']} parsed from {url}")
    if not new and not full:
        print("EVR: no new releases."); return
    rows = {r["end"]: r for r in have}
    for r in new:
        rows[r["end"]] = r
    RAW.write_text(json.dumps([rows[k] for k in sorted(rows)], indent=1))
    sys.path.insert(0, str(ROOT / "companies"))
    import build_companies
    build_companies.main()


if __name__ == "__main__":
    main()

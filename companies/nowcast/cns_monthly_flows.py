"""CNS monthly preliminary AUM & net flows by investment vehicle -> data/cns_monthly_flows.json
(+ data/company-CNS-monthly-flows.xlsx).

Source: Cohen & Steers' monthly "Preliminary Assets Under Management and Net Flows" press releases
(cohenandsteers.com/news, the PDF attached to each release, or the PR Newswire copy). Every number
stored is as reported in the release table ($ millions). Nothing is plugged: a vehicle or column the
release does not show is stored as null. Arithmetic checks (row roll-forward, subtotals, month-to-month
chain) are recorded in "checks" but never used to overwrite reported values. The only derived field is
organic growth (net flows / beginning AUM, x12 annualized), flagged as derived.

Run: python3 companies/nowcast/cns_monthly_flows.py   (incremental; --full re-fetches every month)
Warn-only in the weekday refresh: on any fetch failure the previous JSON is kept.
"""
import calendar, datetime as dt, html, json, pathlib, re, shutil, subprocess, sys, tempfile, time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "cns_monthly_flows.json"
XLSX = ROOT / "data" / "company-CNS-monthly-flows.xlsx"
LEGACY = pathlib.Path(__file__).with_name("cns_monthly.json")   # nowcast cache: PR Newswire URLs by month
START = "2021-11"                                                 # ~5 years of history
UA = {"User-Agent": "Mozilla/5.0 (research-hub; CNS monthly AUM)"}
CS = "https://www.cohenandsteers.com/news/cohen-steers-announces-preliminary-assets-under-management-and-net-flows-for-{m}-{y}/"
PRN_LIST = "https://www.prnewswire.com/news/cohen-%26-steers%2C-inc./?page={p}&pagesize=100"
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}

# reported row label -> (key, display label). Pre-Oct-2026 "Open-end Funds" / "Total Institutional Accounts"
# are the same buckets CNS now calls "Total Wealth" / "Institutional" (9/30/2026 balances tie exactly).
LABELS = {
    "total aum": "total", "open-end funds": "wealth", "total wealth": "wealth",
    "mutual funds": "mutual_funds", "etfs": "etfs", "sicavs": "sicavs", "other wealth": "other_wealth",
    "total institutional accounts": "institutional", "institutional": "institutional",
    "advisory": "advisory", "subadvisory": "subadvisory", "japan subadvisory": "japan_sub",
    "subadvisory excluding japan": "sub_ex_japan", "closed-end funds": "cef",
}
VEHICLES = [  # order used by the page / CSV / Excel
    ("total", "Total AUM", None),
    ("wealth", "Wealth (Open-end Funds)", "Reported as 'Open-end Funds' through Sep 2026 and 'Total Wealth' from Oct 2026"),
    ("mutual_funds", "Wealth: Mutual Funds", "Reported from Oct 2026 only"),
    ("etfs", "Wealth: ETFs", "Reported from Oct 2026 only"),
    ("sicavs", "Wealth: SICAVs", "Reported from Oct 2026 only"),
    ("other_wealth", "Wealth: Other", "Reported from Oct 2026 only"),
    ("institutional", "Institutional (total)", "Reported as 'Total Institutional Accounts' through Sep 2026 and 'Institutional' from Oct 2026"),
    ("advisory", "Institutional: Advisory", "Reported through Sep 2026; not split out from Oct 2026"),
    ("subadvisory", "Institutional: Subadvisory", "Single line Apr 2025 - Sep 2026"),
    ("japan_sub", "Institutional: Japan Subadvisory", "Reported through Mar 2025"),
    ("sub_ex_japan", "Institutional: Subadvisory ex-Japan", "Reported through Mar 2025"),
    ("cef", "Closed-end Funds", None),
]
COLS = ["beg", "net", "mkt", "dist", "xfer", "end"]
NUM = r"(?:\(\s?\$?\s?[\d,]+\s?\)|\$?\s?[\d,]+|\$?\s?[-–—])"


def get(url, binary=False, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                b = r.read()
                return b if binary else b.decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def clean(t):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t)).replace("\xa0", " ").replace("\u2009", " ")
    return re.sub(r"\s+", " ", t)


def val(s):
    s = s.replace("$", "").replace(" ", "")
    if s in ("-", "–", "—"): return 0.0          # dash in the release = nil
    neg = s.startswith("(")
    x = float(s.strip("()").replace(",", ""))
    return -x if neg else x


def pdf_text(b):
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(b); f.flush()
            return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60).stdout
    try:
        import io, pypdf
        return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(b)).pages)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"no PDF text extractor (pdftotext/pypdf): {e}")


def parse(text, month):
    """Parse the 'Assets Under Management (unaudited)' table. Returns dict or None."""
    t = clean(text)
    i = t.lower().find("by investment vehicle")
    if i < 0: return None
    j = t.find("Total AUM", i)
    if j < 0: return None
    seg = t[i:j + 160]
    first = re.search(r"Institutional Accounts|Wealth Channel|Open-end Funds|Advisory", seg)
    header = seg[:first.start()] if first else seg[:220]
    dates = re.findall(r"\d{1,2}/\d{1,2}/\d{4}", header)
    ncol = 6 if "transfer" in header.lower() else 5
    cols = ["beg", "net", "mkt", "dist", "xfer", "end"] if ncol == 6 else ["beg", "net", "mkt", "dist", "end"]
    rows = {}
    body = seg[len(header):]
    for m in re.finditer(r"([A-Z][A-Za-z\- ]*?[A-Za-z])\s*:?\s+((?:" + NUM + r"\s*){" + str(ncol) + r"})(?=\s|$)", body):
        lbl = re.sub(r"^(Institutional Accounts|Wealth Channel)\s*:?\s*", "", m.group(1).strip())
        key = LABELS.get(lbl.lower())
        if not key: continue
        vals = re.findall(NUM, m.group(2))
        if len(vals) != ncol: continue
        r = dict(zip(cols, map(val, vals)))
        r.setdefault("xfer", None)
        r["label"] = lbl
        rows[key] = r
    if "total" not in rows: return None
    # period sanity: end-date column must be the month-end of `month`
    y, mo = map(int, month.split("-"))
    pe = f"{mo}/{calendar.monthrange(y, mo)[1]}/{y}"
    if dates and dates[-1] != pe:
        raise ValueError(f"{month}: table end date {dates[-1]} != {pe}")
    rd = None
    m = re.search(r"New York,? NY,? ([A-Z][a-z]+\.? \d{1,2}, \d{4})", t) or re.search(r"NEW YORK ?, ([A-Z][a-z]+\.? \d{1,2}, \d{4}) /PRNewswire/", t)
    if m:
        s_ = m.group(1).replace(".", "")
        for f in ("%B %d, %Y", "%b %d, %Y"):
            try: rd = dt.datetime.strptime(s_, f).date().isoformat(); break
            except ValueError: pass
    return {"rows": rows, "transfers_column": ncol == 6, "release_date": rd}


def prn_links():
    links = {}
    for p in range(1, 7):
        try: t = get(PRN_LIST.format(p=p)) or ""
        except Exception: break
        for l in re.findall(r'href="(/news-releases/[^"]*assets-under-management[^"]*)"', t):
            m = re.search(r"for-([a-z]+)-(\d{4})-", l)
            if m and m.group(1) in MONTHS: links[f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"] = "https://www.prnewswire.com" + l
    return links


def fetch_month(month, prn):
    y, mo = month.split("-")
    name = calendar.month_name[int(mo)].lower()
    errs = []
    url = CS.format(m=name, y=y)
    page = get(url)
    if page:
        p = parse(page, month)
        if p: return {**p, "url": url, "source": "cohenandsteers.com"}
        pdf = re.search(r'href="(https://[^"]*(?:Monthly[_-]AUM|monthly-aum)[^"]*\.pdf)"', page, re.I)
        if pdf:
            try:
                p = parse(pdf_text(get(pdf.group(1), binary=True)), month)
                if p: return {**p, "url": pdf.group(1), "page_url": url, "source": "cohenandsteers.com (PDF)"}
            except Exception as e:  # noqa: BLE001
                errs.append(f"pdf: {e}")
    for u in [x for x in [prn.get(month)] if x]:
        pg = get(u)
        p = parse(pg, month) if pg else None
        if p: return {**p, "url": u, "source": "PR Newswire"}
    if errs: print(f"  {month}: " + "; ".join(errs), file=sys.stderr)
    return None


def checks(rec, prev):
    R, out = rec["rows"], []
    def roll(k):
        r = R[k]; s = r["beg"] + r["net"] + r["mkt"] + r["dist"] + (r["xfer"] or 0)
        if abs(s - r["end"]) > 2: out.append(f"{k}: beg+net+mkt+dist{'+xfer' if r['xfer'] is not None else ''} = {s:,.0f} vs reported end {r['end']:,.0f}")
    for k in R: roll(k)
    def tie(tot, parts):
        if tot not in R or not all(p in R for p in parts): return
        for c in COLS:
            if R[tot][c] is None: continue
            s = sum(R[p][c] or 0 for p in parts)
            if abs(s - R[tot][c]) > 2: out.append(f"{tot}.{c}: components sum {s:,.0f} vs reported {R[tot][c]:,.0f} ({'+'.join(parts)})")
    tie("total", ["wealth", "institutional", "cef"])
    for parts in (["advisory", "subadvisory"], ["advisory", "japan_sub", "sub_ex_japan"]): tie("institutional", parts)
    tie("wealth", ["mutual_funds", "etfs", "sicavs", "other_wealth"])
    if prev:
        for k in R:
            if k in prev["rows"] and abs(prev["rows"][k]["end"] - R[k]["beg"]) > 2:
                out.append(f"{k}: beginning AUM {R[k]['beg']:,.0f} != prior month ending {prev['rows'][k]['end']:,.0f}")
    return out


def months_due(today):
    y, m = map(int, START.split("-")); out = []
    while (y, m) < (today.year, today.month):
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
    hdr1, hdr2 = ["Month", "Release date"], ["", ""]
    names = {"beg": "Beginning AUM", "net": "Net flows", "mkt": "Market app/(dep)", "dist": "Distributions", "xfer": "Transfers", "end": "Ending AUM", "og": "Organic growth % ann. (derived)"}
    for k, lab, _ in VEHICLES:
        for c in COLS + ["og"]: hdr1.append(lab); hdr2.append(names[c])
    hdr1.append("Source"); hdr2.append("")
    ws.append(hdr1); ws.append(hdr2)
    for c in ws[1] + ws[2]: c.font = Font(bold=True)
    for r in reversed(D["months"]):
        row = [r["month"], r.get("release_date")]
        for k, _, _ in VEHICLES:
            v = r["rows"].get(k)
            row += [v[c] if v else None for c in COLS] + [v.get("og_ann_pct") if v else None]
        row.append(r["url"]); ws.append(row)
    ws.freeze_panes = "C3"
    n = wb.create_sheet("Notes")
    for x in D["notes"] + [""] + [f"{m}: {c}" for m, cs in D["discrepancies"].items() for c in cs]: n.append([x])
    wb.save(XLSX)


def main(full=False):
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    have = {r["month"]: r for r in old.get("months", [])} if not full else {}
    due = months_due(dt.date.today())
    todo = [m for m in due if m not in have]
    prn = {}
    if LEGACY.exists():
        prn = {k: v["url"] for k, v in json.loads(LEGACY.read_text()).items() if "prnewswire" in v.get("url", "")}
    if any(m not in prn for m in todo):
        try: prn.update(prn_links())
        except Exception as e: print("PR Newswire listing failed:", e, file=sys.stderr)
    warnings = []
    for m in todo:
        try:
            rec = fetch_month(m, prn)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{m}: {e}"); continue
        if rec: have[m] = {"month": m, **rec}; print("  parsed", m, rec["source"])
        else: print("  not yet available:", m)
    months = [have[m] for m in sorted(have) if m >= START]
    disc, prev = {}, None
    for r in months:
        y, mo = map(int, r["month"].split("-"))
        r["period_end"] = f"{y}-{mo:02d}-{calendar.monthrange(y, mo)[1]:02d}"
        for k, v in r["rows"].items():
            v["og_ann_pct"] = round(v["net"] / v["beg"] * 12 * 100, 2) if v["beg"] else None
        c = checks(r, prev); r["checks"] = c
        if c: disc[r["month"]] = c
        prev = r
    gaps = [m for m in due if m not in have]
    first, last = (months[0]["month"], months[-1]["month"]) if months else (None, None)
    D = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "units": "$ millions",
        "coverage": {"from": first, "to": last, "n": len(months), "missing": gaps},
        "vehicles": [{"key": k, "label": l, "note": n} for k, l, n in VEHICLES],
        "columns": {"beg": "Beginning AUM", "net": "Net flows", "mkt": "Market appreciation/(depreciation)", "dist": "Distributions", "xfer": "Transfers", "end": "Ending AUM", "og_ann_pct": "Organic growth, annualized % (DERIVED: net flows / beginning AUM x 12)"},
        "notes": [
            "Source: Cohen & Steers monthly preliminary AUM and net flows releases (unaudited, preliminary; quarterly 8-K figures can differ slightly). $ millions, as reported.",
            "Disclosed every month, by investment vehicle: beginning AUM, net flows, market appreciation/(depreciation), distributions and ending AUM. A 'Transfers' column (moves between vehicles, nets to zero in total) appears only in months where transfers occurred; other months it is blank (not disclosed, not zero).",
            "Vehicle detail changed over time: Advisory / Japan Subadvisory / Subadvisory ex-Japan through Mar 2025; Advisory / Subadvisory Apr 2025 - Sep 2026; from Oct 2026 Institutional is one line and Wealth is split into Mutual Funds, ETFs, SICAVs and Other Wealth. Open-end Funds (through Sep 2026) = Total Wealth (from Oct 2026); Total Institutional Accounts = Institutional. Unreported splits are left blank, never estimated.",
            "Not disclosed monthly: flows by strategy (real estate, preferreds, infrastructure...), gross sales vs redemptions, fee rates or revenue. Closed-end fund net flows reflect offerings/ATM issuance and are often nil.",
            "Organic growth % (annualized) is DERIVED here: net flows / beginning AUM x 12. Everything else is reported.",
        ],
        "discrepancies": disc,
        "warnings": warnings,
        "months": months,
    }
    OUT.write_text(json.dumps(D, indent=1))
    write_xlsx(D)
    print(f"{len(months)} months {first} -> {last}; missing {gaps}; discrepancies {list(disc)}; warnings {warnings}")
    return D


if __name__ == "__main__":
    main(full="--full" in sys.argv)

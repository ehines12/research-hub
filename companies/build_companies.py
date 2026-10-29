#!/usr/bin/env python3
"""Build data/companies.json (+ per-ticker xlsx) from figures extracted from SEC 8-K Ex. 99.1 earnings releases.
Raw extracts live in companies/raw/. To add a ticker: add a builder function returning the same dict shape and list it in COMPANIES."""
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "companies/raw"

def k2m(s):  # HLI tables: $K through FQ4'26, whole $M from FQ1'27
    v = float(s.replace(",", "")); return v / 1000 if v > 5000 else v

def hli():
    x = json.loads((RAW / "hli_extra.json").read_text()); urls = dict(json.loads((RAW / "hli_urls.json").read_text()))
    Q = [("FQ3'22","2021-12-31",715.663,238,198),("FQ4'22","2022-03-31",279.019,144,202),("FQ1'23","2022-06-30",263.951,124,217),("FQ2'23","2022-09-30",315.016,114,210),("FQ3'23","2022-12-31",291.734,125,215),("FQ4'23","2023-03-31",256.425,140,217),("FQ1'24","2023-06-30",227.051,95,225),("FQ2'24","2023-09-30",281.684,117,211),("FQ3'24","2023-12-31",310.512,117,219),("FQ4'24","2024-03-31",287.579,121,223),("FQ1'25","2024-06-30",328.417,116,228),("FQ2'25","2024-09-30",364.028,131,224),("FQ3'25","2024-12-31",421.602,170,238),("FQ4'25","2025-03-31",412.709,147,240),("FQ1'26","2025-06-30",398.519,125,244),("FQ2'26","2025-09-30",438.661,171,242),("FQ3'26","2025-12-31",473.688,177,238),("FQ4'26","2026-03-31",433.766,171,251),("FQ1'27","2026-06-30",303,127,260),("FQ2'27","2026-09-30",481,142,267)]
    PR = [(306.171,121),(300.662,151),(209.991,84),(388.41,134)]  # FQ3'21-FQ2'22 from prior-year columns
    AR = [p[0] for p in PR] + [q[2] for q in Q]; AN = [p[1] for p in PR] + [q[3] for q in Q]
    filed = sorted(x)
    rows = []
    for i, (q, end, rev, n, md) in enumerate(Q):
        e = x[filed[i]]; k = i + 4
        rows.append({"q": q, "end": end, "src": urls[filed[i]], "filed": filed[i],
            "total_rev": round(k2m(e["total"]), 3), "cf_rev": rev, "fr_rev": round(k2m(e["fr"]), 3), "fva_rev": round(k2m(e["fva"]), 3),
            "cf_txn": n, "cf_avg": round(rev / n, 3), "cf_md": md,
            "rev_md_q": round(rev / md, 3), "rev_md_ltm": round(sum(AR[k-3:k+1]) / md, 3),
            "txn_md_q": round(n / md, 3), "txn_md_ltm": round(sum(AN[k-3:k+1]) / md, 3),
            "adj_eps": float(e["eps"]), "adj_comp": float(e["comp_tbl"]), "adj_noncomp": float(e["nc_tbl"])})
    return {"ticker": "HLI", "name": "Houlihan Lokey", "fiscal": "Fiscal year ends March 31 (FQ2'27 = quarter ended Sep 30, 2026).",
        "fields": [
            {"key": "total_rev", "label": "Total revenue", "fmt": "m1"}, {"key": "cf_rev", "label": "CF revenue", "fmt": "m1"},
            {"key": "fr_rev", "label": "FR revenue", "fmt": "m1"}, {"key": "fva_rev", "label": "FVA revenue", "fmt": "m1"},
            {"key": "cf_txn", "label": "CF closed txns", "fmt": "n0"}, {"key": "cf_avg", "label": "CF avg rev / txn*", "fmt": "m2"},
            {"key": "cf_md", "label": "CF MDs", "fmt": "n0"}, {"key": "rev_md_q", "label": "CF rev / MD (qtr)*", "fmt": "m2"},
            {"key": "rev_md_ltm", "label": "CF rev / MD (LTM)*", "fmt": "m2"}, {"key": "txn_md_q", "label": "Txns / MD (qtr)*", "fmt": "x2"},
            {"key": "txn_md_ltm", "label": "Txns / MD (LTM)*", "fmt": "x2"}, {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"},
            {"key": "adj_comp", "label": "Adj. comp ratio", "fmt": "pct1", "invert": True}, {"key": "adj_noncomp", "label": "Adj. non-comp ratio", "fmt": "pct1", "invert": True}],
        "kpis": ["total_rev", "cf_rev", "cf_txn", "cf_avg", "cf_md", "rev_md_ltm", "adj_eps", "adj_noncomp"],
        "charts": [
            {"title": "Revenue by segment ($M)", "type": "bar", "stacked": True, "series": ["cf_rev", "fr_rev", "fva_rev"]},
            {"title": "CF revenue ($M) vs closed transactions", "type": "bar", "series": ["cf_rev", "cf_txn"], "y2": ["cf_txn"], "types": ["bar", "line"]},
            {"title": "CF avg revenue per closed transaction ($M)", "type": "line", "series": ["cf_avg"]},
            {"title": "CF productivity per MD (LTM)", "type": "line", "series": ["rev_md_ltm", "txn_md_ltm"], "y2": ["txn_md_ltm"]},
            {"title": "Adj. EPS", "type": "bar", "series": ["adj_eps"]},
            {"title": "Adj. comp and non-comp ratios (%)", "type": "line", "series": ["adj_comp", "adj_noncomp"]}],
        "rows": rows,
        "notes": ["Source: Houlihan Lokey quarterly earnings releases (SEC Form 8-K, Exhibit 99.1); one link per quarter.",
            "* Computed: avg rev/txn = CF revenue / closed transactions; per-MD = revenue or transactions / period-end CF MDs; LTM = trailing four quarters.",
            "Releases from FQ1'27 report in whole $M (rounded); earlier ones in $K.",
            "Adj. comp and non-comp ratios are the adjusted (non-GAAP) % of revenues in each release's expense table.",
            "FQ3'22 includes GCA, acquired during that quarter. LTM for FQ3'22-FQ1'23 uses FQ3'21-FQ2'22 from prior-year columns."]}

# Fee rate ex performance fees (GAAP), as reported in the Jul and Oct 2026 releases' 5-quarter highlight tables
FEE_REP = {"2025-06-30": 59.1, "2025-09-30": 59.1, "2025-12-31": 58.7, "2026-03-31": 59.0, "2026-06-30": 58.5, "2026-09-30": 58.3}

def cns():
    raw = json.loads((RAW / "cns_raw.json").read_text())
    ends = ["2021-12-31","2022-03-31","2022-06-30","2022-09-30","2022-12-31","2023-03-31","2023-06-30","2023-09-30","2023-12-31","2024-03-31","2024-06-30","2024-09-30","2024-12-31","2025-03-31","2025-06-30","2025-09-30","2025-12-31","2026-03-31","2026-06-30","2026-09-30"]
    rows = []
    for r, end in zip(raw, ends):
        y, m = int(end[:4]), int(end[5:7]); T = r["tot"]
        og = lambda b: round(b["net"] * 4 / b["beg"] * 100, 1)
        rows.append({"q": f"Q{(m-1)//3+1} {y}", "end": end, "src": r["url"], "filed": r["filed"],
            "aum_end": round(T["end"] / 1000, 2), "aum_avg": round(T["avg"] / 1000, 2),
            "aum_oe": round(r["oe"]["end"] / 1000, 2), "aum_inst": round(r["inst"]["end"] / 1000, 2), "aum_cef": round(r["cef"]["end"] / 1000, 2),
            "flow_tot": round(T["net"] / 1000, 2), "flow_oe": round(r["oe"]["net"] / 1000, 2), "flow_inst": round(r["inst"]["net"] / 1000, 2), "flow_cef": round(r["cef"]["net"] / 1000, 2),
            "og": og(T), "rev": round(r["rev"], 1), "rev_adj": round(r["rev_adj"], 1),
            "fee_calc": round(r["rev_adj"] * 4 / (T["avg"] / 1000) * 10, 1),  # bps: $M*4 / $bn avg AUM -> bps
            "fee_rep": FEE_REP.get(end), "opm_adj": r["opm"], "adj_eps": r["eps"]})
    return {"ticker": "CNS", "name": "Cohen & Steers", "fiscal": "Calendar fiscal year.",
        "fields": [
            {"key": "aum_end", "label": "Ending AUM", "fmt": "bn1"}, {"key": "aum_avg", "label": "Average AUM", "fmt": "bn1"},
            {"key": "aum_oe", "label": "Open-end / Wealth AUM", "fmt": "bn1"}, {"key": "aum_inst", "label": "Institutional AUM", "fmt": "bn1"},
            {"key": "aum_cef", "label": "Closed-end AUM", "fmt": "bn1"}, {"key": "flow_tot", "label": "Net flows", "fmt": "bnf"},
            {"key": "flow_oe", "label": "Net flows: open-end / Wealth", "fmt": "bnf"}, {"key": "flow_inst", "label": "Net flows: institutional", "fmt": "bnf"},
            {"key": "flow_cef", "label": "Net flows: closed-end", "fmt": "bnf"}, {"key": "og", "label": "Organic growth (ann.)*", "fmt": "pct1"},
            {"key": "rev", "label": "Revenue (GAAP)", "fmt": "m1"}, {"key": "rev_adj", "label": "Revenue (adj.)", "fmt": "m1"},
            {"key": "fee_calc", "label": "Effective fee rate*", "fmt": "bps"}, {"key": "fee_rep", "label": "Reported fee rate ex perf.", "fmt": "bps"},
            {"key": "opm_adj", "label": "Op. margin (as adj.)", "fmt": "pct1"}, {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"}],
        "kpis": ["aum_end", "aum_avg", "flow_tot", "og", "rev", "fee_calc", "opm_adj", "adj_eps"],
        "charts": [
            {"title": "AUM by vehicle ($bn)", "type": "bar", "stacked": True, "series": ["aum_oe", "aum_inst", "aum_cef"]},
            {"title": "Net flows by vehicle ($bn)", "type": "bar", "stacked": True, "series": ["flow_oe", "flow_inst", "flow_cef"]},
            {"title": "Organic growth, annualized (%)", "type": "bar", "series": ["og"], "zero": True},
            {"title": "Effective fee rate (bps) and adj. operating margin (%)", "type": "line", "series": ["fee_calc", "opm_adj"], "y2": ["opm_adj"]},
            {"title": "Adj. EPS", "type": "bar", "series": ["adj_eps"]},
            {"title": "Revenue (adj., $M)", "type": "bar", "series": ["rev_adj"]}],
        "rows": rows,
        "notes": ["Source: Cohen & Steers quarterly earnings releases (SEC Form 8-K, Exhibit 99.2) incl. AUM-by-vehicle supplemental tables; one link per quarter. Each quarter is as first reported.",
            "Vehicle names: 'Open-end Funds' through Q2 2026; from Q3 2026 CNS reports 'Wealth' (mutual funds, ETFs, SICAVs, other wealth vehicles). Wealth AUM at Jun 30, 2026 equals the prior Open-end total, so the series is continuous.",
            "* Computed: organic growth = net flows x 4 / beginning AUM; effective fee rate = adjusted revenue x 4 / average AUM (includes performance fees).",
            "Reported fee rate (ex performance fees) is first disclosed in the Q2 2026 release (with history back to Q2 2025); earlier quarters n/a."]}

COMPANIES = [hli, cns]

def xlsx(c):
    wb = Workbook(); ws = wb.active; ws.title = "Data"
    F = c["fields"]; ws.append(["Quarter", "Period end"] + [f["label"] for f in F] + ["Source"])
    for x in ws[1]: x.font = Font(bold=True)
    for r in c["rows"]:
        ws.append([r["q"], r["end"]] + [r.get(f["key"]) if r.get(f["key"]) is not None else "n/a" for f in F] + [r["src"]])
    ws.freeze_panes = "C2"
    n = wb.create_sheet("Notes"); [n.append([t]) for t in c["notes"]]
    wb.save(ROOT / "data" / f"company-{c['ticker']}.xlsx")

def main():
    cs = [f() for f in COMPANIES]
    for c in cs: xlsx(c)
    (ROOT / "data/companies.json").write_text(json.dumps({"companies": cs}, indent=1))
    print("wrote data/companies.json:", [(c["ticker"], len(c["rows"])) for c in cs])

if __name__ == "__main__":
    main()

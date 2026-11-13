#!/usr/bin/env python3
"""Build data/companies.json (+ per-ticker xlsx) from figures extracted from SEC 8-K Ex. 99.1 earnings releases.
Raw extracts live in companies/raw/. To add a ticker: add a builder function returning the same dict shape and list it in COMPANIES."""
import json
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "companies/raw"

def hli():
    raw = json.loads((RAW / "hli_raw.json").read_text())  # inputs in $M; new quarters appended by companies/nowcast/hli_quarterly.py
    Q, PR = raw["quarters"], raw["prior"]
    AR = [p["cf_rev"] for p in PR] + [q["cf_rev"] for q in Q]; AN = [p["cf_txn"] for p in PR] + [q["cf_txn"] for q in Q]
    rows = []
    for i, e in enumerate(Q):
        rev, n, md, k = e["cf_rev"], e["cf_txn"], e["cf_md"], i + len(PR)
        rows.append({"q": e["q"], "end": e["end"], "src": e["src"], "filed": e["filed"],
            "total_rev": round(e["total"], 3), "cf_rev": rev, "fr_rev": round(e["fr"], 3), "fva_rev": round(e["fva"], 3),
            "cf_txn": n, "cf_avg": round(rev / n, 3), "cf_md": md,
            "rev_md_q": round(rev / md, 3), "rev_md_ltm": round(sum(AR[k-3:k+1]) / md, 3),
            "txn_md_q": round(n / md, 3), "txn_md_ltm": round(sum(AN[k-3:k+1]) / md, 3),
            "adj_eps": e["eps"], "adj_comp": e["comp_tbl"], "adj_noncomp": e["nc_tbl"]})
    rows = rows[-20:]  # page shows the latest 20 quarters
    return {"ticker": "HLI", "name": "Houlihan Lokey", "fiscal": "Fiscal year ends March 31 (FQ2'27 = quarter ended Sep 30, 2026).",
        "fields": [
            {"key": "total_rev", "label": "Total revenue", "fmt": "m1"}, {"key": "cf_rev", "label": "CF revenue", "fmt": "m1"},
            {"key": "fr_rev", "label": "FR revenue", "fmt": "m1"}, {"key": "fva_rev", "label": "FVA revenue", "fmt": "m1"},
            {"key": "cf_txn", "label": "CF closed txns", "fmt": "n0"}, {"key": "cf_avg", "label": "CF avg rev / txn*", "fmt": "m2"},
            {"key": "cf_md", "label": "CF MDs", "fmt": "n0"}, {"key": "rev_md_q", "label": "CF rev / MD (qtr)*", "fmt": "m2"},
            {"key": "rev_md_ltm", "label": "CF rev / MD (LTM)*", "fmt": "m2"}, {"key": "txn_md_q", "label": "Txns / MD (qtr)*", "fmt": "x2"},
            {"key": "txn_md_ltm", "label": "Txns / MD (LTM)*", "fmt": "x2"}, {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"},
            {"key": "adj_comp", "label": "Adj. comp ratio", "fmt": "pct1", "invert": True}, {"key": "adj_noncomp", "label": "Adj. non-comp ratio", "fmt": "pct1", "invert": True}],
        "tiles": ["total_rev", "cf_rev", "cf_avg"],
        "kpis": ["total_rev", "cf_rev", "cf_txn", "cf_avg", "cf_md", "rev_md_ltm", "adj_eps", "adj_noncomp"],
        "charts": [
            {"title": "Revenue by segment ($M)", "type": "bar", "stacked": True, "series": ["cf_rev", "fr_rev", "fva_rev"]},
            {"title": "CF revenue ($M) vs closed transactions", "type": "bar", "series": ["cf_rev", "cf_txn"], "y2": ["cf_txn"], "types": ["bar", "line"]},
            {"title": "CF avg revenue per closed transaction ($M)", "type": "line", "series": ["cf_avg"]},
            {"title": "CF productivity per MD (LTM)", "type": "line", "series": ["rev_md_ltm", "txn_md_ltm"], "y2": ["txn_md_ltm"]},
            {"title": "Adj. EPS", "type": "bar", "series": ["adj_eps"]},
            {"title": "Adj. comp and non-comp ratios (%)", "type": "line", "series": ["adj_comp", "adj_noncomp"]}],
        "rows": rows,
        "notes": ["Source: Houlihan Lokey quarterly earnings releases (SEC Form 8-K, Exhibit 99.1); one link per quarter. Refreshed automatically: the weekday workflow checks EDGAR for a new Item 2.02 8-K and adds the quarter only if it ties out (segments sum to total revenues; adjusted op income = revenues - adjusted comp - adjusted non-comp; reported adjusted % match the dollar amounts; adjusted EPS = adjusted net income / adjusted diluted shares).",
            "* Computed: avg rev/txn = CF revenue / closed transactions; per-MD = revenue or transactions / period-end CF MDs; LTM = trailing four quarters.",
            "Releases from FQ1'27 report in whole $M (rounded); earlier ones in $K.",
            "Adj. comp and non-comp ratios are the adjusted (non-GAAP) % of revenues in each release's expense table.",
            "FQ3'22 includes GCA, acquired during that quarter. LTM for FQ3'22-FQ1'23 uses FQ3'21-FQ2'22 from prior-year columns."]}

# Fee rate ex performance fees (GAAP), as reported in the Jul and Oct 2026 releases' 5-quarter highlight tables
FEE_REP = {"2025-06-30": 59.1, "2025-09-30": 59.1, "2025-12-31": 58.7, "2026-03-31": 59.0, "2026-06-30": 58.5, "2026-09-30": 58.3}

PIPE = json.loads((RAW / "cns_pipeline.json").read_text())

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
            "fee_rep": FEE_REP.get(end), "pipe": PIPE[end]["bn"], "opm_adj": r["opm"], "adj_eps": r["eps"]})
    return {"ticker": "CNS", "name": "Cohen & Steers", "fiscal": "Calendar fiscal year.",
        "fields": [
            {"key": "aum_end", "label": "Ending AUM", "fmt": "bn1"}, {"key": "aum_avg", "label": "Average AUM", "fmt": "bn1"},
            {"key": "aum_oe", "label": "Open-end / Wealth AUM", "fmt": "bn1"}, {"key": "aum_inst", "label": "Institutional AUM", "fmt": "bn1"},
            {"key": "aum_cef", "label": "Closed-end AUM", "fmt": "bn1"}, {"key": "flow_tot", "label": "Net flows", "fmt": "bnf"},
            {"key": "flow_oe", "label": "Net flows: open-end / Wealth", "fmt": "bnf"}, {"key": "flow_inst", "label": "Net flows: institutional", "fmt": "bnf"},
            {"key": "flow_cef", "label": "Net flows: closed-end", "fmt": "bnf"}, {"key": "pipe", "label": "Won-but-unfunded pipeline", "fmt": "bn2"}, {"key": "og", "label": "Organic growth (ann.)*", "fmt": "pct1"},
            {"key": "rev", "label": "Revenue (GAAP)", "fmt": "m1"}, {"key": "rev_adj", "label": "Revenue (adj.)", "fmt": "m1"},
            {"key": "fee_calc", "label": "Effective fee rate*", "fmt": "bps"}, {"key": "fee_rep", "label": "Reported fee rate ex perf.", "fmt": "bps"},
            {"key": "opm_adj", "label": "Op. margin (as adj.)", "fmt": "pct1"}, {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"}],
        "tiles": ["aum_end", "flow_tot", "og"],
        "kpis": ["aum_end", "aum_avg", "flow_tot", "og", "pipe", "rev", "fee_calc", "opm_adj", "adj_eps"],
        "charts": [
            {"title": "AUM by vehicle ($bn)", "type": "bar", "stacked": True, "series": ["aum_oe", "aum_inst", "aum_cef"]},
            {"title": "Net flows by vehicle ($bn)", "type": "bar", "stacked": True, "series": ["flow_oe", "flow_inst", "flow_cef"]},
            {"title": "Institutional won-but-unfunded pipeline vs institutional net flows ($bn)", "type": "bar", "series": ["pipe", "flow_inst"], "zero": True},
            {"title": "Organic growth, annualized (%)", "type": "bar", "series": ["og"], "zero": True},
            {"title": "Effective fee rate (bps) and adj. operating margin (%)", "type": "line", "series": ["fee_calc", "opm_adj"], "y2": ["opm_adj"]},
            {"title": "Adj. EPS", "type": "bar", "series": ["adj_eps"]},
            {"title": "Revenue (adj., $M)", "type": "bar", "series": ["rev_adj"]}],
        "rows": rows,
        "notes": ["Source: Cohen & Steers quarterly earnings releases (SEC Form 8-K, Exhibit 99.2) incl. AUM-by-vehicle supplemental tables; one link per quarter. Each quarter is as first reported.",
            "Vehicle names: 'Open-end Funds' through Q2 2026; from Q3 2026 CNS reports 'Wealth' (mutual funds, ETFs, SICAVs, other wealth vehicles). Wealth AUM at Jun 30, 2026 equals the prior Open-end total, so the series is continuous.",
            "* Computed: organic growth = net flows x 4 / beginning AUM; effective fee rate = adjusted revenue x 4 / average AUM (includes performance fees).",
            "Won-but-unfunded pipeline: institutional mandates awarded but not yet funded, $bn at quarter end. Not in the 8-K exhibits (checked all 20 filings); taken from the CEO's prepared remarks on each earnings call (transcript links in companies/raw/cns_pipeline.json). Values are as stated on the call, often rounded (e.g. $1.1bn). Q1 2023, Q1 2024 and Q3 2024 come from the following quarter's call ('compared with $X last quarter').",
            "Reported fee rate (ex performance fees) is first disclosed in the Q2 2026 release (with history back to Q2 2025); earlier quarters n/a."]}

def wt():
    raw = json.loads((RAW / "wt_raw.json").read_text())
    rows = []
    for r in raw:
        # bps: adj revenue ($M) x 4 / avg AUM ($bn) x 10
        fee_calc = round(r["rev_adj"] * 4 / r["aum_avg"] * 10, 1)
        rows.append({
            "q": r["q"], "end": r["end"], "src": r["src"], "filed": r["filed"],
            "aum_end": r["aum_end"], "aum_avg": r["aum_avg"], "flow": r["flow"],
            "og": round(r["flow"] * 4 / (r["aum_end"] - r["flow"]) * 100, 1) if (r["aum_end"] - r["flow"]) else None,
            "fee_adv": r["fee_adv_bps"], "rev_yield_rep": r.get("rev_yield_rep"),
            "rev": r["rev"], "rev_adj": r["rev_adj"], "fee_calc": fee_calc,
            "opm_adj": r["opm_adj"], "adj_eps": r["adj_eps"],
        })
    return {"ticker": "WT", "name": "WisdomTree", "fiscal": "Calendar fiscal year.",
        "fields": [
            {"key": "aum_end", "label": "Ending AUM", "fmt": "bn1"},
            {"key": "aum_avg", "label": "Average AUM", "fmt": "bn1"},
            {"key": "flow", "label": "Net flows", "fmt": "bnf"},
            {"key": "og", "label": "Organic growth (ann.)*", "fmt": "pct1"},
            {"key": "fee_adv", "label": "Avg advisory fee", "fmt": "bps"},
            {"key": "rev_yield_rep", "label": "Reported revenue yield", "fmt": "bps"},
            {"key": "rev", "label": "Revenue (GAAP)", "fmt": "m1"},
            {"key": "rev_adj", "label": "Revenue (adj.)", "fmt": "m1"},
            {"key": "fee_calc", "label": "Effective revenue yield*", "fmt": "bps"},
            {"key": "opm_adj", "label": "Op. margin (as adj.)", "fmt": "pct1"},
            {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"}],
        "tiles": ["aum_end", "flow", "adj_eps"],
        "kpis": ["aum_end", "aum_avg", "flow", "og", "fee_adv", "rev_adj", "fee_calc", "opm_adj", "adj_eps"],
        "charts": [
            {"title": "Ending AUM ($bn)", "type": "line", "series": ["aum_end"]},
            {"title": "Net flows ($bn)", "type": "bar", "series": ["flow"], "zero": True},
            {"title": "Organic growth, annualized (%)", "type": "bar", "series": ["og"], "zero": True},
            {"title": "Advisory fee and effective revenue yield (bps)", "type": "line", "series": ["fee_adv", "fee_calc"]},
            {"title": "Adj. operating margin (%)", "type": "line", "series": ["opm_adj"]},
            {"title": "Adj. EPS", "type": "bar", "series": ["adj_eps"]},
            {"title": "Revenue (adj., $M)", "type": "bar", "series": ["rev_adj"]}],
        "rows": rows,
        "notes": [
            "Source: WisdomTree quarterly earnings releases (IR press releases / SEC Form 8-K Exhibit 99.1). Figures as first reported in each release's consolidated operating and financial highlights.",
            "Ending AUM is company-reported total AUM (includes private assets managed by Ceres Partners once acquired in Q4 2025). The IR daily/weekly AUM spreadsheet on wisdomtree.com excludes those private assets; the earnings-power panel reconciles the two.",
            "* Computed: organic growth = net flows x 4 / beginning AUM (ending − flows); effective revenue yield = adjusted operating revenue x 4 / average AUM (bps). Reported revenue yield is WisdomTree's disclosed adjusted revenue yield when available (first regularly shown from 2024).",
            "Adj. operating margin and adj. diluted EPS are the non-GAAP figures from each release. Revenue (adj.) equals GAAP operating revenues except where the release disclosed a separate adjusted revenue (e.g. Q3–Q4 2024 ESG-settlement other-revenue items)."]}

def evr():
    raw = json.loads((RAW / "evr_raw.json").read_text())  # written by companies/nowcast/evr_quarterly.py
    m = lambda v: None if v is None else round(v / 1000, 3)  # $K -> $M
    adv = [r["adv"] / 1000 for r in raw]
    rows = []
    for i, r in enumerate(raw):
        # trailing four quarters of advisory fees; before the 4th row, earlier quarters come from the year-ago column
        # of the releases 4 quarters later (raw[i+4-k]["adv_py"])
        t4 = [adv[j] if j >= 0 else raw[j + 4]["adv_py"] / 1000 for j in range(i - 3, i + 1)]
        ib = r["smd_ib"]; fee_n = r["nfee"]
        rows.append({"q": r["q"], "end": r["end"], "src": r["src"], "filed": r["filed"],
            "net_rev": m(r["net"]), "adj_rev": m(r["rev_adj"]),
            "adv": m(r["adv"]), "uw": m(r["uw"]), "comm": m(r["comm"]), "amf": m(r["amf"]), "oth": m(r["oth"]), "im_adj": m(r["im_adj"]),
            "nfee": fee_n, "nfee1m": r["nfee1m"],
            "avg_fee": round((r["adv"] + r["uw"]) / 1000 / fee_n, 3) if fee_n else None,
            "smd_ib": ib, "smd_tot": r["smd_tot"],
            "adv_smd_q": round(adv[i] / ib, 3) if ib else None, "adv_smd_ltm": round(sum(t4) / ib, 3) if ib else None,
            "adj_comp": r["comp_adj"], "adj_noncomp": r["nc_adj"], "opm_adj": r["opm_adj"],
            "adj_eps": r["eps_adj"], "gaap_eps": r["eps_gaap"], "sh_adj": round(r["sh_adj"] / 1000, 2),
            "aum": round(r["aum"] / 1000, 2) if r.get("aum") else None})
    rows = rows[-20:]  # page shows the latest 20 quarters
    return {"ticker": "EVR", "name": "Evercore", "fiscal": "Calendar fiscal year.",
        "fields": [
            {"key": "net_rev", "label": "Net revenues (GAAP)", "fmt": "m1"}, {"key": "adj_rev", "label": "Net revenues (adj.)", "fmt": "m1"},
            {"key": "adv", "label": "Advisory fees", "fmt": "m1"}, {"key": "uw", "label": "Underwriting fees", "fmt": "m1"},
            {"key": "comm", "label": "Commissions & related", "fmt": "m1"}, {"key": "amf", "label": "Asset mgmt & admin fees (IM)", "fmt": "m1"},
            {"key": "oth", "label": "Other revenue, net", "fmt": "m1"}, {"key": "im_adj", "label": "IM segment net rev. (adj.)", "fmt": "m1"},
            {"key": "nfee", "label": "Client fees (adv. + UW)", "fmt": "n0"}, {"key": "nfee1m", "label": "Client fees >= $1M", "fmt": "n0"},
            {"key": "avg_fee", "label": "Avg fee per client fee*", "fmt": "m2"},
            {"key": "smd_ib", "label": "IB SMDs", "fmt": "n0"}, {"key": "smd_tot", "label": "IB&E SMDs (total)", "fmt": "n0"},
            {"key": "adv_smd_q", "label": "Advisory / IB SMD (qtr)*", "fmt": "m2"}, {"key": "adv_smd_ltm", "label": "Advisory / IB SMD (LTM)*", "fmt": "m2"},
            {"key": "adj_comp", "label": "Adj. comp ratio", "fmt": "pct1", "invert": True}, {"key": "adj_noncomp", "label": "Adj. non-comp ratio", "fmt": "pct1", "invert": True},
            {"key": "opm_adj", "label": "Adj. operating margin", "fmt": "pct1"},
            {"key": "adj_eps", "label": "Adj. diluted EPS", "fmt": "usd2"}, {"key": "gaap_eps", "label": "GAAP diluted EPS", "fmt": "usd2"},
            {"key": "sh_adj", "label": "Adj. diluted shares (M)", "fmt": "x2", "invert": True},
            {"key": "aum", "label": "Wealth Mgmt AUM", "fmt": "bn2"}],
        "tiles": ["adj_rev", "adv", "adv_smd_ltm"],
        "kpis": ["adj_rev", "adv", "nfee", "avg_fee", "smd_ib", "adv_smd_ltm", "adj_comp", "opm_adj", "adj_eps"],
        "charts": [
            {"title": "Net revenues by line ($M, GAAP)", "type": "bar", "stacked": True, "series": ["adv", "uw", "comm", "amf", "oth"]},
            {"title": "Advisory fees ($M) vs client fees earned", "type": "bar", "series": ["adv", "nfee"], "y2": ["nfee"], "types": ["bar", "line"]},
            {"title": "Avg fee per advisory + underwriting client fee ($M)", "type": "line", "series": ["avg_fee"]},
            {"title": "Advisory fees per IB SMD (LTM, $M) vs IB SMDs", "type": "line", "series": ["adv_smd_ltm", "smd_ib"], "y2": ["smd_ib"]},
            {"title": "Adj. and GAAP diluted EPS", "type": "bar", "series": ["adj_eps", "gaap_eps"]},
            {"title": "Adj. comp, non-comp ratios and operating margin (%)", "type": "line", "series": ["adj_comp", "adj_noncomp", "opm_adj"]},
            {"title": "Investment Management: Wealth AUM ($bn) vs segment adj. net revenues ($M)", "type": "line", "series": ["aum", "im_adj"], "y2": ["im_adj"]}],
        "rows": rows,
        "notes": ["Source: Evercore quarterly earnings releases (SEC Form 8-K, Exhibit 99.1); one link per quarter. Each quarter is as first reported in its own release (later recasts not applied). Refreshed automatically: the weekday workflow checks EDGAR for a new Item 2.02 8-K and adds the quarter only if it passes the checks below.",
            "Revenue lines are U.S. GAAP and sum to GAAP net revenues every quarter (checked). Advisory, Underwriting and Commissions are the Investment Banking & Equities segment; Asset Management & Administration Fees are the Investment Management segment (Wealth Management); Other revenue is mostly interest and investment-fund marks, net of interest expense. Adjusted net revenues add back mainly the Robey Warshaw / notes-related interest and equity-method reclasses; adjusted advisory fees differ from GAAP by < $1M a quarter.",
            "* Computed: avg fee = (advisory + underwriting fees) / number of advisory and underwriting client fees; per-SMD = advisory fees / period-end IB SMDs; LTM = trailing four quarters (Q4 2021-Q2 2022 use the year-ago advisory column of the releases a year later for Q1-Q3 2021).",
            "SMD headcount is as stated in each release and, per Evercore's footnote, includes SMDs who have committed to join and excludes known departures as of the release date. Label change: 'Advisory SMDs' through Q4 2023, 'Investment Banking SMDs' from Q1 2024 (same population: Q1 2024's year-ago figure equals the Q1 2023 Advisory count). Total is IB & Equities SMDs (incl. Equities/research). Hires and promotions are not disclosed on a consistent quarterly basis, so they are not tabulated; disclosed: 17 Advisory MDs promoted to SMD in Jan 2022, 7 Advisory SMDs hired in 2022, 7 Advisory promotions in Jan 2023 and Jan 2024, 8 IB promotions in Jan 2026, 14 IB SMD hires YTD 2026 (as of the Q3 2026 release).",
            "Segment labels: 'Investment Banking' renamed 'Investment Banking & Equities' from the Q4 2022 release; client-fee counts labelled 'from Advisory Client Transactions' through Q4 2022 and 'from Advisory and Underwriting Client Transactions' from Q1 2023 (year-ago comparatives unchanged, so treated as continuous).",
            "Adj. comp and non-comp ratios, adj. operating margin and EPS are Evercore's non-GAAP figures (A-2 reconciliation); adj. diluted shares include Evercore LP units. Wealth Mgmt AUM is period-end AUM of the consolidated Wealth Management business. First-quarter EPS is lifted by the tax deduction on employee share awards vesting above grant price (adj. effective tax rate 3.0% in Q1 2026 and (39.7%) in Q1 2025 vs ~25-29% in other quarters)."]}

COMPANIES = [hli, cns, wt, evr]


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

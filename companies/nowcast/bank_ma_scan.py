"""Weekly bank M&A scan -> companies/bank_ma/universe.json (+ deals_auto.json), then rebuilds data/bank-ma.json.

What it does (warn-only; never fails the pipeline):
  1. Sweeps SEC EDGAR full-text search (efts.sec.gov) for 8-K and Form 425 filings in the scan window that
     contain merger-agreement language ("definitive agreement", "agreement and plan of merger", ...) together
     with "bank", keeping only filers with bank / thrift SIC codes (6021, 6022, 6029, 6035, 6036, 6712).
  2. For each new filing, reads the press-release / presentation exhibits and decides whether it ANNOUNCES a
     new whole-company bank or thrift merger (not a completion, approval or proxy update).
  3. Parses deal terms with regexes. Every parsed value keeps the source URL and the verbatim snippet it came
     from; anything not found is left blank, never estimated.
  4. Every announced US bank/thrift deal (any size) is added to the "All announced bank deals" table
     (companies/bank_ma/universe.json). If acquirer, target, date and a stated aggregate deal value of $500M+
     all parse cleanly, the deal is ALSO auto-added to the main table (companies/bank_ma/deals_auto.json)
     flagged "auto-added, pending review". Announcements that cannot be parsed go to the candidates list.
  5. Re-checks status (completion / termination 8-Ks) of pending deals in the All-deals table.

SEC fair access: identifies itself with a User-Agent and pauses between requests (<= ~4 req/s).

Run: python3 companies/nowcast/bank_ma_scan.py                      (scan since last scan - 7 days)
     python3 companies/nowcast/bank_ma_scan.py --since 2026-01-01    (backfill window)
     python3 companies/nowcast/bank_ma_scan.py --no-status           (skip status re-checks)
"""
import datetime as dt, hashlib, json, os, pathlib, re, sys, time, urllib.parse

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import bank_ma as BM  # noqa: E402

ROOT = BM.ROOT
UNIV = BM.CURDIR / "universe.json"
AUTO = BM.CURDIR / "deals_auto.json"
CACHE = os.environ.get("BANK_MA_CACHE")  # optional local doc cache for backfills
BANK_SIC = {"6021", "6022", "6029", "6035", "6036", "6712"}
QUERIES = ['"definitive merger agreement"', '"definitive agreement"', '"agreement and plan of merger"',
           '"agreement and plan of reorganization"', '"merger agreement"']
MIN_MAIN = 500  # $M, main-table threshold


def get(url):
    if CACHE:
        p = pathlib.Path(CACHE) / hashlib.md5(url.encode()).hexdigest()
        if p.exists(): return p.read_text()
        t = BM.get(url); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(t); return t
    return BM.get(url)


def sweep(start, end):
    """EDGAR full-text search -> {accession: filing group} for bank/thrift filers."""
    G = {}
    for q in QUERIES:
        for forms in ("8-K", "425"):
            frm = 0
            while True:
                u = "https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(
                    {"q": q + " bank", "forms": forms, "dateRange": "custom", "startdt": start, "enddt": end, "from": frm})
                r = json.loads(BM.get(u)); hs = r["hits"]["hits"]; tot = r["hits"]["total"]["value"]
                for h in hs:
                    s = h["_source"]
                    if not BANK_SIC & set(s.get("sics") or []): continue
                    acc, fn = h["_id"].split(":", 1)
                    g = G.setdefault(acc, {"acc": acc, "filed": s.get("file_date"), "form": (s.get("root_forms") or [forms])[0],
                                           "names": s.get("display_names") or [], "ciks": [int(c) for c in s.get("ciks") or []],
                                           "items": s.get("items") or [], "docs": set()})
                    g["docs"].add(fn)
                frm += 100
                if not hs or frm >= min(tot, 10000): break
    return G


# ---------------------------------------------------------------- announcement detection / parties
ANN = re.compile(r"(?:entered into|signed|executed|execution of|announced)[^.]{0,120}?(?:definitive|merger|reorganization|affiliation|combination)[^.]{0,25}?agreement|agreement and plan of (?:merger|reorganization)|definitive agreement (?:to|under which|pursuant)", re.I)
DONE = re.compile(r"(?:complet|consummat|closing of|clos(?:ed|es) (?:its|the))[^.]{0,60}(?:merger|acquisition|transaction)|shareholders? (?:have )?approv|received (?:all )?regulatory approval|special meeting|proxy statement/prospectus (?:is|was) (?:first )?mailed", re.I)
TOK = r"(?:[A-Z][A-Za-z0-9&'’.\-]*|&|of|and|de|du)"
NAME = rf"[A-Z][A-Za-z0-9&'’.\-]*(?: {TOK}){{0,6}}(?:,? (?:Inc\.?|N\.A\.|LLC|L\.L\.C\.|F\.S\.B\.|SSB|National Association))?"
PAR = r"(?:\s*\([^()]{0,120}\))*"
BAD_FIRST = re.compile(r"^(?:Immediately|Following|Effective|Under|Upon|Pursuant|Merger|The Merger|Subject|Each|Such|After|Prior|Concurrently|Holders?|Shareholders?|Stockholders?|Exhibit|EXHIBIT|Item|Section|Agreement|Bank Merger|Parent|Buyer|Seller|Company|Purchaser|Acquiror|Target)\b")
STRIP_CO = re.compile(r",? (?:Inc\.?|N\.A\.|LLC|L\.L\.C\.|F\.S\.B\.|SSB|National Association)$")


def strip_co(s):
    s = re.sub(r"\s*\((?:[^)]*)\)", "", s or "").strip(" ,.;“”\"")
    s = re.sub(r"^(?:the|The) ", "", s)
    return s


def norm(s):
    s = strip_co(s).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(the|inc|corp|corporation|company|co|holdings?|group|n a|na|fsb|f s b|ssb|mhc|bancorp|bancorporation|bancshares|bankshares|financial|services|bank|banc|trust|of|and)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def aliases(t):
    """Defined terms: 'Texas Community Bancshares, Inc. (NASDAQ: TCBS) (the “Company”)' -> {'Company': full name}."""
    out = {}
    for m in re.finditer(rf"({NAME}){PAR}?\s*\((?:the |collectively, |together, )?[“\"]([^”\"]{{2,40}})[”\"]\)", t[:9000]):
        full, al = m.group(1).strip(), m.group(2).strip()
        if BAD_FIRST.match(full) and not al: continue
        if al not in out and len(full) > len(al) - 1 and not re.match(r"(?i)merger|agreement|effective|closing|exchange", al): out[al] = full
    return out


def parties(t):
    """Return (acquirer, target, snippet) from announcement text, or (None, None, None)."""
    head = t[:7000]
    al = aliases(head)
    A_, T_ = rf"(?:the )?(?P<acq>{NAME}){PAR}", rf"(?:the )?(?P<tgt>{NAME}){PAR}"
    pats = [
        rf"pursuant to which {T_} will (?:merge with and into|be merged with and into|merge into) {A_}",
        rf"{A_}(?:,[^,.;]{{0,110}},)? (?:will|to|agreed to|has agreed to|have agreed to|plans to) acquire {T_}",
        rf"{A_}(?:,[^,.;]{{0,110}},)? (?:today )?announce[sd]?[^.]{{0,140}}?agreement (?:to acquire|under which it will acquire|pursuant to which it will acquire|to merge with) {T_}",
        rf"{A_}(?:,[^,.;]{{0,110}},)? (?:has |have )?entered into an? (?:Agreement and Plan of (?:Merger|Reorganization)|(?:definitive )?(?:merger )?agreement)[^.]{{0,160}}?\bwith {T_}",
        rf"by and (?:among|between) {A_},(?: [^,]{{0,40}}Merger Sub[^,]{{0,20}},(?: (?:Inc\.|LLC|Corp\.),)?)? and {T_}",
        rf"acquisition of {T_} by {A_}",
        rf"{T_} (?:will be acquired by|to be acquired by|agreed to be acquired by) {A_}",
        rf"{A_} to Acquire {T_}",
    ]
    for p in pats:
        for m in re.finditer(p, head):
            fix = lambda x: x.strip().rstrip(",") if re.search(r"(?:Inc|N\.A|Co|Corp|F\.S\.B|L\.L\.C)\.$", x.strip()) else x.strip().rstrip(".,")
            a, b = fix(m.group("acq")), fix(m.group("tgt"))
            a = re.split(r"(?:\. |Signs (?:a )?Definitive Agreement|Announces Agreement|Immediate Release)\s*", a)[-1].strip()
            b = re.split(r"\. ", b)[0].strip()
            if " and " in b:  # "Stellar and Stellar Bank", "National Association and Signature Bancorporation, Inc."
                b = next((x.strip() for x in b.split(" and ") if norm(x) and not re.match(r"(?i)national association|its |the ", x.strip())), b)
            a, b = al.get(a, a), al.get(b, b)
            if BAD_FIRST.match(a) or BAD_FIRST.match(b) or re.search(r"Merger Sub|\bSub\b", a + "|" + b): continue
            if not norm(a) or not norm(b) or norm(a) == norm(b) or len(a) < 3 or len(b) < 3: continue
            return a, b, BM_snip(head, m.start(), m.end())
    return None, None, None


def BM_snip(t, i, j, pad=110):
    return "…" + t[max(0, i - pad):min(len(t), j + pad)].strip() + "…"


# ---------------------------------------------------------------- term parsing
NUM = r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"


def fnum(s): return float(s.replace(",", ""))


def money_m(n, unit):
    return round(fnum(n) * (1000 if unit.lower().startswith("b") else 1), 1)


PATTERNS = {
    # key: list of (regex, converter(match)->value)
    "deal_value_m": [
        (rf"(?:valued at|transaction value of|aggregate (?:deal |transaction )?value of|deal value of|aggregate (?:merger )?consideration of|total (?:deal|transaction) value of|for total consideration of|implies an aggregate transaction value of)\s*(?:approximately |about |roughly |~)?\$\s?{NUM}\s?(billion|million|bn|mm|B|M)\b", lambda m: money_m(m.group(1), m.group(2))),
        (rf"\${NUM}\s?(billion|million|B|MM)\b in aggregate (?:deal |transaction )?value", lambda m: money_m(m.group(1), m.group(2))),
        (rf"(?:total|aggregate|implied) (?:merger |deal |transaction )?(?:consideration|value)(?: of the (?:transaction|merger|deal))? (?:is|was|of|totals|equals)(?: estimated to be| expected to be| valued at)? (?:approximately |about |roughly |~)?\$\s?{NUM}\s?(billion|million|bn|mm)\b", lambda m: money_m(m.group(1), m.group(2))),
        (rf"(?:transaction|merger|deal) (?:is )?valued at (?:approximately |about )?\$\s?{NUM}\s?(billion|million)\b", lambda m: money_m(m.group(1), m.group(2))),
        (rf"\${NUM}\s?(B|MM|M)\s+(?:Aggregate )?(?:Deal|Transaction) Value", lambda m: money_m(m.group(1), m.group(2))),
        (rf"\${NUM}\s?(billion|million)\s+(?:aggregate )?(?:deal|transaction) value", lambda m: money_m(m.group(1), m.group(2))),
        (rf"(?:Aggregate (?:Transaction )?(?:Value|Consideration)|Transaction Value|Deal Value)\s?[:–-]\s?\$\s?{NUM}\s?(billion|million|B|MM|M)\b", lambda m: money_m(m.group(1), m.group(2))),
    ],
    "price_per_share": [
        (rf"(?:valued at|value of|consideration of|implies a (?:per share )?value of|equates to|equal to|~)\s*(?:approximately |~)?\${NUM} per (?:share|[A-Z][a-z]+ share)", lambda m: fnum(m.group(1))),
        (rf"\${NUM} per share or \$", lambda m: fnum(m.group(1))),
        (rf"Price per (?:Target )?Share:?\s*\${NUM}", lambda m: fnum(m.group(1))),
    ],
    "exchange_ratio": [
        (r"(?:receive|issue|exchange ratio of)\s*(\d\.\d{2,5}) shares? of", lambda m: float(m.group(1))),
        (r"Exchange Ratio:?\s*(\d\.\d{2,5})", lambda m: float(m.group(1))),
    ],
    "p_tbv": [
        (rf"(?:Price\s?/\s?(?:Tangible Book Value|TBV)(?: per share| ?PS)?|price to tangible book value(?: per share)?(?: multiple)?(?: of)?)[^\d$]{{0,25}}{NUM}\s?x", lambda m: fnum(m.group(1))),
        (rf"{NUM}\s?x (?:price to |P/)?(?:tangible book value|TBV)", lambda m: fnum(m.group(1))),
    ],
    "p_ltm_eps": [(rf"Price\s?/\s?(?:LTM|Last Twelve Months|TTM) (?:EPS|Earnings)[^\d]{{0,15}}{NUM}\s?x", lambda m: fnum(m.group(1)))],
    "p_fwd_eps": [(rf"Price\s?/\s?(?:20\d\d|'\d\d)E? ?(?:consensus )?EPS[^\d]{{0,15}}{NUM}\s?x", lambda m: fnum(m.group(1)))],
    "cdp": [
        (rf"core deposit premium[^\d]{{0,25}}{NUM}\s?%", lambda m: fnum(m.group(1))),
        (rf"{NUM}\s?% (?:core )?deposit premium", lambda m: fnum(m.group(1))),
    ],
    "eps_accr": [
        (rf"(?:approximately |~)?{NUM}\s?% accretive to [^.]{{0,60}}?(?:earnings per share|EPS)", lambda m: fnum(m.group(1))),
        (rf"(?:EPS|earnings per share) accretion of (?:approximately |~)?{NUM}\s?%", lambda m: fnum(m.group(1))),
        (rf"~?{NUM}\s?% ‘?'?(?:\d\d|20\d\d)E? EPS Accretion", lambda m: fnum(m.group(1))),
    ],
    "tbv_dil": [
        (rf"(?:approximately |~)?{NUM}\s?% dilutive to tangible book value", lambda m: fnum(m.group(1))),
        (rf"tangible book value(?: per share)? dilution of (?:approximately |~)?{NUM}\s?%", lambda m: fnum(m.group(1))),
        (rf"\(~?{NUM}\s?%\) TBV(?:PS)? Dilution", lambda m: fnum(m.group(1))),
    ],
    "earnback": [
        (rf"earn-?\s?back(?: period)?(?: of| in)? (?:approximately |~)?{NUM} years", lambda m: fnum(m.group(1))),
        (rf"~?{NUM} years (?:TBV(?:PS)? )?Earn-?\s?back", lambda m: fnum(m.group(1))),
    ],
    "cost_saves": [(rf"{NUM}\s?% of [^.]{{0,25}}?(?:non-?interest|operating) expense", lambda m: fnum(m.group(1)))],
    "credit_mark_m": [(rf"\${NUM} million (?:gross )?(?:loan )?credit mark", lambda m: fnum(m.group(1))),
                      (rf"credit mark of (?:approximately )?\${NUM} million", lambda m: fnum(m.group(1)))],
    "credit_mark_pct": [(rf"credit mark[^.%]{{0,60}}?{NUM}\s?% of (?:gross |total )?loans", lambda m: fnum(m.group(1)))],
    "rate_mark_m": [(rf"\$\(?{NUM}\)? million (?:pre-tax )?(?:loan |interest rate )(?:rate )?mark", lambda m: fnum(m.group(1))),
                    (rf"(?:loan )?(?:interest )?rate mark of (?:approximately )?\$\(?{NUM}\)? million", lambda m: fnum(m.group(1)))],
    "cdi_pct": [(rf"core deposit intangible[^.%]{{0,40}}?{NUM}\s?% of", lambda m: fnum(m.group(1)))],
    "pf_cet1": [(rf"(?:pro forma )?CET1(?: Ratio)?(?: at close)?[^\d.]{{0,20}}{NUM}\s?%", lambda m: fnum(m.group(1))),
                (rf"{NUM}\s?% CET1 Ratio", lambda m: fnum(m.group(1)))],
    "tgt_own": [],  # filled in parse() once the target name is known
    "pf_assets_b": [(rf"(?:combined (?:company|organization|bank|franchise)\b|pro forma (?:company|organization)\b|creat(?:e|es|ing) an?|establish(?:es)? an?|(?:will|would|expected to) have)[^.$]{{0,80}}?(?:approximately |~|over )?\${NUM}\s?(?:billion|B)\b[^.$]{{0,12}}?(?:in |of )?(?:total |combined )?assets", lambda m: fnum(m.group(1))),
                    (rf"Pro Forma (?:Snapshot|Highlights|Franchise)[\s\S]{{0,140}}?\${NUM}\s?B (?:Total )?Assets", lambda m: fnum(m.group(1)))],
}


def find(t, key, pats, src, out, lo=0, hi=None):
    if key in out: return
    seg = t[lo:hi] if hi else t[lo:]
    for p, fn in pats:
        m = re.search(p, seg, re.I)
        if m:
            try: v = fn(m)
            except Exception: continue  # noqa: BLE001
            out[key] = {"v": v, "src": src, "q": BM_snip(seg, m.start(), m.end())}
            return


def parse_terms(docs, tgt):
    """docs: list of (url, text). Returns field dict {key: {v, src, q}} (blank = not found)."""
    out = {}
    tw = re.escape(tgt.split()[0]) if tgt else None
    tpats = {
        "tgt_assets_b": [(rf"{tw}[^.]{{0,200}}?(?:has|had|with|holds)[^.]{{0,40}}?\${NUM}\s?(?:billion|B) (?:in |of )?(?:total )?assets", lambda m: fnum(m.group(1)))] if tw else [],
        "tgt_deposits_b": [(rf"{tw}[^.]{{0,260}}?\${NUM}\s?(?:billion|B) (?:in |of )?(?:total )?deposits", lambda m: fnum(m.group(1)))] if tw else [],
        "tgt_loans_b": [(rf"{tw}[^.]{{0,260}}?\${NUM}\s?(?:billion|B) (?:in |of )?(?:total |gross )?loans", lambda m: fnum(m.group(1)))] if tw else [],
        "tgt_own": [(rf"{tw}(?:’s|'s)? (?:share|stock)holders will own approximately {NUM}\s?%", lambda m: fnum(m.group(1))),
                    (rf"approximately {NUM}\s?% (?:owned )?by (?:former )?{tw}", lambda m: fnum(m.group(1)))] if tw else [],
    }
    for url, t in docs:
        for k, pats in list(PATTERNS.items()) + list(tpats.items()):
            find(t, k, pats, url, out)
        m = re.search(r"(?:expected|anticipated) to (?:close|be completed)[^.]{0,30}?(?:in |during |by )?(?:the )?((?:first|second|third|fourth) quarter|(?:first|second) half|(?:early|mid|late|end of|middle of)(?: the)?(?: first| second| third| fourth)?(?: quarter| half)?(?: of)?)[^.]{0,6}?(?:of )?(20\d\d)", t, re.I)
        if m and "expected_close" not in out:
            qm = {"first quarter": "1Q", "second quarter": "2Q", "third quarter": "3Q", "fourth quarter": "4Q", "first half": "1H", "second half": "2H"}
            lab = qm.get(m.group(1).lower(), m.group(1).strip())
            out["expected_close"] = {"v": f"{lab} {m.group(2)}", "src": url, "q": BM_snip(t, m.start(), m.end())}
        if "consideration" not in out:
            m = re.search(r"(all[- ]stock|100% stock|all[- ]cash|100% cash|cash and stock|stock and cash|\d{1,3}% (?:cash|stock)[^.]{0,20}\d{1,3}% (?:cash|stock))", t, re.I)
            if m:
                v = m.group(1).lower().replace("all-stock", "100% stock").replace("all stock", "100% stock").replace("all-cash", "100% cash").replace("all cash", "100% cash")
                if v in ("cash and stock", "stock and cash"): v = "Cash & stock"
                out["consideration"] = {"v": v[0].upper() + v[1:] if v[0].isalpha() else v, "src": url, "q": BM_snip(t, m.start(), m.end())}
    if "price_per_share" in out and re.search(r"(?i)par value", out["price_per_share"]["q"]): out.pop("price_per_share")
    if "consideration" in out and re.search(r"(?i)stock option|restricted stock|exchange agent|fractional", out["consideration"]["q"]): out.pop("consideration")
    # sanity bounds: drop implausible parses rather than publish them
    bounds = {"p_tbv": (0.3, 4), "p_fwd_eps": (3, 40), "p_ltm_eps": (3, 60), "cdp": (-10, 40), "eps_accr": (0, 80), "tbv_dil": (0, 40),
              "earnback": (0, 10), "cost_saves": (5, 70), "credit_mark_pct": (0.1, 6), "cdi_pct": (0.3, 10), "pf_cet1": (6, 20), "tgt_own": (1, 70),
              "price_per_share": (1, 5000), "deal_value_m": (1, 200000)}
    for k, (a, b) in bounds.items():
        if k in out and isinstance(out[k]["v"], (int, float)) and not a <= out[k]["v"] <= b: out.pop(k)
    if "exchange_ratio" in out:  # fold into consideration note
        er = out.pop("exchange_ratio")
        if "consideration" in out: out["consideration"]["note"] = f"{er['v']} acquirer shares per target share"
    return out


STATES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}


def doc_order(g):
    def pr(fn):
        f = fn.lower()
        if re.search(r"ex-?99[-_.]?0?1|ex991|dex991|99d1|ex99\b", f): return 0
        if re.search(r"99", f): return 1
        if "425" in f: return 2
        if re.search(r"ex-?2|dex2|ex10|ex-10|ex4|ex-4|ex3|ex-3", f): return 9
        return 3
    return sorted(g["docs"], key=lambda f: (pr(f), f))


def filing_docs(g):
    """All .htm documents in the filing (from the EDGAR index), press-release exhibits first."""
    cik = g["ciks"][0] if g["ciks"] else None
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{g['acc'].replace('-', '')}/"
    names = list(g["docs"])
    try:
        idx = json.loads(get(base + "index.json"))
        names = [x["name"] for x in idx["directory"]["item"] if re.search(r"\.html?$", x["name"], re.I)] or names
    except Exception:  # noqa: BLE001
        pass
    names = [n for n in names if not re.search(r"ex-?(?:2|3|4|5|8|10|21|23|24|31|32|101|104)(?:[-_.d]|\b)|dex(?:2|3|4|5|8|10|23)\d|index|\.pdf$|\.jpg$|\.xml$|R\d+\.htm", n, re.I)]
    return base, sorted(names, key=lambda f: ({**{n: i for i, n in enumerate(doc_order({"docs": names}))}}[f]))


def lead_text(t):
    """Skip the 8-K / 425 cover page and cut forward-looking-statement boilerplate."""
    i = t.find("Emerging growth company")
    if 0 <= i < 6000:
        m = re.search(r"Item \d\.\d\d", t[i:])
        if m: t = t[i + m.start():]
    t = re.split(r"(?i)(?:cautionary (?:note|statement)[^.]{0,40}|)forward[- ]looking statements? ", t, maxsplit=1)[0] if len(t) > 3000 else t
    return t[:7000]


def classify(g):
    """Return dict(kind='deal'|'unparsed'|None, ...) for a filing group."""
    cik = g["ciks"][0] if g["ciks"] else None
    base, names = filing_docs(g)
    texts = []
    for fn in names[:4]:
        try: t = BM.clean(get(base + fn))
        except Exception: continue  # noqa: BLE001
        texts.append((base + fn, t))
    ann = None
    for url, t in texts:
        lead = lead_text(t)
        m = ANN.search(lead)
        if not m: continue
        pre = lead[max(0, m.start() - 600):m.end() + 300]
        if DONE.search(pre) and not re.search(r"(?i)today announced|announced today|jointly announced", pre): continue
        if re.search(r"(?i)previously announced|previously disclosed|as announced on", pre[:m.end() - max(0, m.start() - 600) + 50]) and not re.search(r"(?i)today announced|announced today", pre): continue
        if not re.search(r"(?i)\bbank|bancorp|bancshares|savings|thrift|financial", pre): continue
        ann = (url, t, m); break
    if not ann: return None
    url, t, m = ann
    acq, tgt, psnip = parties(lead_text(t))
    if not acq:
        for _, t2 in texts:
            acq, tgt, psnip = parties(lead_text(t2))
            if acq: break
    filer = re.sub(r"\s+\(.*", "", g["names"][0]) if g["names"] else ""
    res = {"filed": g["filed"], "acc": g["acc"], "form": g["form"], "filer": filer, "filer_cik": cik, "ciks": g["ciks"], "url": url,
           "lead": BM_snip(t, m.start(), m.end())}
    if acq and tgt and not role_of(filer, acq, tgt) and not any(role_of(re.sub(r"\s+\(.*", "", n), acq, tgt) for n in g["names"]):
        acq = tgt = None  # neither party is the filer: parse is not trustworthy
    if not acq or not tgt:
        res["kind"] = "unparsed"; return res
    # non-bank targets (wealth, insurance, fintech, branch deals) are out of scope
    tblob = t[:8000]
    if re.search(rf"(?i)(branch(?:es)? (?:purchase|acquisition|sale)|purchase and assumption)", tblob) and not re.search(r"(?i)merge with and into|merger", tblob[:3000]):
        res["kind"] = None; return res
    if re.search(r"(?i)\b(wealth|advisors?|insurance|agency|capital management|asset management|investment|securities|leasing|technolog|fintech|payments?|mortgage company|REIT|realty|properties)\b", tgt) and not re.search(r"(?i)bank|bancorp|bancshares|savings|financial", tgt):
        res["kind"] = None; return res
    res.update(kind="deal", acquirer=acq, target=tgt, parties_q=psnip,
               f=parse_terms(texts, tgt))
    # target state / tickers: only when stated right next to the party's own name (no guessing)
    def near(name):
        n = strip_co(name); n = re.sub(r",? (?:Inc|N\.A|F\.S\.B|LLC)\.?$", "", n)
        return re.escape(n[:30])
    sm = re.search(rf"{near(tgt)}[^.;]{{0,120}}?(?:headquartered|based) in [A-Z][A-Za-z .'-]+?,? ({'|'.join(STATES)})\b", t) or \
        re.search(rf"\b({'|'.join(STATES)})[- ]based {near(tgt)}", t)
    if sm: res["f"]["tgt_state"] = {"v": STATES[sm.group(1)], "src": url, "q": BM_snip(t, sm.start(), sm.end())}
    TKR = r"\((?:[“\"][^”\"]*[”\"]\)\s*\()?(?:NASDAQ|Nasdaq|NYSE|NYSE American|OTCQX|OTCQB|OTC Pink|OTC)(?: Global Select Market| Capital Market| Global Market)?:\s*([A-Z]{1,5})\)"
    tk = re.search(rf"{near(tgt)}(?:,? (?:Inc|Corp|N\.A)\.?)?\s*{TKR}", t)
    ak = re.search(rf"{near(acq)}(?:,? (?:Inc|Corp|N\.A)\.?)?\s*{TKR}", t)
    res["tgt_ticker"] = tk.group(1) if tk else None
    res["acq_ticker"] = ak.group(1) if ak else None
    if res["tgt_ticker"] and res["tgt_ticker"] == res["acq_ticker"]: res["tgt_ticker"] = None
    return res


# ---------------------------------------------------------------- universe / main-table maintenance
def slug(a, b):
    f = lambda s: (re.sub(r"[^a-z0-9]+", "", (norm(s).split() or ["x"])[0]))[:12] or "x"
    return f"{f(a)}-{f(b)}"


def same_deal(r, acq, tgt, atk=None, ttk=None):
    if ttk and r.get("tgt_ticker") == ttk and (not atk or r.get("acq_ticker") in (atk, None, "")): return True
    na, nt = norm(acq), norm(tgt); ra, rt = norm(r["acquirer"]), norm(r["target"])
    def eq(x, y): return bool(x) and bool(y) and (x == y or x.startswith(y + " ") or y.startswith(x + " ") or x.split()[0] == y.split()[0] and len(x.split()[0]) > 4)
    return (eq(na, ra) and eq(nt, rt)) or (eq(na, rt) and eq(nt, ra))


def name_rx(n):
    """Distinctive regex for a party name: its first two words (suffixes / parentheticals dropped)."""
    w = re.sub(r"\s*\(.*?\)", "", n).replace(",", " ").split()
    w = [x for x in w if x not in ("The", "Inc.", "Inc", "Corp.", "Corporation", "Company")] or w
    return r"\s+".join(re.escape(x) for x in w[:2])


def role_of(filer, acq, tgt):
    f = norm(filer)
    if not f: return None
    if norm(acq).split()[:1] == f.split()[:1]: return "acq"
    if norm(tgt).split()[:1] == f.split()[:1]: return "tgt"
    return None


MAIN_KEYS = {c[0] for c in BM.COLS} | {"tgt_state", "expected_close"}


def load_json(p, default):
    try: return json.loads(p.read_text())
    except Exception: return default  # noqa: BLE001


def main(since=None, status=True):
    today = dt.date.today()
    U = load_json(UNIV, {"last_scanned": None, "coverage_start": "2026-01-01", "deals": [], "candidates": []})
    A = load_json(AUTO, {"deals": []})
    curated = [d for f in sorted(BM.CURDIR.glob("deals_*.json")) if f.name != AUTO.name for d in json.loads(f.read_text())["deals"]]
    start = since or (dt.date.fromisoformat(U["last_scanned"][:10]) - dt.timedelta(days=7)).isoformat() if (since or U.get("last_scanned")) else (today - dt.timedelta(days=14)).isoformat()
    warnings = []
    try:
        G = sweep(start, today.isoformat())
    except Exception as e:  # noqa: BLE001
        print("::warning::EDGAR full-text sweep failed:", e); G = {}; warnings.append(f"sweep failed: {e}")
    seen = set(U.get("seen_acc", []))
    found = []
    for acc, g in sorted(G.items(), key=lambda kv: kv[1]["filed"]):
        if acc in seen: continue
        try: r = classify(g)
        except Exception as e:  # noqa: BLE001
            warnings.append(f"{acc}: {e}"); continue
        seen.add(acc)
        if r: found.append(r)
    added_u, added_main, cands = [], [], {c["acc"]: c for c in U.get("candidates", []) if c.get("acc")}
    for r in found:
        if r["kind"] == "unparsed":
            if not any(r["acc"] == c for c in cands): cands[r["acc"]] = {k: r[k] for k in ("filed", "acc", "form", "filer", "url", "lead")}
            continue
        if r["kind"] != "deal" or re.search(r"\bLtd\b|Japan|Tokyo", r["filer"] + r["acquirer"] + r["target"]): continue
        acq, tgt = r["acquirer"], r["target"]
        hit = next((u for u in U["deals"] if same_deal(u, acq, tgt, r.get("acq_ticker"), r.get("tgt_ticker"))), None)
        if hit:  # same deal seen again (other party's filing, later 425s): fill gaps only, keep earliest date
            for k, v in r["f"].items(): hit["f"].setdefault(k, v)
            if r["filed"] < hit["announced"]: hit["announced"] = r["filed"]
            role = role_of(r["filer"], hit["acquirer"], hit["target"])
            if role and str(r["filer_cik"]) not in hit["roles"]: hit["roles"][str(r["filer_cik"])] = role
            continue
        main_hit = next((d for d in curated + A["deals"] if same_deal(d, acq, tgt, r.get("acq_ticker"), r.get("tgt_ticker"))), None)
        row = {"id": slug(acq, tgt), "announced": r["filed"], "acquirer": acq, "acq_ticker": r.get("acq_ticker"), "target": tgt,
               "tgt_ticker": r.get("tgt_ticker"), "f": {k: v for k, v in r["f"].items()}, "sources": {"Announcement (" + r["form"] + ")": r["url"]},
               "parties_q": r.get("parties_q"), "roles": {str(r["filer_cik"]): role} if (role := role_of(r["filer"], acq, tgt)) else {}, "status": "pending", "origin": "scan", "first_seen": today.isoformat()}
        if main_hit: row["main_id"] = main_hit["id"]
        U["deals"].append(row); added_u.append(row)
        cands.pop(r["acc"], None)
    # auto-add to the main table: clean parse + stated value >= $500M, not already there
    for row in added_u:
        v = (row["f"].get("deal_value_m") or {}).get("v")
        if row.get("main_id") or v is None or v < MIN_MAIN or row["announced"] < "2026-11-12": continue
        d = {"id": row["id"], "announced": row["announced"], "acquirer": row["acquirer"], "acq_ticker": row.get("acq_ticker") or "",
             "target": row["target"], "tgt_ticker": row.get("tgt_ticker") or "private", "deal_type": "Acquisition",
             "sources": row["sources"], "f": {k: x for k, x in row["f"].items() if k in MAIN_KEYS},
             "auto": True, "review": "auto-added, pending review", "auto_added": today.isoformat(),
             "check": {"roles": row["roles"], "acq_rx": name_rx(row["acquirer"]), "tgt_rx": name_rx(row["target"])}}
        A["deals"].append(d); row["main_id"] = d["id"]; added_main.append(d["id"])
    # status re-check for pending all-deals rows not in the main table (main-table rows are checked by bank_ma.py)
    if status:
        for u in U["deals"]:
            if u.get("main_id") or u.get("status") != "pending" or not u.get("roles"): continue
            try:
                r = BM.close_check({"id": u["id"], "acq_ticker": None, "announced": u["announced"],
                                    "check": {"roles": u["roles"], "acq_rx": name_rx(u["acquirer"]), "tgt_rx": name_rx(u["target"])}})
                if r and "status" in r: u.update(r)
                elif r and r.get("exp_update"): u["exp_update"] = r["exp_update"]
            except Exception as e:  # noqa: BLE001
                warnings.append(f"{u['id']}: status check failed: {e}")
    U["deals"].sort(key=lambda u: u["announced"])
    U["candidates"] = sorted(cands.values(), key=lambda c: c["filed"], reverse=True)[:40]
    U["seen_acc"] = sorted(seen)[-4000:]
    U["last_scanned"] = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    U["last_window"] = [start, today.isoformat()]
    U["last_warnings"] = warnings[:20]
    UNIV.write_text(json.dumps(U, indent=1, ensure_ascii=False))
    AUTO.write_text(json.dumps(A, indent=1, ensure_ascii=False))
    print(f"scan {start}..{today}: {len(G)} bank filings, {len(found)} announcements, +{len(added_u)} all-deals rows, +{len(added_main)} main-table (auto) {added_main}, {len(U['candidates'])} unparsed candidates; warnings {warnings[:5]}")
    BM.main(offline=True)  # rebuild data/bank-ma.json / .xlsx with the new rows (status checks run in the weekday refresh)


if __name__ == "__main__":
    a = sys.argv
    try:
        main(since=a[a.index("--since") + 1] if "--since" in a else None, status="--no-status" not in a)
    except Exception as e:  # noqa: BLE001  (warn-only)
        print("::warning::bank M&A weekly scan failed:", e)

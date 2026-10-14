#!/usr/bin/env python3
"""Prediction-markets dashboard data: the top-N most liquid macro / markets / geopolitical markets across
Kalshi (public trade API v2) and Polymarket (Gamma + CLOB APIs). All endpoints are public and keyless.

Selection, recomputed every run so the list rolls forward:
  1. Candidates: Kalshi open events in the Economics, Financials, Commodities, Politics, Elections, World and
     Companies categories; Polymarket active events under macro / markets / geopolitics tags.
  2. Topic filter: a title must match a Macro, Markets or Geopolitical keyword group AND no deny-list term
     (sports, entertainment, crypto, weather, US domestic electoral politics, private-company novelty, ...).
  3. Resolved / closed outcomes are dropped; events with no live outcome are dropped.
  4. Rank by trailing 7-day traded volume (Kalshi: contracts, $1 notional each, from event candlesticks;
     Polymarket: USD volume1wk); ties broken by open interest. A multi-outcome event counts as one item.
     The same question on both venues (FOMC decision for a month, rate cuts in a year, recession by year-end)
     is merged into one item shown side by side, ranked on combined volume.
Nothing is estimated: probabilities are each venue's own prices (Kalshi bid/ask mid when the spread is
<= 10c, else last trade; Polymarket's displayed outcome price). Kalshi 24h/7d changes are last trade vs the
last-trade price a day / a week earlier, so a mid-vs-last gap never shows up as a move."""
import json, re, subprocess, time, datetime as dt
from concurrent.futures import ThreadPoolExecutor

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
K_CATS = {"Economics", "Financials", "Commodities", "Politics", "Elections", "World", "Companies"}
P_TAGS = ["economy", "fed", "fed-rates", "finance", "commodities", "stocks", "tariffs", "geopolitics", "world",
          "middle-east", "ukraine", "china", "inflation", "economic-policy", "banks"]

GROUPS = {
    "Macro": r"\b(fed|fomc|federal reserve|rate cuts?|rate hikes?|interest rates?|fed funds|central bank|ecb|bank of (england|japan|canada)|boj|boe|"
             r"inflation|cpi|pce|gdp|recession|unemployment|jobs|payrolls?|jobless|nonfarm|shutdown|debt ceiling|deficit|tariffs?|trade deal|trade war|powell|fed chair)\b",
    "Markets": r"\b(treasury|treasuries|yields?|10-year|10y|2-year|s&p|s&p 500|nasdaq|dow jones|stock market|largest company|market cap|dollar|euro|yen|"
               r"exchange rate|oil|crude|wti|brent|gold|silver|natural gas|gas prices?|commodit\w*|banks?|banking|fdic|bank failures?|mortgage rates?|vix)\b",
    "Geopolitical": r"\b(war|ceasefire|invade|invasion|blockade|military|ukraine|russia|putin|zelensk\w*|china|taiwan|xi jinping|iran|israel|gaza|hamas|hezbollah|"
                    r"houthi|yemen|hormuz|sanctions?|nato|north korea|venezuela|maduro|syria|prime minister|chancellor|parliament|"
                    r"(brazil|france|french|germany|german|uk|britain|japan|canada|mexico|india|argentina|colombia|chile|peru|poland|hungary|italy|spain|korea|turkey|"
                    r"australia|netherlands|portugal|romania|czech|philippines|south africa|nigeria|pakistan|bangladesh|thailand|indonesia)\w*\b.*\b(election|president|presidential|pm)\b)",
}
DENY = (r"\b(nfl|nba|mlb|nhl|wnba|ufc|f1|formula 1|soccer|football|basketball|baseball|tennis|golf|super bowl|world cup|olympic\w*|premier league|champions league|"
        r"oscars?|grammys?|emmys?|box office|album|movie|film|song|spotify|netflix|taylor swift|celebrity|tiktok|youtube|"
        r"bitcoin|btc|ethereum|eth|crypto|solana|dogecoin|memecoin|microstrategy|coinbase|"
        r"weather|temperature|hurricane|snow|rain|tornado|"
        r"2028|primary|nominee|senate|house seat|governor|mayor|approval rating|epstein|pardon|impeach\w*|cabinet|"
        r"openai|anthropic|spacex|ipo|ipos|valuation|ai bubble|elon|musk|mention|say|tweets?|"
        r"state gas|california|texas|new york|florida)\b")
MERGE_KEYS = [  # same question on both venues -> one item
    (r"fed decision in (\w+)", lambda m, end: "fomc-" + m.group(1)[:3].lower() + "-" + end[:4]),
    (r"how many fed rate cuts in (\d{4})|number of rate cuts in (\d{4})", lambda m, end: "cuts-" + (m.group(1) or m.group(2))),
    (r"recession (by end of|this year|in) ?(\d{4})?", lambda m, end: "recession-" + (m.group(2) or end[:4])),
]


def _get(url, tries=4):
    last = None
    for i in range(tries):
        r = subprocess.run(["curl", "-sS", "-g", "--max-time", "45", "-w", "\n%{http_code}", url], capture_output=True, text=True)
        body, _, code = r.stdout.rpartition("\n")
        if r.returncode == 0 and code == "200":
            return json.loads(body)
        last = f"HTTP {code or r.returncode}: {(body or r.stderr)[:160]}"
        time.sleep(1.5 * (i + 1) + (3 if code == "429" else 0))
    raise RuntimeError(last)


EXCLUDE = []  # persistent user exclusions (regex list from config "exclude")


def classify(title, extra=""):
    t = (title + " " + extra).lower()
    if re.search(DENY, t) or any(re.search(x, t) for x in EXCLUDE):
        return None
    for g, rx in GROUPS.items():
        if re.search(rx, t):
            return g
    return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ Kalshi
def kalshi_candidates(now):
    evs, cur = [], ""
    while True:
        d = _get(f"{KALSHI}/events?status=open&limit=200&cursor={cur}")
        evs += d.get("events", [])
        cur = d.get("cursor")
        if not cur or not d.get("events"):
            break
    out = []
    for e in evs:
        if e.get("category") not in K_CATS:
            continue
        g = classify(e.get("title", ""), e.get("sub_title", ""))
        if g == "Markets" and e.get("category") == "Companies" and not re.search(r"\bbank", e["title"].lower()):
            g = None
        if g:
            out.append((g, e))
    return out


def kalshi_event(g, e, now):
    d = _get(f"{KALSHI}/events/{e['event_ticker']}?with_nested_markets=true")
    ev = d.get("event", e)
    mkts = ev.get("markets") or d.get("markets") or []
    outs = []
    for m in mkts:
        if m.get("status") not in ("active", "open") or m.get("result"):
            continue
        ct = m.get("close_time") or ""
        if ct and ct < now.strftime("%Y-%m-%dT%H:%M:%SZ"):
            continue
        bid, ask, last, prev = (_f(m.get(k)) for k in ("yes_bid_dollars", "yes_ask_dollars", "last_price_dollars", "previous_price_dollars"))
        p = (bid + ask) / 2 if bid is not None and ask and ask - bid <= 0.10 and ask > 0 else last
        if p is None:
            continue
        outs.append({"label": m.get("yes_sub_title") or m.get("subtitle") or m.get("title"), "ticker": m["ticker"], "p": round(p, 4),
                     "last": last,  # changes are measured last-trade vs last-trade (prices a day / a week earlier)
                     "chg24h": round(last - prev, 4) if prev is not None and last is not None else None,
                     "vol": _f(m.get("volume_fp")) or 0.0, "oi": _f(m.get("open_interest_fp")) or 0.0, "close": ct,
                     "strike": _f(m.get("floor_strike")) if m.get("floor_strike") is not None else _f(m.get("cap_strike"))})
    if not outs:
        return None
    return {"venue": "Kalshi", "group": g, "id": e["event_ticker"], "series": ev.get("series_ticker") or e.get("series_ticker"),
            "title": ev.get("title") or e.get("title"), "subtitle": ev.get("sub_title") or "", "exclusive": bool(ev.get("mutually_exclusive")),
            "outcomes": outs, "oi": sum(o["oi"] for o in outs), "vol_total": sum(o["vol"] for o in outs),
            "close": min(o["close"] for o in outs if o["close"]) if any(o["close"] for o in outs) else "",
            "url": f"https://kalshi.com/markets/{(ev.get('series_ticker') or e.get('series_ticker') or '').lower()}"}


def kalshi_history(item, days, now):
    """Daily candles for the event: 7d volume, 7d price change, and history for charts."""
    end = int(now.timestamp()); start = end - days * 86400
    d = _get(f"{KALSHI}/series/{item['series']}/events/{item['id']}/candlesticks?start_ts={start}&end_ts={end}&period_interval=1440")
    tick = d.get("market_tickers") or []
    cands = d.get("market_candlesticks") or []
    by = dict(zip(tick, cands))
    cut7 = end - 7 * 86400
    vol7 = 0.0
    for o in item["outcomes"]:
        cs = by.get(o["ticker"]) or []
        vol7 += sum(_f(c.get("volume_fp")) or 0 for c in cs if c["end_period_ts"] > cut7)
        pts = [(dt.datetime.fromtimestamp(c["end_period_ts"], dt.timezone.utc).date().isoformat(), _f((c.get("price") or {}).get("close_dollars")) or _f((c.get("yes_bid") or {}).get("close_dollars")))
               for c in cs]
        pts = [(t, v) for t, v in pts if v is not None]
        old = [v for t, v in pts if t <= dt.datetime.fromtimestamp(cut7, dt.timezone.utc).date().isoformat()]
        base = o.get("last") if o.get("last") is not None else o["p"]
        o["chg7d"] = round(base - old[-1], 4) if old else None
        o["hist"] = pts
    item["vol7d"] = vol7
    return item


# ------------------------------------------------------------------ Polymarket
def poly_candidates(now):
    seen, out = set(), []
    for t in P_TAGS:
        try:
            evs = _get(f"{GAMMA}/events?tag_slug={t}&active=true&closed=false&limit=100&order=volume1wk&ascending=false")
        except Exception:
            continue
        for e in evs:
            if e["id"] in seen:
                continue
            seen.add(e["id"])
            g = classify(e.get("title", ""))
            if g:
                out.append((g, e))
    return out


def poly_item(g, e, now):
    nowz = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    outs = []
    for m in e.get("markets") or []:
        if m.get("closed") or not m.get("active") or (m.get("endDate") and m["endDate"] < nowz):
            continue
        try:
            prices = json.loads(m.get("outcomePrices") or "[]"); names = json.loads(m.get("outcomes") or "[]")
            toks = json.loads(m.get("clobTokenIds") or "[]")
        except ValueError:
            continue
        if not prices:
            continue
        p = _f(prices[0])
        if p is None or (p <= 0.0005 and (_f(m.get("volume1wk")) or 0) == 0):
            continue
        label = m.get("groupItemTitle") or (m.get("question") if len(e.get("markets")) > 1 else (names[0] if names else "Yes"))
        outs.append({"label": label, "token": toks[0] if toks else None, "p": round(p, 4), "chg24h": _f(m.get("oneDayPriceChange")),
                     "chg7d": _f(m.get("oneWeekPriceChange")), "vol": _f(m.get("volumeNum")) or 0.0, "vol7d": _f(m.get("volume1wk")) or 0.0,
                     "close": m.get("endDate") or "", "slug": m.get("slug")})
    if not outs:
        return None
    return {"venue": "Polymarket", "group": g, "id": str(e["id"]), "title": e.get("title"), "subtitle": "",
            "exclusive": bool(e.get("negRisk")) or len(outs) == 1, "outcomes": outs,
            "vol7d": sum(o["vol7d"] for o in outs), "vol_total": _f(e.get("volume")) or 0.0,  # live outcomes only (expired sub-markets excluded)
            "oi": _f(e.get("openInterest")) or _f(e.get("liquidity")) or 0.0, "liquidity": _f(e.get("liquidity")),
            "close": min((o["close"] for o in outs if o["close"]), default=e.get("endDate") or ""),
            "url": f"https://polymarket.com/event/{e.get('slug')}"}


def poly_history(item, days):
    for o in item["outcomes"][:4]:
        if not o.get("token"):
            continue
        try:
            h = _get(f"{CLOB}/prices-history?market={o['token']}&interval=max&fidelity=1440").get("history") or []
        except Exception:
            continue
        cut = time.time() - days * 86400
        daily = {}
        for x in h:
            if x["t"] >= cut:
                daily[dt.datetime.fromtimestamp(x["t"], dt.timezone.utc).date().isoformat()] = round(x["p"], 4)
        o["hist"] = sorted(daily.items())
    return item



# ------------------------------------------------------------------ pinned markets (fixed tickers / slugs)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
STATIC_PINS = [  # (group, title, kalshi event ticker, polymarket event slug, max outcomes)
    ("Elections", "Which party wins the House (2026 midterms)?", "CONTROLH-2026", "which-party-will-win-the-house-in-2026", 2),
    ("Elections", "Which party wins the Senate (2026 midterms)?", "CONTROLS-2026", "which-party-will-win-the-senate-in-2026", 2),
    ("Elections", "2028 presidential election: winning party", "KXPRESPARTY-2028", "which-party-wins-2028-us-presidential-election", 2),
    ("Elections", "2028 presidential election: winner (top candidates)", "KXPRESPERSON-28", "presidential-election-winner-2028", 6),
    ("Fed & CPI", "Fed decision, December 2026 FOMC", "KXFEDDECISION-26DEC", "fed-decision-in-december-20260729232808632", 6),
]


def cpi_pins(n=2):
    """Next n unreleased CPI prints = the earliest open Kalshi KXCPI events; rolls forward after each release."""
    evs = _get(f"{KALSHI}/events?series_ticker=KXCPI&status=open&limit=50").get("events", [])
    def key(t):
        m = re.search(r"-(\d\d)([A-Z]{3})$", t); return (int(m.group(1)), [x[:3].upper() for x in MONTHS].index(m.group(2))) if m else (99, 99)
    out = []
    for e in sorted(evs, key=lambda e: key(e["event_ticker"]))[:n]:
        yy, mi = key(e["event_ticker"]); mon = MONTHS[mi]; tag = e["event_ticker"].split("-")[1]
        out.append(("Fed & CPI", f"CPI {mon.title()} 20{yy}: m/m", e["event_ticker"], f"{mon}-inflation-us-monthly", 10))
        out.append(("Fed & CPI", f"CPI {mon.title()} 20{yy}: y/y", f"KXCPIYOY-{tag}", f"{mon}-inflation-us-annual", 10))
    return out


def pinned(now, hist_days):
    specs = STATIC_PINS + (_safe(cpi_pins) or [])
    def one(sp):
        g, title, kt, slug, k = sp
        vs = []
        it = _safe(kalshi_event, g, {"event_ticker": kt, "title": title}, now)
        if it:
            it = _safe(kalshi_history, it, hist_days, now) or it
            vs.append(it)
        try:
            e = _get(f"{GAMMA}/events/slug/{slug}", tries=2)
            pi = poly_item(g, e, now) if not e.get("closed") else None
            if pi: vs.append(pi)
        except Exception:
            pass
        for v in vs:
            _trim(v)
            if v["exclusive"]: v["outcomes"] = v["outcomes"][:k]
            for o in v["outcomes"]:
                o.pop("hist", None); o.pop("token", None); o.pop("last", None)
        return {"key": "pin:" + kt, "group": g, "title": title, "pinned": True, "venues": vs,
                "ids": [kt, slug] + [v["id"] for v in vs]} if vs else None
    with ThreadPoolExecutor(4) as ex:
        return [x for x in ex.map(one, specs) if x]

# ------------------------------------------------------------------ assemble
def _merge_key(item):
    t = item["title"].lower()
    for rx, fn in MERGE_KEYS:
        m = re.search(rx, t)
        if m:
            return fn(m, item.get("close") or "")
    return None


def _trim(item):
    """Keep the outcomes that matter: exclusive sets by probability, ladders in strike order within 2-98%."""
    o = item["outcomes"]
    if item["exclusive"]:
        o = sorted(o, key=lambda x: -x["p"])
        o = [x for x in o if x["p"] >= 0.005][:8] or o[:1]
    else:
        live = [x for x in o if 0.02 <= x["p"] <= 0.98] or sorted(o, key=lambda x: abs(x["p"] - 0.5))[:3]
        o = sorted(live, key=lambda x: (x.get("strike") is None, x.get("strike") or 0, x["close"], -x["p"]))[:10]
    item["outcomes"] = o
    return item


def build(cfg, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    top_n, hist_days, n_charts = int(cfg.get("top_n", 12)), int(cfg.get("history_days", 90)), int(cfg.get("charts", 4))
    status = {}
    items = []
    EXCLUDE[:] = [x for x in cfg.get("exclude", [])]
    pins = pinned(now, hist_days)
    pin_ids = {i for p in pins for i in p["ids"]}
    # Kalshi
    try:
        kc = kalshi_candidates(now)
        with ThreadPoolExecutor(6) as ex:
            ks = [x for x in ex.map(lambda ge: _safe(kalshi_event, *ge, now), kc) if x]
        ks.sort(key=lambda x: -(x["oi"] + x["vol_total"] * 0.05))
        pre = ks[:60]  # 7d volume needs candles: only for the plausible leaders
        with ThreadPoolExecutor(6) as ex:
            pre = [x for x in ex.map(lambda it: _safe(kalshi_history, it, hist_days, now), pre) if x]
        items += pre
        status["kalshi"] = {"status": "ok", "candidates": len(kc), "events": len(ks)}
    except Exception as e:  # noqa: BLE001
        status["kalshi"] = {"status": "failed", "error": str(e)[:300]}
    # Polymarket
    try:
        pc = poly_candidates(now)
        ps = [x for x in (_safe(poly_item, g, e, now) for g, e in pc) if x]
        items += ps
        status["polymarket"] = {"status": "ok", "candidates": len(pc), "events": len(ps)}
    except Exception as e:  # noqa: BLE001
        status["polymarket"] = {"status": "failed", "error": str(e)[:300]}
    # merge cross-venue duplicates, rank, trim
    merged, byk = [], {}
    items = [it for it in items if it["id"] not in pin_ids]
    for it in items:
        k = _merge_key(it)
        if k and k in byk:
            byk[k]["venues"].append(it); continue
        rec = {"key": k or f"{it['venue']}:{it['id']}", "group": it["group"], "venues": [it]}
        if k:
            byk[k] = rec
        merged.append(rec)
    for r in merged:
        r["vol7d"] = sum(v.get("vol7d") or 0 for v in r["venues"])
        r["oi"] = sum(v.get("oi") or 0 for v in r["venues"])
        r["venues"].sort(key=lambda v: v["venue"] != "Kalshi")
        r["title"] = r["venues"][0]["title"]
    merged.sort(key=lambda r: (-r["vol7d"], -r["oi"]))
    top = merged[:top_n]
    for i, r in enumerate(top):
        for v in r["venues"]:
            if v["venue"] == "Polymarket" and i < n_charts:
                _safe(poly_history, v, hist_days)
            _trim(v)
            for o in v["outcomes"]:
                if i >= n_charts:
                    o.pop("hist", None)
                o.pop("token", None); o.pop("last", None)
        r["rank"] = i + 1
        r["chart"] = i < n_charts
    return {"generated_at": now.isoformat(timespec="seconds"), "items": top, "pinned": pins, "sources": status,
            "universe": {"ranked": len(merged)}, "ranking_note": cfg.get("ranking_note")}


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # noqa: BLE001
        print(f"  ! {fn.__name__}: {str(e)[:160]}")
        return None


if __name__ == "__main__":
    t0 = time.time()
    r = build({"top_n": 12})
    print(json.dumps(r["sources"]), round(time.time() - t0, 1), "s")
    for it in r["items"]:
        print(f"{it['rank']:>2} {it['group']:<12} {it['vol7d']/1e3:>8.0f}k  {it['title'][:60]:<60} " + " | ".join(f"{v['venue']}: " + ", ".join(f"{o['label']} {o['p']*100:.0f}%" for o in v["outcomes"][:4]) for v in it["venues"]))

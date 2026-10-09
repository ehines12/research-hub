"""Shared calculations for config-driven dashboards.

Ported unchanged from the Financials Dashboard (ehines12/financials-dashboard, fetch_data.py) so the
H.8 / H.6 views that moved here compute exactly as before:
  yoy (on-or-before 1Y lookback, 3-day tolerance, >=360 days), share, contribution to YoY (pp),
  sums / splices on exact date matches, and 1W/1M/3M/1Y changes vs the observation on or before
  each lookback date (bp for % series, relative % for levels, plain difference for pts).
"""
import calendar
import datetime as dt


def d(s):
    return dt.date.fromisoformat(s)


def value_on_or_before(obs, target):
    lo, hi, ans = 0, len(obs) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if d(obs[mid][0]) <= target:
            ans = obs[mid]; lo = mid + 1
        else:
            hi = mid - 1
    return ans


def minus_years(date, n=1):
    try:
        return date.replace(year=date.year - n)
    except ValueError:
        return date.replace(year=date.year - n, day=28)


def minus_months(date, n=1):
    y, m = divmod(date.year * 12 + date.month - 1 - n, 12)
    m += 1
    return date.replace(year=y, month=m, day=min(date.day, calendar.monthrange(y, m)[1]))


def yoy(obs, tol_days=3):
    out = []
    for date_s, v in obs:
        prior = value_on_or_before(obs, minus_years(d(date_s)) + dt.timedelta(days=tol_days))
        if prior and prior[1] and (d(date_s) - d(prior[0])).days >= 360:
            out.append([date_s, round((v / prior[1] - 1) * 100, 3)])
    return out


def combine(fn, *series_list):
    maps = [dict(x) for x in series_list]
    if not maps or any(not m for m in maps):
        return []
    dates = sorted(set.intersection(*(set(m) for m in maps)))
    out = []
    for k in dates:
        v = fn(*(m[k] for m in maps))
        if v is not None:
            out.append([k, round(v, 4)])
    return out


def share(a, b):
    return combine(lambda x, y: (x / y * 100) if y else None, a, b)


def contribution(comp, total, tol_days=3):
    tmap = dict(total)
    out = []
    for date_s, v in comp:
        prior = value_on_or_before(comp, minus_years(d(date_s)) + dt.timedelta(days=tol_days))
        if not prior or (d(date_s) - d(prior[0])).days < 360:
            continue
        tp = tmap.get(prior[0])
        if tp:
            out.append([date_s, round((v - prior[1]) / tp * 100, 3)])
    return out


def splice(pre, post):
    """pre-series values before post's first date, then post (e.g. H.6 savings+OCD -> MDLM in May 2020)."""
    if not post:
        return []
    first = post[0][0]
    return [list(o) for o in pre if o[0] < first] + [list(o) for o in post]


PERIOD_DAYS = {"Daily": 1, "Weekly": 7, "Semi-monthly": 14, "Monthly": 28, "Quarterly": 90}
HORIZONS = [("1w", 7), ("1m", 30), ("3m", 91), ("1y", 365)]


def lookback(date, h):
    return {"1w": date - dt.timedelta(days=7), "1m": minus_months(date, 1),
            "3m": minus_months(date, 3), "1y": minus_years(date)}[h]


def change(obs, unit, h, freq):
    hdays = dict(HORIZONS)[h]
    latest = obs[-1]
    if hdays < PERIOD_DAYS.get(freq, 1):
        return None
    prior = value_on_or_before(obs, lookback(d(latest[0]), h))
    if not prior or prior[0] == latest[0]:
        return None
    a, b = latest[1], prior[1]
    if unit == "bp":
        val = (a - b) * 100
    elif unit == "pct":
        val = (a / b - 1) * 100 if b else None
    else:
        val = a - b
    return {"value": None if val is None else round(val, 3), "vs_date": prior[0], "vs_value": b}


def fmt_level(v, units):
    if v is None:
        return ""
    if units == "%":
        return f"{v:.2f}%"
    if units == "pp":
        return f"{v:+.2f} pp"
    if units == "$bn":
        return f"${v:,.2f}bn" if abs(v) < 100 else f"${v:,.1f}bn"
    return f"{v:,.2f}"


def fmt_change(c, unit):
    if not c or c.get("value") is None:
        return "–"
    v = c["value"]
    sign = "+" if v > 0 else ("−" if v < 0 else "±")
    a = abs(v)
    if unit == "bp":
        return f"{sign}{a:,.0f} bp"
    if unit == "pct":
        return f"{sign}{a:.2f}%"
    return f"{sign}{a:.2f}"


UNIT_LABEL = {"bp": "bp", "pct": "% chg", "pts": "pts"}


def derive(op, spec, get):
    """Evaluate one derived-series spec from config. get(key) -> obs list."""
    if op == "yoy":
        return yoy(get(spec["of"]))
    if op == "share":
        return share(get(spec["num"]), get(spec["den"]))
    if op == "contribution":
        return contribution(get(spec["comp"]), get(spec["total"]))
    if op == "sum":
        return combine(lambda *xs: sum(xs), *[get(k) for k in spec["of"]])
    if op == "splice":
        return splice(get(spec["pre"]), get(spec["post"]))
    raise ValueError(f"unknown derived op {op}")


def inputs_of(spec):
    out = []
    for f in ("of", "num", "den", "comp", "total", "pre", "post"):
        v = spec.get(f)
        if isinstance(v, list):
            out += v
        elif v:
            out.append(v)
    return out


# ---- quarterly averages (bank-analyst convention: quarter-average balances) ----
def qkey(date):
    dd = d(date)
    return dd.year, (dd.month - 1) // 3 + 1


def q_end(y, q):
    import datetime as _dt
    return (_dt.date(y + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - _dt.timedelta(days=1))


def quarter_averages(obs, freq):
    """{(y, q): {"avg", "n", "complete", "first", "last"}} from weekly/monthly obs (dated by FRED obs date:
    week-ending Wednesday for H.8, first of month for H.6). Complete = the quarter's last weekly obs (dated
    within 6 days of quarter end) or its 3rd month is present."""
    out = {}
    for t, v in obs:
        if v is None:
            continue
        k = qkey(t)
        r = out.setdefault(k, {"sum": 0.0, "n": 0, "first": t, "last": t, "months": set()})
        r["sum"] += v; r["n"] += 1; r["first"] = min(r["first"], t)
        if t >= r["last"]:
            r["last"], r["eop"] = t, v  # end-of-period = latest obs dated on/before quarter-end
        r["months"].add(d(t).month)
    for (y, q), r in out.items():
        end = q_end(y, q)
        r["complete"] = (len(r["months"]) == 3) if freq == "Monthly" else ((end - d(r["last"])).days <= 6)
        r["avg"] = r["sum"] / r["n"]
        del r["sum"], r["months"]
    return out

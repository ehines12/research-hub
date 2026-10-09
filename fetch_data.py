#!/usr/bin/env python3
"""Pull FRED series for every live dashboard in config/hub.json into data/<dashboard>.json.

Source: FRED public fredgraph CSV endpoint (no API key). Fallback: ALFRED graph CSV.
No numbers are ever synthesized: if a series cannot be fetched, the last good copy on
disk is kept and flagged stale; if none exists, the series is marked failed.

Usage:  python3 fetch_data.py            # all live dashboards
        python3 fetch_data.py macro      # one dashboard
"""
import csv, io, json, sys, time, shutil, subprocess, datetime as dt, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
SOURCES = [
    ("FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}"),
    ("ALFRED", "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={id}"),
]
UA = {"User-Agent": "Mozilla/5.0 (research-hub data refresh)"}


def http_csv(url, tries=3):
    """curl is the primary transport (FRED's edge stalls Python's TLS client); urllib is a fallback."""
    last = None
    for i in range(tries):
        try:
            if shutil.which("curl"):
                r = subprocess.run(["curl", "-sSfL", "--max-time", "60", url], capture_output=True, text=True)
                if r.returncode == 0 and r.stdout:
                    return r.stdout
                raise RuntimeError(f"curl exit {r.returncode}: {r.stderr.strip()[:200]}")
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise last


def parse(text, sid):
    rdr = csv.reader(io.StringIO(text))
    header = next(rdr)
    if len(header) < 2 or "date" not in header[0].lower():
        raise ValueError(f"unexpected CSV header {header[:3]}")
    obs = []
    for row in rdr:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            obs.append((row[0], float(row[1])))
        except ValueError:
            continue
    if not obs:
        raise ValueError("no observations")
    return obs


def fetch(sid):
    errs = []
    for name, tmpl in SOURCES:
        try:
            return name, tmpl.format(id=sid), parse(http_csv(tmpl.format(id=sid)), sid)
        except Exception as e:
            errs.append(f"{name}: {e}")
    raise RuntimeError("; ".join(errs))


GDPNOW_PAGE = "https://www.atlantafed.org/cqer/research/gdpnow"
GDPNOW_XLSX = ("https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents/research-and-data/"
               "data/gdpnow/GDPTrackingModelDataAndForecasts.xlsx")


def _qlabel(d):
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def fetch_gdpnow():
    """Atlanta Fed GDPNow daily nowcast history from its public tracking workbook.
    Returns (source, url, [(date, value)], {date: {"target": "Q3 2026", "release": "..."}}).
    Finished quarters: TrackingDeepArchives + TrackingArchives ('GDP Nowcast' column).
    Current quarter: CurrentQtrEvolution (Date / Major Releases / GDP* column triplets)."""
    import openpyxl, re, tempfile, os
    fd, path = tempfile.mkstemp(suffix=".xlsx"); os.close(fd)
    try:
        r = subprocess.run(["curl", "-sSfL", "--max-time", "120", "-o", path, GDPNOW_XLSX], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"curl exit {r.returncode}: {r.stderr.strip()[:200]}")
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        pts = {}  # date -> (value, target_quarter_end, release)
        for name in ("TrackingDeepArchives", "TrackingArchives"):
            rows = wb[name].iter_rows(values_only=True)
            hdr = next(rows)
            gi = [i for i, c in enumerate(hdr) if c and str(c).strip().lower() == "gdp nowcast"]
            if not gi:
                raise ValueError(f"{name}: no 'GDP Nowcast' column")
            for row in rows:
                d, q, v = row[0], row[1], row[gi[0]]
                if hasattr(d, "year") and hasattr(q, "year") and isinstance(v, (int, float)):
                    if d.date() not in pts or q.date() > pts[d.date()][1]:
                        pts[d.date()] = (float(v), q.date(), None)
        title = next(wb["TrackingHistory"].iter_rows(min_row=2, max_row=2, values_only=True))[0] or ""
        m = re.search(r"(\d{4})\s*q\s*(\d)", str(title), re.I)
        if not m:
            raise ValueError(f"cannot find current quarter in TrackingHistory title {title!r}")
        y, qn = int(m.group(1)), int(m.group(2))
        cur_q = dt.date(y, 3 * qn, 31 if qn in (1, 4) else 30)
        rows = list(wb["CurrentQtrEvolution"].iter_rows(values_only=True))
        if not rows or "date" not in str(rows[0][0]).lower():
            raise ValueError("CurrentQtrEvolution layout changed")
        n_cur = 0
        for row in rows[1:]:
            for b in range(0, len(row) - 2, 3):
                d, lab, v = row[b], row[b + 1], row[b + 2]
                if hasattr(d, "year") and isinstance(v, (int, float)):
                    pts[d.date()] = (float(v), cur_q, str(lab).strip() if lab else None); n_cur += 1
        if n_cur == 0:
            raise ValueError("no current-quarter nowcasts found")
    finally:
        os.unlink(path)
    dates = sorted(pts)
    obs = [(d.isoformat(), pts[d][0]) for d in dates]
    meta = {d.isoformat(): {"target": _qlabel(pts[d][1]), **({"release": pts[d][2]} if pts[d][2] else {})} for d in dates}
    return "Atlanta Fed", GDPNOW_XLSX, obs, meta


def _fetch_series(s):
    if s.get("source") == "gdpnow":
        return fetch_gdpnow()
    return fetch(s["fred"]) + (None,)


def _safe_fetch(spec):
    try:
        return _fetch_series(spec)
    except Exception as e:
        return e


def d(s):
    return dt.date.fromisoformat(s)


def transform(obs, how):
    if how == "level":
        return obs
    if how == "div1000":
        return [(t, v / 1000.0) for t, v in obs]
    if how == "diff":
        return [(obs[i][0], obs[i][1] - obs[i - 1][1]) for i in range(1, len(obs))]
    if how == "yoy":
        idx = {t: v for t, v in obs}
        out = []
        for t, v in obs:
            dd = d(t)
            try:
                prev = idx.get(dd.replace(year=dd.year - 1).isoformat())
            except ValueError:
                prev = None
            if prev:
                out.append((t, (v / prev - 1) * 100.0))
        return out
    raise ValueError(f"unknown transform {how}")


def year_ago(obs):
    """Observation closest to (and not after) one year before the latest."""
    target = d(obs[-1][0]).replace(year=d(obs[-1][0]).year - 1) if not (d(obs[-1][0]).month == 2 and d(obs[-1][0]).day == 29) else d(obs[-1][0]) - dt.timedelta(days=365)
    cand = [o for o in obs if d(o[0]) <= target]
    return cand[-1] if cand else None


def run_dashboard(cfg_path):
    cfg = json.loads((ROOT / cfg_path).read_text())
    out_path = DATA / f"{cfg['id']}.json"
    prev = json.loads(out_path.read_text()) if out_path.exists() else {"series": {}}
    now = dt.datetime.now(dt.timezone.utc)
    result = {"id": cfg["id"], "config": cfg, "updated_at": now.isoformat(timespec="seconds"), "series": {}}
    with ThreadPoolExecutor(max_workers=6) as ex:
        fetched = dict(zip([s["key"] for s in cfg["series"]],
                           ex.map(_safe_fetch, cfg["series"])))
    for s in cfg["series"]:
        rec = {k: v for k, v in s.items()}
        try:
            res = fetched[s["key"]]
            if isinstance(res, Exception):
                raise res
            src, url, raw, meta = res
            obs = [(t, round(v, 4)) for t, v in transform(raw, s["transform"])]
            if meta:
                rec["obs_meta"] = {t: meta[t] for t, _ in obs[-400:] if t in meta}
            rec.update(status="ok", source=src, source_url=url, fetched_at=now.isoformat(timespec="seconds"),
                       raw_latest={"date": raw[-1][0], "value": raw[-1][1]}, obs=obs)
        except Exception as e:
            old = prev.get("series", {}).get(s["key"])
            if old and old.get("obs"):
                rec.update(old)
                rec.update(status="stale", error=str(e))
            else:
                rec.update(status="failed", error=str(e), obs=[])
        if rec["obs"]:
            o = rec["obs"]
            rec["latest"] = {"date": o[-1][0], "value": o[-1][1]}
            rec["prior"] = {"date": o[-2][0], "value": o[-2][1]} if len(o) > 1 else None
            ya = year_ago(o)
            rec["year_ago"] = {"date": ya[0], "value": ya[1]} if ya and not s.get("no_yoy") else None
            om = rec.get("obs_meta")
            if om and o[-1][0] in om:
                # nowcast-style series: prior = previous estimate for the SAME target quarter
                rec["latest"].update(om[o[-1][0]])
                tgt = om[o[-1][0]].get("target")
                same = [x for x in o[:-1] if om.get(x[0], {}).get("target") == tgt]
                rec["prior"] = {"date": same[-1][0], "value": same[-1][1], **om[same[-1][0]]} if same else None
        result["series"][s["key"]] = rec
        st = rec["status"]
        lt = rec.get("latest") or {}
        print(f"  {s['fred']:<16} {st:<7} {lt.get('date','-'):<11} {lt.get('value','')}  {rec.get('error','')}")
    DATA.mkdir(exist_ok=True)
    # Only rewrite the (large) data file when the numbers or config actually changed, so the
    # scheduled job commits a big diff only on new FRED data. updated_at = last data change.
    changed = _strip(result) != _strip(prev)
    if changed:
        tmp = out_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, separators=(",", ":")))
        tmp.replace(out_path)
    else:
        result["updated_at"] = prev.get("updated_at", result["updated_at"])
    print(f"  -> {'data changed, wrote' if changed else 'no data change, kept'} {out_path.name}")
    return result


def _strip(doc):
    """Comparable view of a dashboard doc, without run timestamps."""
    doc = json.loads(json.dumps(doc))  # normalize tuples -> lists
    return {"config": doc.get("config"),
            "series": {k: {f: v for f, v in s.items() if f != "fetched_at"} for k, s in doc.get("series", {}).items()}}


def main():
    hub = json.loads((ROOT / "config/hub.json").read_text())
    only = set(sys.argv[1:])
    bad = 0
    status_path = DATA / "status.json"
    status = json.loads(status_path.read_text()) if status_path.exists() else {}
    status.setdefault("dashboards", {})
    for a in hub["areas"]:
        if a.get("status") != "live" or not a.get("dashboard"):
            continue
        if only and a["id"] not in only:
            continue
        print(f"[{a['id']}] {a['dashboard']}")
        r = run_dashboard(a["dashboard"])
        bad += sum(1 for s in r["series"].values() if s["status"] != "ok")
        status["dashboards"][a["id"]] = {
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "data_changed_at": r["updated_at"],
            "series": {k: {"fred": s["fred"], "status": s["status"], "latest": s.get("latest"), **({"error": s["error"]} if s.get("error") else {})}
                       for k, s in r["series"].items()}}
    status["checked_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    status["ok"] = bad == 0
    status_path.write_text(json.dumps(status, indent=1))
    (DATA / "hub.json").write_text(json.dumps(hub, indent=1))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

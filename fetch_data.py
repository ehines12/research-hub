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


def _safe_fetch(sid):
    try:
        return fetch(sid)
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
                           ex.map(lambda s: _safe_fetch(s["fred"]), cfg["series"])))
    for s in cfg["series"]:
        rec = {k: v for k, v in s.items()}
        try:
            res = fetched[s["key"]]
            if isinstance(res, Exception):
                raise res
            src, url, raw = res
            obs = [(t, round(v, 4)) for t, v in transform(raw, s["transform"])]
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
            rec["year_ago"] = {"date": ya[0], "value": ya[1]} if ya else None
        result["series"][s["key"]] = rec
        st = rec["status"]
        lt = rec.get("latest") or {}
        print(f"  {s['fred']:<16} {st:<7} {lt.get('date','-'):<11} {lt.get('value','')}  {rec.get('error','')}")
    DATA.mkdir(exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, separators=(",", ":")))
    tmp.replace(out_path)
    return result


def main():
    hub = json.loads((ROOT / "config/hub.json").read_text())
    only = set(sys.argv[1:])
    bad = 0
    for a in hub["areas"]:
        if a.get("status") != "live" or not a.get("dashboard"):
            continue
        if only and a["id"] not in only:
            continue
        print(f"[{a['id']}] {a['dashboard']}")
        r = run_dashboard(a["dashboard"])
        bad += sum(1 for s in r["series"].values() if s["status"] != "ok")
    (DATA / "hub.json").write_text(json.dumps(hub, indent=1))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

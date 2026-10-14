"""Real-time (as-first-published) vintages from ALFRED for the revised series used by the Bank Conditions index.
For each weekly grid date g (Fridays from 2012-01-06) we keep the vintage that was public on g-1 (Thursday),
so Friday-afternoon releases are never used early. Only the tail of each vintage that the component rules need
is stored. Cache: data/alfred-vintages.json.gz (committed); refreshes only fetch grid weeks not yet cached, and if
ALFRED is unreachable the current live FRED data is recorded as that week's vintage (marked 'live')."""
import datetime as dt, gzip, io, json, subprocess, time, csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CACHE = Path(__file__).resolve().parent / "data" / "alfred-vintages.json.gz"
TAIL = {"LLBSCBW027SBOG": 70, "LLBDCBW027SBOG": 70, "DPSSCBW027SBOG": 70, "LTDSCBW027SBOG": 70, "H8B3094NSMD": 70,
        "NFCI": 265, "STLFSI4": 265, "ICSA": 60, "CORALACBS": 6, "DRALACBS": 6}
URL = "https://alfred.stlouisfed.org/graph/alfredgraph.csv?id={ids}&vintage_date={vds}"
CHUNK = 12  # alfredgraph returns at most 12 vintages per request


def load():
    if CACHE.exists():
        return json.loads(gzip.decompress(CACHE.read_bytes()))
    return {k: {} for k in TAIL}


def save(c):
    CACHE.write_bytes(gzip.compress(json.dumps(c, separators=(",", ":")).encode(), 9))


def _get(sid, grid):
    vds = [(dt.date.fromisoformat(g) - dt.timedelta(days=1)).isoformat() for g in grid]
    url = URL.format(ids=",".join([sid] * len(vds)), vds=",".join(vds))
    last = None
    for i in range(4):
        r = subprocess.run(["curl", "-sSL", "--max-time", "180", "-w", "\n%{http_code}", url], capture_output=True, text=True)
        body, _, code = r.stdout.rpartition("\n")
        if r.returncode == 0 and code == "404":
            if len(grid) == 1:
                return {grid[0]: None}            # no vintage of this series existed yet
            h = len(grid) // 2                    # chunk may straddle the series' first vintage: split
            return {**_get(sid, grid[:h]), **_get(sid, grid[h:])}
        if r.returncode == 0 and code == "200":
            break
        last = f"curl {r.returncode} http {code} {r.stderr.strip()[:100]}"; time.sleep(5 * (i + 1))
    else:
        raise RuntimeError(f"ALFRED {sid}: {last}")
    r = type("R", (), {"stdout": body})
    if not r.stdout.strip():
        return {g: None for g in grid}          # no vintage existed yet for any of these dates
    rows = list(csv.reader(io.StringIO(r.stdout)))
    hdr = rows[0][1:]
    out = {g: None for g in grid}
    for j, col in enumerate(hdr):
        obs = [(row[0], float(row[j + 1])) for row in rows[1:] if row[j + 1] not in ("", ".")]
        if not obs:
            continue
        vd = col.rsplit("_", 1)[-1]
        tail = obs[-TAIL[sid]:]
        for g, v in zip(grid, vds):
            if v.replace("-", "") == vd:
                out[g] = tail
    return out


def update(grid, live=None, max_new=None):
    """Fill cache for grid weeks not yet cached. live: {sid: [(date, value)]} current FRED data, used as the
    vintage for the latest week if ALFRED fails."""
    c = load()
    st = {}
    jobs = []
    for sid in TAIL:
        c.setdefault(sid, {})
        miss = [g for g in grid if g not in c[sid]]
        if max_new:
            miss = miss[-max_new:]
        for i in range(0, len(miss), CHUNK):
            jobs.append((sid, miss[i:i + CHUNK]))

    def run(j):
        try:
            return j, _get(*j), None
        except Exception as e:  # noqa
            return j, None, str(e)
    with ThreadPoolExecutor(max_workers=4) as ex:
        for n, ((sid, ch), res, err) in enumerate(ex.map(run, jobs)):
            if n % 40 == 39:
                print(f"  ALFRED {n + 1}/{len(jobs)} chunks", flush=True); save(c)
            if err:
                st[sid] = {"status": "failed", "error": err[:200]}
                if live and live.get(sid) and ch[-1] == grid[-1]:
                    c[sid][grid[-1]] = {"live": [list(x) for x in live[sid][-TAIL[sid]:]]}
                continue
            for g, tail in res.items():
                c[sid][g] = tail
    save(c)
    return c, st


def series_at(c, sid, g):
    """vintage tail public at grid date g, or None (no vintage yet -> caller falls back to revised data)."""
    v = c.get(sid, {}).get(g)
    if isinstance(v, dict):
        v = v.get("live")
    return v

#!/usr/bin/env python3
"""Build research-hub.html: one self-contained file (CSS, JS, Chart.js and all data inlined)."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parent

def main():
    html = (ROOT / "index.html").read_text()
    hub = json.loads((ROOT / "data/hub.json").read_text())
    inline = {"hub": hub}
    st = ROOT / "data/status.json"
    if st.exists():
        inline["status"] = json.loads(st.read_text())
    for a in hub["areas"]:
        f = ROOT / "data" / f"{a['id']}.json"
        if a.get("status") == "live" and f.exists():
            inline[a["id"]] = json.loads(f.read_text())
    css = (ROOT / "assets/hub.css").read_text()
    html = html.replace('<link rel="stylesheet" href="assets/hub.css">', f"<style>\n{css}\n</style>")
    for src in ["vendor/chart.umd.min.js", "vendor/chartjs-adapter-date-fns.bundle.min.js", "assets/hub.js"]:
        js = (ROOT / src).read_text().replace("</script", "<\\/script")
        html = html.replace(f'<script src="{src}"></script>', f"<script>\n{js}\n</script>")
    data = json.dumps(inline, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("<!--INLINE_DATA-->", f"<script>window.HUB_INLINE={data};</script>")
    out = ROOT / "research-hub.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size/1e6:.2f} MB)")

if __name__ == "__main__":
    main()

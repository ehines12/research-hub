#!/usr/bin/env bash
# /workspace/research-hub IS the git working copy of github.com/ehines12/research-hub.
# Usage: ./publish.sh "commit message"  -> pulls Action data commits, refreshes, commits, pushes (Pages rebuilds).
set -euo pipefail
cd "$(dirname "$0")"
git pull --rebase --autostash -q origin main
./refresh.sh >/dev/null || echo "warning: some series stale/failed (see data/status.json)"
git add -A
git diff --cached --quiet && { echo "nothing to publish"; exit 0; }
git commit -q -m "${1:-Update research hub}"
git push -q origin main
echo "pushed $(git rev-parse --short HEAD); Pages will rebuild in ~1-2 min"

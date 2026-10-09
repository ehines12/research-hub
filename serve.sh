#!/usr/bin/env bash
# Serve the hub locally in the background. Usage: ./serve.sh [port]   (default 8077)
cd "$(dirname "$0")"; PORT="${1:-8077}"; mkdir -p logs
if ss -ltn | grep -q ":$PORT "; then echo "port $PORT already in use"; exit 0; fi
nohup python3 -m http.server "$PORT" --bind 0.0.0.0 > logs/server.log 2>&1 &
echo $! > logs/server.pid; echo "serving http://localhost:$PORT/ (pid $(cat logs/server.pid))"

#!/usr/bin/env bash
# Two laptop-hosted live-AI demo servers, each meant to sit behind its own HTTPS tunnel:
#   live    127.0.0.1:8090  every visitor gets a fresh private account
#   seeded  127.0.0.1:8091  open /?seed=sample to land in the fictional sample household
#
#   bash infra/demo/local-demo.sh [LIVE_PUBLIC_URL] [SEEDED_PUBLIC_URL]
#
# Re-run with the tunnel URLs once they exist: the API must trust the browser's Origin.
# Microsoft dev tunnels rewrite Origin to http://localhost:<port>, so that is trusted too.
# The OpenAI key comes from the repo .env (gitignored). The regular dev stack is untouched.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../.."

grep -qE '^OPENAI_API_KEY=sk-' .env || { echo "error: put OPENAI_API_KEY=sk-... in .env" >&2; exit 1; }
mkdir -p var/demo

compose() {
  local name=$1
  shift
  docker compose -p "adapt-demo-$name" --env-file "var/demo/$name.env" \
    -f docker-compose.yml -f docker-compose.local-demo.yml "$@"
}

# write_env NAME WEB_PORT API_PORT PG_PORT REDIS_PORT [PUBLIC_URL]
write_env() {
  local url="${6:-http://127.0.0.1:$2}"
  url="${url%/}"
  cat >"var/demo/$1.env" <<EOF
ADAPT_ENV=development
FRONTEND_HOST_PORT=$2
BACKEND_HOST_PORT=$3
POSTGRES_HOST_PORT=$4
REDIS_HOST_PORT=$5
PUBLIC_BASE_URL=$url
CORS_ORIGINS=$url,http://localhost:$2
DEMO_MODE=false
VITE_DATA_MODE=live
VITE_SHOW_DEV_BADGE=false
EOF
}

check() {
  local name=$1 api=$2
  for _ in $(seq 1 90); do
    curl -fsS --max-time 3 "http://127.0.0.1:$api/api/health" >/dev/null 2>&1 && break
    sleep 2
  done
  compose "$name" exec -T backend python -c '
import json, sys, urllib.request
info = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/system/info"))
modes = {a["capability"]: a["mode"] for a in info["adapters"]}
offline = [c for c in ("llm", "embeddings", "ocr", "voice", "web_search") if modes.get(c) != "live"]
print("  " + ", ".join(f"{c}={m}" for c, m in sorted(modes.items())))
sys.exit(f"not live: {offline}" if offline else 0)
'
}

write_env live 8090 8110 55442 56389 "${1:-}"
write_env seeded 8091 8120 55452 56399 "${2:-}"

echo "==> Building images"
compose live build
for name in live seeded; do
  echo "==> Starting $name"
  compose "$name" up -d
done
echo "==> live:   http://127.0.0.1:8090"
check live 8110
echo "==> seeded: http://127.0.0.1:8091/?seed=sample"
check seeded 8120

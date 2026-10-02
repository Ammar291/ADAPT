#!/usr/bin/env bash
# Hosted ADAPT live demo: real OpenAI behind every AI capability, no deterministic adapters.
# Run as root on a fresh Ubuntu 22.04/24.04 VM (2+ vCPU, 4 GB RAM recommended):
#
#   git clone https://github.com/Ammar291/ADAPT.git /opt/adapt
#   bash /opt/adapt/infra/demo/setup-server.sh        # prompts for the OpenAI key (hidden)
#
# The key may also come from $OPENAI_API_KEY or stdin; it is stored only in /opt/adapt/.env
# (mode 600, gitignored). Re-running pulls main, keeps generated secrets and the stored key,
# and rebuilds. The URL defaults to https://<public-ip>.sslip.io; set ADAPT_DOMAIN to use
# your own domain (point its A record at this server first).
#
# Demo profile: ADAPT_ENV=development because production refuses demo sign-in, which is
# the only sign-in. Government actions stay preview-only, so nothing is ever filed.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$APP_DIR/.env"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.demo.yml)
LIVE_CAPABILITIES="llm embeddings ocr voice web_search"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

get_env() {
  [ -f "$ENV_FILE" ] || return 0
  grep -m1 "^$1=" "$ENV_FILE" | cut -d= -f2- | sed 's/[[:space:]]*#.*$//; s/[[:space:]]*$//' || true
}

# Replace KEY= in .env (dropping any inline comment), or append it.
set_env() {
  local tmp
  tmp="$(mktemp)"
  grep -v "^$1=" "$ENV_FILE" >"$tmp" || true
  printf '%s=%s\n' "$1" "$2" >>"$tmp"
  cat "$tmp" >"$ENV_FILE"
  rm -f "$tmp"
}

[ "$(id -u)" -eq 0 ] || die "run as root (sudo bash $0)"
cd "$APP_DIR"

# --- OpenAI key first, before any other command can read stdin ------------------------
key="${OPENAI_API_KEY:-$(get_env OPENAI_API_KEY)}"
if [ -z "$key" ]; then
  if [ -t 0 ]; then
    read -rsp "OpenAI API key (input hidden): " key
    echo
  else
    IFS= read -r key || true
  fi
fi
key="$(printf '%s' "$key" | tr -d '[:space:]')"
[[ $key == sk-* ]] || die "an OpenAI API key (sk-...) is required"

# --- host -----------------------------------------------------------------------------
mem_kb="$(awk '/MemTotal/ {print $2}' /proc/meminfo)"
if [ "$mem_kb" -lt 3500000 ] && ! swapon --show | grep -q .; then
  log "Adding 2 GB swap (the frontend build needs headroom on small VMs)"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >>/etc/fstab
fi

if ! command -v docker >/dev/null 2>&1; then
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

if [ -d .git ]; then
  log "Updating to the latest main"
  git pull --ff-only
fi

# --- configuration --------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  log "Creating .env with fresh secrets"
  install -m 600 .env.example "$ENV_FILE"
  set_env SESSION_SECRET "$(openssl rand -hex 32)"
  set_env DOCUMENT_ENCRYPTION_KEY "$(openssl rand -base64 32 | tr '+/' '-_')"
  set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  set_env APP_DB_PASSWORD "$(openssl rand -hex 24)"
fi
chmod 600 "$ENV_FILE"

domain="${ADAPT_DOMAIN:-$(get_env ADAPT_DOMAIN)}"
if [ -z "$domain" ]; then
  ip="$(curl -fsS4 --max-time 10 https://api.ipify.org || curl -fsS4 --max-time 10 https://ifconfig.me)"
  [ -n "$ip" ] || die "could not detect the public IP; set ADAPT_DOMAIN"
  domain="${ip//./-}.sslip.io"
fi

set_env OPENAI_API_KEY "$key"
set_env ADAPT_DOMAIN "$domain"
set_env PUBLIC_BASE_URL "https://$domain"
set_env CORS_ORIGINS "https://$domain"
set_env ADAPT_ENV development
set_env DEMO_AUTH_ENABLED true
set_env SESSION_COOKIE_SECURE true
for capability in $LIVE_CAPABILITIES; do
  set_env "ADAPTER_$(printf '%s' "$capability" | tr '[:lower:]' '[:upper:]')" live
done
set_env ADAPTER_ACTIONS auto
set_env INTERPRETER_MODE auto
set_env DEMO_MODE false
set_env VITE_DATA_MODE live
set_env VITE_SHOW_DEV_BADGE false

# --- run ------------------------------------------------------------------------------
log "Building and starting the stack (first build takes several minutes)"
"${COMPOSE[@]}" up -d --build --remove-orphans

log "Waiting for the API"
for _ in $(seq 1 90); do
  curl -fsS --max-time 3 http://127.0.0.1:8100/api/health >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS --max-time 3 http://127.0.0.1:8100/api/health >/dev/null || {
  "${COMPOSE[@]}" logs --tail=60 migrate backend
  die "the API did not become healthy"
}

log "Checking that every AI capability is live"
curl -fsS http://127.0.0.1:8100/api/system/info | LIVE_CAPABILITIES="$LIVE_CAPABILITIES" python3 -c '
import json, os, sys
modes = {a["capability"]: a["mode"] for a in json.load(sys.stdin)["adapters"]}
for name, mode in sorted(modes.items()):
    print(f"  {name:<11} {mode}")
offline = [c for c in os.environ["LIVE_CAPABILITIES"].split() if modes.get(c) != "live"]
sys.exit(f"not live: {offline}" if offline else 0)
'

log "Waiting for HTTPS on $domain (certificate issuance)"
for _ in $(seq 1 60); do
  curl -fsS --max-time 5 "https://$domain/api/health" >/dev/null 2>&1 && break
  sleep 3
done
if curl -fsS --max-time 5 "https://$domain/api/health" >/dev/null 2>&1; then
  log "Live demo ready: https://$domain"
else
  "${COMPOSE[@]}" logs --tail=40 caddy
  die "https://$domain is not reachable yet: open ports 80 and 443 in the cloud firewall"
fi
cat <<EOF

  Update:  cd $APP_DIR && bash infra/demo/setup-server.sh
  Logs:    cd $APP_DIR && ${COMPOSE[*]} logs -f backend worker
  Stop:    cd $APP_DIR && ${COMPOSE[*]} down
EOF

#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir/backend"
python_bin="${TALKDOCK_PYTHON:-python}"
export TELEMETRY_VERSION="${TELEMETRY_VERSION:-$(git -C "$repo_dir" rev-parse --short HEAD)}"
export TELEMETRY_SERVICE="${1:?Usage: run-service.sh api|push|construction|digest|replication}"
case "$1" in
  api) exec "$python_bin" -m waitress --listen="127.0.0.1:${TALKDOCK_API_PORT:-8002}" --threads="${TALKDOCK_HTTP_THREADS:-8}" --channel-timeout=180 configs.wsgi:application ;;
  push) exec "$python_bin" manage.py run_push_worker ;;
  construction) exec "$python_bin" manage.py run_construction_supervisor ;;
  digest) exec "$python_bin" manage.py run_digest_scheduler ;;
  replication) shift; exec "$python_bin" -u manage.py run_replication_worker "$@" ;;
  *) echo "Unknown service" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
for ((attempt=0; attempt<1800; attempt++)); do
    if [[ -S /tmp/hapatchy-dev/supervisor.sock && -x "$script_dir/../../.venv/bin/python" ]]; then
        exec "$script_dir/../../.venv/bin/python" "$script_dir/ha_control.py" wait --timeout 120
    fi
    if [[ -f /tmp/hapatchy-dev/service.pid ]]; then
        python3 "$script_dir/environment.py" --service-alive
    fi
    if ((attempt % 30 == 0)); then
        printf '%s\n' 'Waiting for environment bootstrap; HA HTTP readiness has a separate 120s budget.'
    fi
    sleep 1
done
printf '%s\n' 'Supervisor startup timed out; inspect container logs.' >&2
exit 1

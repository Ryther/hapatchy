#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bash "$script_dir/bootstrap.sh"
exec "$script_dir/../../.venv/bin/python" "$script_dir/ha_control.py" restart

#!/usr/bin/env bash
# fastest way to try zimreader on kubuntu without packaging it. just venv + pip + run.
# usage:  ./run-dev.sh [optional/path/to/file.zim]
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

# nudge pyside to use the kde platform theme so it follows your plasma light/dark colors
export QT_QPA_PLATFORMTHEME="${QT_QPA_PLATFORMTHEME:-kde}"

python -m zimreader "$@"

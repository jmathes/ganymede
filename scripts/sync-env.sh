#!/usr/bin/env bash
# Keep the local conda env "ganymede" and requirements.txt in sync.
#
#   scripts/sync-env.sh            install requirements.txt into the env
#   scripts/sync-env.sh freeze     write the env's installed packages to requirements.txt
#   scripts/sync-env.sh add PKG..  install PKG(s) into the env, then freeze
#
# The env is created on first use with the Python version in .python-version.
set -euo pipefail
cd "$(dirname "$0")/.."

ENV_NAME=ganymede
PY_VERSION=$(cat .python-version)

if ! conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; then
  conda create -y -q -n "$ENV_NAME" "python=$PY_VERSION"
fi
PIP=(conda run -n "$ENV_NAME" python -m pip)

freeze() {
  "${PIP[@]}" freeze | grep -vE '^(pip|setuptools|wheel)==' > requirements.txt
  echo "wrote requirements.txt ($(wc -l < requirements.txt) packages)"
}

case "${1:-install}" in
  install) "${PIP[@]}" install -q -r requirements.txt ;;
  freeze)  freeze ;;
  add)     shift; "${PIP[@]}" install -q "$@"; freeze ;;
  *)       echo "usage: $0 [install|freeze|add PKG...]" >&2; exit 2 ;;
esac

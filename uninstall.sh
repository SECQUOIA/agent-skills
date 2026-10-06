#!/usr/bin/env bash
# Manage the complete skill set; --help documents roots and hook options.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$REPO_DIR/scripts/manage_installation.py" uninstall "$@"

#!/usr/bin/env bash
# Install the SECQUOIA agent skills into both Codex CLI and Claude Code.
#
# Usage:
#   ./install.sh            # symlink each skill into both tools (recommended; `git pull` then updates both)
#   ./install.sh --copy     # copy instead of symlink (use on Windows without symlink support)
#
# The skills reference each other by relative sibling paths, so they must be
# installed together. This script installs the whole set into each tool's skills dir.
set -euo pipefail

MODE="symlink"
[ "${1:-}" = "--copy" ] && MODE="copy"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/skills"

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
TARGETS=("$CODEX_HOME/skills" "$HOME/.claude/skills")

RUN="$(date +%s)"
for T in "${TARGETS[@]}"; do
  mkdir -p "$T"
  # Back up any real (non-symlink) dirs OUTSIDE the skills dir, so a leftover
  # copy can't be scanned as a duplicate-named skill.
  BACKUP="$(dirname "$T")/$(basename "$T")-backup-$RUN"
  echo "Installing into $T ($MODE):"
  for S in "$SRC"/*/; do
    name="$(basename "$S")"
    dest="$T/$name"
    if [ -L "$dest" ]; then
      rm "$dest"
    elif [ -e "$dest" ]; then
      mkdir -p "$BACKUP"
      mv "$dest" "$BACKUP/$name"
      echo "  ! existing $name moved to $BACKUP/"
    fi
    if [ "$MODE" = "copy" ]; then
      cp -R "$S" "$dest"
    else
      ln -s "${S%/}" "$dest"
    fi
    echo "  + $name"
  done
done

# Install the pre-push guard into this clone (blocks accidental pushes to main;
# this repo is private on a free plan, so GitHub branch protection is unavailable).
if [ -d "$REPO_DIR/.git" ] && [ -f "$REPO_DIR/hooks/pre-push" ]; then
  cp "$REPO_DIR/hooks/pre-push" "$REPO_DIR/.git/hooks/pre-push"
  chmod +x "$REPO_DIR/.git/hooks/pre-push"
  echo
  echo "Installed pre-push guard (blocks direct pushes to main; override with --no-verify)."
fi

echo
echo "Done. Start a fresh Codex/Claude session to pick up the skills."
echo "Update later with: git -C \"$REPO_DIR\" pull"

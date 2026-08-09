#!/usr/bin/env bash
# Install the SECQUOIA agent skills into both Codex CLI and Claude Code.
#
# Usage:
#   ./install.sh                         # symlink skills into both tools
#   ./install.sh --copy                  # copy skills instead of symlinking
#   ./install.sh --codex-hooks           # also install Codex encounter hooks in audit mode
#   ./install.sh --codex-hooks=enforce   # Codex encounter hooks in enforcement mode
#   ./install.sh --claude-hooks          # also install Claude Code encounter hooks in audit mode
#   ./install.sh --claude-hooks=enforce  # Claude Code encounter hooks in enforcement mode
#
# The skills reference each other by relative sibling paths, so they must be
# installed together. This script installs the whole set into each tool's skills dir.
set -euo pipefail

MODE="symlink"
CODEX_HOOKS_MODE=""
CLAUDE_HOOKS_MODE=""
for argument in "$@"; do
  case "$argument" in
    --copy)
      MODE="copy"
      ;;
    --codex-hooks)
      CODEX_HOOKS_MODE="audit"
      ;;
    --codex-hooks=audit|--codex-hooks=enforce)
      CODEX_HOOKS_MODE="${argument#*=}"
      ;;
    --claude-hooks)
      CLAUDE_HOOKS_MODE="audit"
      ;;
    --claude-hooks=audit|--claude-hooks=enforce)
      CLAUDE_HOOKS_MODE="${argument#*=}"
      ;;
    *)
      echo "Unknown option: $argument" >&2
      exit 2
      ;;
  esac
done

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
      if [ "$name" = "apply-conversation-lessons" ]; then
        git -C "$REPO_DIR" rev-parse HEAD > "$dest/scripts/.installed-revision"
      fi
    else
      ln -s "${S%/}" "$dest"
    fi
    echo "  + $name"
  done
done

if [ -n "$CODEX_HOOKS_MODE" ]; then
  ENCOUNTER_SCRIPT="$CODEX_HOME/skills/apply-conversation-lessons/scripts/encounter_ledger.py"
  python3 "$ENCOUNTER_SCRIPT" install-codex-hooks \
    --codex-home "$CODEX_HOME" \
    --script "$ENCOUNTER_SCRIPT" \
    --mode "$CODEX_HOOKS_MODE"
fi

if [ -n "$CLAUDE_HOOKS_MODE" ]; then
  CLAUDE_ENCOUNTER_SCRIPT="$HOME/.claude/skills/apply-conversation-lessons/scripts/encounter_ledger.py"
  python3 "$CLAUDE_ENCOUNTER_SCRIPT" install-claude-hooks \
    --settings-path "$HOME/.claude/settings.json" \
    --script "$CLAUDE_ENCOUNTER_SCRIPT" \
    --mode "$CLAUDE_HOOKS_MODE"
fi

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
if [ -n "$CODEX_HOOKS_MODE" ]; then
  echo "In Codex, open /hooks once to review and trust the installed hook definition."
fi
if [ -n "$CLAUDE_HOOKS_MODE" ]; then
  echo "Claude Code reads hooks from settings.json at session start; restart open sessions to pick them up."
fi

#!/usr/bin/env bash
# cwo (claude-work-orchestrator) installer
#
# Installs two things:
#   1) a skill link in ~/.claude/skills  (so Claude Code discovers the skill)
#   2) a `cwo` command on your PATH       (symlink to scripts/cwo.py)
#
# Usage:
#   ./install.sh                 install (idempotent)
#   ./install.sh --bindir DIR    install the command into DIR
#   ./install.sh --uninstall     remove the skill link and the command
#   ./install.sh --help          show this help
#
# Requirements: python3 >= 3.9 (stdlib only), git.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
SKILL_NAME="$(basename "$SKILL_DIR")"
SKILLS_LINK="$HOME/.claude/skills/$SKILL_NAME"
CWO_SCRIPT="$SKILL_DIR/scripts/cwo.py"

BINDIR=""
UNINSTALL=0
while [ $# -gt 0 ]; do
  case "$1" in
    --uninstall) UNINSTALL=1 ;;
    --bindir)    BINDIR="${2:-}"; shift ;;
    -h|--help)   awk 'NR==1{next} /^#/{sub(/^# ?/,"");print;next} {exit}' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
  shift
done

info() { printf '  %s\n' "$*"; }
on_path() { case ":$PATH:" in *":$1:"*) return 0 ;; *) return 1 ;; esac; }

# ---- uninstall ------------------------------------------------------------
if [ "$UNINSTALL" -eq 1 ]; then
  [ -L "$SKILLS_LINK" ] && rm -f "$SKILLS_LINK" && info "removed skill link: $SKILLS_LINK"
  for d in "$HOME/.local/bin" /usr/local/bin; do
    [ -L "$d/cwo" ] && rm -f "$d/cwo" && info "removed command: $d/cwo"
  done
  echo "uninstalled."
  exit 0
fi

# ---- python check ---------------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 not found on PATH" >&2; exit 1
fi
PYV="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 9) else 1)'; then
  echo "error: Python 3.9+ required (found $PYV)" >&2; exit 1
fi
info "python3: $PYV ($(command -v python3))"

# ---- 1) skill link --------------------------------------------------------
mkdir -p "$HOME/.claude/skills"
ln -sfn "$SKILL_DIR" "$SKILLS_LINK"
info "skill linked: $SKILLS_LINK"

# ---- 2) cwo command -------------------------------------------------------
chmod +x "$CWO_SCRIPT"
if [ -z "$BINDIR" ]; then
  if on_path "$HOME/.local/bin"; then BINDIR="$HOME/.local/bin"
  elif [ -w /usr/local/bin ] && on_path /usr/local/bin; then BINDIR="/usr/local/bin"
  else BINDIR="$HOME/.local/bin"; fi
fi
mkdir -p "$BINDIR"
ln -sfn "$CWO_SCRIPT" "$BINDIR/cwo"
info "command installed: $BINDIR/cwo"

if ! on_path "$BINDIR"; then
  echo
  echo "  NOTE: $BINDIR is not on your PATH. Add to your shell rc, then restart the shell:"
  echo "        export PATH=\"$BINDIR:\$PATH\""
fi

# ---- 3) verify ------------------------------------------------------------
if "$BINDIR/cwo" --help >/dev/null 2>&1; then
  info "verified: cwo responds"
else
  echo "  WARN: cwo did not run cleanly — check your python3." >&2
fi

echo
echo "Done. Try:"
echo "  cwo --root <your-project> init"
echo "  cwo --root <your-project> serve --port 8787   # web dashboard"

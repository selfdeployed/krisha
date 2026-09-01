#!/bin/bash

# Ralph Wiggum Loop for SentInflation — test-and-improve every capability.
# Runs the main `claude` (Opus) headless, one plan.md task per iteration, offline only.
#
# Usage: ./ralpheasy/ralph.sh [iterations]   (default 40)

set -uo pipefail

MAX_ITERATIONS="${1:-40}"
MODEL="${RALPH_MODEL:-claude-sonnet-5}"

# Resolve repo root = parent of this script's dir, and run there so the agent
# edits services/, frontend/, etc. directly.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# Find a REAL python for the stream formatter. On Windows, `command -v python`
# often hits the Microsoft Store alias stub (WindowsApps\python.exe) which just
# prints an install nag — so prefer the repo venv and verify each candidate
# actually executes before trusting it.
PY=""
for cand in "$REPO_ROOT/.venv/Scripts/python.exe" "$(command -v python3 2>/dev/null)" "$(command -v python 2>/dev/null)"; do
  if [ -n "$cand" ] && "$cand" -c "pass" >/dev/null 2>&1; then
    PY="$cand"
    break
  fi
done

PROMPT_FILE="$SCRIPT_DIR/PROMPT.md"
PLAN_FILE="$SCRIPT_DIR/plan.md"
FORMAT_SCRIPT="$SCRIPT_DIR/format-stream.py"
OUTPUT_FILE="/tmp/ralph_sentinflation_output.txt"

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Error: PROMPT.md not found at $PROMPT_FILE"
  exit 1
fi

echo "========================================"
echo "  Ralph Wiggum Loop"
echo "  Project: SentInflation methodology upgrade"
echo "========================================"
echo "Model:          $MODEL"
echo "Max Iterations: $MAX_ITERATIONS"
echo "Repo root:      $REPO_ROOT"
echo "Prompt:         $PROMPT_FILE"
echo "Plan:           $PLAN_FILE"
echo "========================================"
echo ""

for ((i=1; i<=MAX_ITERATIONS; i++)); do
  echo "========================================"
  echo "Iteration $i of $MAX_ITERATIONS — $(date)"
  echo "========================================"

  # Offline-only env guard: empty TELEGRAM_API_ID in .env breaks Settings()
  # import; export a dummy so pytest collection always works.
  export TELEGRAM_API_ID="${TELEGRAM_API_ID:-0}"

  if [ -f "$FORMAT_SCRIPT" ] && [ -n "$PY" ]; then
    claude -p "$(cat "$PROMPT_FILE")" --model "$MODEL" \
      --output-format stream-json --verbose \
      --dangerously-skip-permissions 2>&1 | tee "$OUTPUT_FILE" | "$PY" "$FORMAT_SCRIPT" || true
  else
    claude -p "$(cat "$PROMPT_FILE")" --model "$MODEL" \
      --output-format text \
      --dangerously-skip-permissions 2>&1 | tee "$OUTPUT_FILE" || true
  fi

  echo ""
  echo "Finished iteration $i at: $(date)"

  # NOTE: we do NOT grep the streamed output for the <promise>COMPLETE</promise>
  # sentinel — `claude -p "$(cat PROMPT.md)"` echoes the prompt (which contains
  # that literal string) back into the raw stream, causing a false positive on
  # the very first iteration. Completion is detected purely from the plan.md
  # tally below, which is deterministic and not subject to prompt echo.

  # Task tally from plan.md. NB: `grep -c` exits 1 (and would trigger a
  # `|| echo 0`, producing "0\n0") when there are zero matches — so capture the
  # single-line count directly and default empties to 0 with parameter expansion.
  if [ -f "$PLAN_FILE" ]; then
    false_count=$(grep -c '"passes": false' "$PLAN_FILE" 2>/dev/null); false_count=${false_count:-0}
    in_progress_count=$(grep -c '"passes": "in_progress"' "$PLAN_FILE" 2>/dev/null); in_progress_count=${in_progress_count:-0}
    true_count=$(grep -c '"passes": true' "$PLAN_FILE" 2>/dev/null); true_count=${true_count:-0}
    echo "Task status: $true_count done / $in_progress_count in-progress / $false_count remaining"

    if [ "$false_count" -eq 0 ] && [ "$in_progress_count" -eq 0 ]; then
      echo "========================================"
      echo "  ALL TASKS COMPLETE (tally) after $i iterations"
      echo "========================================"
      rm -f "$OUTPUT_FILE"
      exit 0
    fi
  fi

  echo "--- end iteration $i ---"
  echo ""
  sleep 2
done

echo "========================================"
echo "  MAX ITERATIONS REACHED ($MAX_ITERATIONS)"
echo "========================================"
rm -f "$OUTPUT_FILE"
exit 1

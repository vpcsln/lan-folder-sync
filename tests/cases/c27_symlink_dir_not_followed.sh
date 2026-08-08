#!/bin/bash
# Verified-safe port: os.walk(followlinks=False) — symlinked directories are
# not descended into; real directories are.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L/real" "$R"
printf 'inside\n' > "$L/real/inner.txt"
ln -s real "$L/linkdir"
run_sim --list --plain >"$CASE_DIR/out" 2>/dev/null || fail "list failed"
grep -q "real/inner.txt" "$CASE_DIR/out" || fail "real/inner.txt missing"
grep -q "linkdir" "$CASE_DIR/out" && fail "symlinked dir was followed"
exit 0

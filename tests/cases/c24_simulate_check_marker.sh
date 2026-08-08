#!/bin/bash
# F16: --check in simulate mode must say so ("simulated") instead of
# pretending a real connection was verified.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
run_sim --check >"$CASE_DIR/out" 2>&1; rc=$?
[[ $rc -eq 0 ]] || fail "rc=$rc"
grep -q "simulated" "$CASE_DIR/out" || fail "no simulated marker in: $(cat "$CASE_DIR/out")"
exit 0

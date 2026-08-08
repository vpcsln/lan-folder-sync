#!/bin/bash
# F7/F13: bare run without a terminal must exit 2 with a friendly message,
# no curses traceback.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/a.txt"
"$TOOL" --simulate-local "$L" --simulate-remote "$R" </dev/null >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?
[[ $rc -eq 2 ]] || fail "expected exit 2, got $rc"
assert_no_traceback "$CASE_DIR/err"
grep -qi "terminal" "$CASE_DIR/err" || fail "no friendly terminal message"
exit 0

#!/bin/bash
# F6/R7: a state directory that is a symlink must be refused with a clean
# error, not silently written through.
. "$ROOT/tests/lib.sh"
L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$CASE_DIR/real" "$L" "$R"
ln -s "$CASE_DIR/real" "$CASE_DIR/state"
LAN_SYNC_STATE_DIR="$CASE_DIR/state" "$TOOL" --simulate-local "$L" --simulate-remote "$R" \
    --list --plain >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?
[[ $rc -ne 0 ]] || fail "accepted symlinked state dir"
grep -q "symlink" "$CASE_DIR/err" || fail "no symlink error message"
assert_no_traceback "$CASE_DIR/err"
exit 0

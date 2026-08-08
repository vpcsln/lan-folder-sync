#!/bin/bash
# F5: '\r' (and other C0) filenames must be rejected at scan, never reach
# rsync, never appear in output; push must complete cleanly.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'cr\n' > "$(printf '%s/carr\rreturn.txt' "$L")"
printf 'esc\n' > "$(printf '%s/esc\x1b[31mRED\x1b[0m.txt' "$L")"
printf 'tab\n' > "$(printf '%s/tab\tname.txt' "$L")"
printf 'ok\n' > "$L/normal.txt"

run_sim --list --plain >"$CASE_DIR/out.txt" 2>"$CASE_DIR/err.txt" || fail "list failed"
grep -q "carr" "$CASE_DIR/out.txt" && fail "CR filename listed"
grep -q "RED" "$CASE_DIR/out.txt" && fail "ESC filename listed"
grep -q "tab" "$CASE_DIR/out.txt" && fail "tab filename listed"
grep -q "normal.txt" "$CASE_DIR/out.txt" || fail "normal.txt missing from list"
grep -q "skip local path (invalid)" "$STATE/log" || fail "no skip log entry"

run_sim --push >/dev/null 2>"$CASE_DIR/push.err" || fail "push failed"
assert_no_traceback "$CASE_DIR/push.err"
[[ -e "$R/normal.txt" ]] || fail "normal.txt not pushed"
[[ -e "$R/carr"* ]] && fail "CR file pushed"
exit 0

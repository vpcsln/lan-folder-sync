#!/bin/bash
# F3: malformed/tampered state.json must never crash the tool — bad entries
# are skipped with a log line, runs continue with exit 0.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/a.txt"

printf '{"a.txt": "garbage"}' > "$STATE/state.json"
run_sim --list --plain >"$CASE_DIR/out1" 2>"$CASE_DIR/err1"; rc=$?
[[ $rc -eq 0 ]] || fail "exit $rc with string entry"
assert_no_traceback "$CASE_DIR/err1"
grep -q "a.txt" "$CASE_DIR/out1" || fail "file not listed despite bad state entry"

printf '{"a.txt": {"l": "bogus", "r": [3, 1.0]}}' > "$STATE/state.json"
run_sim --list --plain >/dev/null 2>"$CASE_DIR/err2"; rc=$?
[[ $rc -eq 0 ]] || fail "exit $rc with bad l type"
assert_no_traceback "$CASE_DIR/err2"

printf '[1, 2, 3]' > "$STATE/state.json"
run_sim --list --plain >/dev/null 2>"$CASE_DIR/err3"; rc=$?
[[ $rc -eq 0 ]] || fail "exit $rc with array state"
assert_no_traceback "$CASE_DIR/err3"

printf '{"version": 99}' > "$STATE/state.json"
run_sim --list --plain >/dev/null 2>"$CASE_DIR/err4"; rc=$?
[[ $rc -eq 0 ]] || fail "exit $rc with unknown version"
assert_no_traceback "$CASE_DIR/err4"
grep -q "state" "$STATE/log" || fail "no state-validation log lines"
exit 0

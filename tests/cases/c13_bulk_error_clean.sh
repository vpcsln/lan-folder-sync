#!/bin/bash
# F7: bulk transfer failures must produce a clean "error:" message and exit 1,
# never a Python traceback; state must not record failed files.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/good.txt"
printf 'secret\n' > "$L/bad.txt"
chmod 000 "$L/bad.txt"

run_sim --push >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?
[[ $rc -eq 1 ]] || fail "expected exit 1, got $rc"
assert_no_traceback "$CASE_DIR/err"
grep -q "error:" "$CASE_DIR/err" || fail "no clean error message on stderr"
if [[ -e "$STATE/state.json" ]]; then
    grep -q "bad.txt" "$STATE/state.json" && fail "failed file recorded in state.json"
fi
chmod 644 "$L/bad.txt"
exit 0

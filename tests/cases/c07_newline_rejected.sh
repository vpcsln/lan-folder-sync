#!/bin/bash
# Verified-safe port: newline filenames are rejected at scan, logged, and
# never listed or transferred.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$(printf '%s/weird\nname.txt' "$L")"
run_sim --list --plain >"$CASE_DIR/out" 2>/dev/null || fail "list failed"
grep -q "weird" "$CASE_DIR/out" && fail "newline file listed"
grep -q "skip local path (invalid)" "$STATE/log" || fail "no skip log entry"
run_sim --push >/dev/null 2>&1 || fail "push failed"
[[ -z "$(ls -A "$R")" ]] || fail "newline file transferred"
exit 0

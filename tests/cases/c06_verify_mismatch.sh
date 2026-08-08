#!/bin/bash
# Verified-safe port: --verify detects equal mtime+size but different
# content and flags it as unsure + logs the mismatch.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'AAAA' > "$L/f.dat"
printf 'BBBB' > "$R/f.dat"
touch -d '2026-01-01 00:00:00' "$L/f.dat" "$R/f.dat"
run_sim --verify --list --plain >"$CASE_DIR/out" 2>/dev/null || fail "list failed"
grep -q "f.dat" "$CASE_DIR/out" || fail "content mismatch not flagged"
grep -q "content mismatch" "$STATE/log" || fail "no content-mismatch log"
exit 0

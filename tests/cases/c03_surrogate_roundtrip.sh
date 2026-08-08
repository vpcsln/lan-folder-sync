#!/bin/bash
# Verified-safe port: non-UTF-8 byte 0x94 in a filename round-trips
# byte-exact through scan -> transfer -> state.json -> re-classification.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'bytes\n' > "$(printf '%s/byte\x94name.txt' "$L")"
run_sim --push >/dev/null 2>&1 || fail "push failed"
find "$R" -type f -printf '%f\n' | od -c | grep -q "224" || fail "0x94 byte lost in transfer"
grep -q '\\udc94' "$STATE/state.json" || fail "state.json does not round-trip the surrogate"
run_sim --list --plain >"$CASE_DIR/out" 2>/dev/null || fail "list failed"
grep -q "byte" "$CASE_DIR/out" && fail "byte file not classified same after sync"
exit 0

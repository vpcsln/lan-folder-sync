#!/bin/bash
# F4: no raw ESC bytes may reach stdout from --list / --list --plain /
# --pull output, regardless of hostile filenames.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$(printf '%s/esc\x1b[31mRED\x1b[0m.txt' "$L")"
printf 'cr\n' > "$(printf '%s/carr\rreturn.txt' "$L")"

run_sim --list --plain >"$CASE_DIR/out1" 2>/dev/null || fail "list --plain failed"
if LC_ALL=C grep -q $'\x1b' "$CASE_DIR/out1"; then fail "ESC byte in --list --plain output"; fi

run_sim --list >"$CASE_DIR/out2" 2>/dev/null || fail "list failed"
if LC_ALL=C grep -q $'\x1b' "$CASE_DIR/out2"; then fail "ESC byte in --list output"; fi

run_sim --pull >"$CASE_DIR/out3" 2>/dev/null || fail "pull failed"
if LC_ALL=C grep -q $'\x1b' "$CASE_DIR/out3"; then fail "ESC byte in --pull output"; fi
exit 0

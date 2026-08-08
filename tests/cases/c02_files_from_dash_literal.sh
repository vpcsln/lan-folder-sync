#!/bin/bash
# Verified-safe port: leading-dash filenames (incl. bare "-" and "--inject")
# are literal names in --files-from and transfer byte-exact.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'dash\n' > "$L/-inject.txt"
printf 'dd\n' > "$L/--inject"
printf 'minus\n' > "$L/-"
run_sim --push >/dev/null 2>"$CASE_DIR/err" || fail "push failed"
assert_no_traceback "$CASE_DIR/err"
[[ -e "$R/-inject.txt" ]] || fail "-inject.txt not transferred"
[[ -e "$R/--inject" ]] || fail "--inject not transferred"
[[ -e "$R/-" ]] || fail "- not transferred"
[[ "$(cat "$R/-inject.txt")" == "dash" ]] || fail "content mismatch"
exit 0

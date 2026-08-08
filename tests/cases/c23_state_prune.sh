#!/bin/bash
# State growth: entries for files that no longer exist on EITHER side must
# be pruned from state.json on the next successful apply.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'a\n' > "$L/a.txt"
printf 'b\n' > "$L/b.txt"
run_sim --push >/dev/null 2>&1 || fail "first push"
grep -q '"a.txt"' "$STATE/state.json" || fail "a.txt missing from state"

rm -f "$L/a.txt" "$R/a.txt"
printf 'c\n' > "$L/c.txt"
run_sim --push >/dev/null 2>&1 || fail "second push"
grep -q '"a.txt"' "$STATE/state.json" && fail "pruned path a.txt still in state"
grep -q '"c.txt"' "$STATE/state.json" || fail "c.txt missing from state"
exit 0

#!/bin/bash
# F2: symlinks (to files, broken, to dirs) must be excluded from the scan;
# push must succeed, transfer only regular files, and never record a
# symlink in state.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/real.txt"
ln -s real.txt "$L/link.txt"
ln -s /nonexistent "$L/broken.txt"
mkdir -p "$L/realdir" && printf 'y\n' > "$L/realdir/inner.txt"
ln -s realdir "$L/linkdir"

run_sim --list --plain >"$CASE_DIR/out.txt" 2>/dev/null || fail "list failed"
grep -q "link.txt" "$CASE_DIR/out.txt" && fail "symlink-to-file listed"
grep -q "broken.txt" "$CASE_DIR/out.txt" && fail "broken symlink listed"
grep -q "linkdir" "$CASE_DIR/out.txt" && fail "symlinked dir listed"
grep -q "real.txt" "$CASE_DIR/out.txt" || fail "real.txt missing"
grep -q "realdir/inner.txt" "$CASE_DIR/out.txt" || fail "realdir/inner.txt missing"

run_sim --push >/dev/null 2>"$CASE_DIR/push.err" || fail "push failed"
assert_no_traceback "$CASE_DIR/push.err"
[[ -e "$R/real.txt" ]] || fail "real.txt not pushed"
[[ -e "$R/realdir/inner.txt" ]] || fail "inner.txt not pushed"
[[ -e "$R/link.txt" || -L "$R/link.txt" ]] && fail "symlink pushed to remote"
grep -q "link.txt" "$STATE/state.json" && fail "symlink recorded in state.json"
grep -q "broken.txt" "$STATE/state.json" && fail "broken symlink recorded in state.json"
exit 0

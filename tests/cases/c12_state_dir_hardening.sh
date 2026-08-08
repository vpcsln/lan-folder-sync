#!/bin/bash
# F6: state-dir hardening — pre-existing wrong perms are tightened to 0700;
# symlinked lock/log/state.json.tmp must be refused, never written through.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"

# 1) pre-created 0755 state dir gets tightened
mkdir -p "$CASE_DIR/s1" "$L" "$R"
chmod 755 "$CASE_DIR/s1"
LAN_SYNC_STATE_DIR="$CASE_DIR/s1" "$TOOL" --simulate-local "$L" --simulate-remote "$R" \
    --list --plain >/dev/null 2>&1 || fail "run with 0755 dir failed"
[[ "$(stat -c%a "$CASE_DIR/s1")" == "700" ]] \
    || fail "state dir not tightened to 0700 (got $(stat -c%a "$CASE_DIR/s1"))"

# 2) lock symlink: victim must not be truncated, run must fail cleanly
mkdir -p "$CASE_DIR/s2"; printf 'PRECIOUS\n' > "$CASE_DIR/victim.txt"
ln -s "$CASE_DIR/victim.txt" "$CASE_DIR/s2/lock"
LAN_SYNC_STATE_DIR="$CASE_DIR/s2" "$TOOL" --simulate-local "$L" --simulate-remote "$R" \
    --list --plain >/dev/null 2>"$CASE_DIR/err2"; rc=$?
[[ "$(cat "$CASE_DIR/victim.txt")" == "PRECIOUS" ]] || fail "victim truncated via lock symlink"
[[ $rc -ne 0 ]] || fail "tool accepted a symlinked lock file"
assert_no_traceback "$CASE_DIR/err2"

# 3) log symlink: victim must not receive log lines
mkdir -p "$CASE_DIR/s3" "$CASE_DIR/l2" "$CASE_DIR/r2"; printf 'KEEP\n' > "$CASE_DIR/victim3.txt"
ln -s "$CASE_DIR/victim3.txt" "$CASE_DIR/s3/log"
printf 'x\n' > "$(printf 'l2/bad\nname.txt')"
LAN_SYNC_STATE_DIR="$CASE_DIR/s3" "$TOOL" --simulate-local "$CASE_DIR/l2" --simulate-remote "$CASE_DIR/r2" \
    --list --plain >/dev/null 2>&1 || fail "run with log symlink failed"
[[ "$(cat "$CASE_DIR/victim3.txt")" == "KEEP" ]] || fail "log appended through symlink"

# 4) state.json.tmp symlink: state write must fail cleanly, victim untouched
mkdir -p "$CASE_DIR/s4" "$CASE_DIR/l5" "$CASE_DIR/r5"; printf 'KEEP2\n' > "$CASE_DIR/victim4.txt"
ln -s "$CASE_DIR/victim4.txt" "$CASE_DIR/s4/state.json.tmp"
printf 'new\n' > "$CASE_DIR/l5/f.txt"
LAN_SYNC_STATE_DIR="$CASE_DIR/s4" "$TOOL" --simulate-local "$CASE_DIR/l5" --simulate-remote "$CASE_DIR/r5" \
    --push >/dev/null 2>"$CASE_DIR/err4"; rc=$?
[[ "$(cat "$CASE_DIR/victim4.txt")" == "KEEP2" ]] || fail "state written through state.json.tmp symlink"
[[ ! -e "$CASE_DIR/s4/state.json" ]] || fail "state.json created despite symlink attack"
[[ $rc -ne 0 ]] || fail "save_state succeeded despite symlink attack"
assert_no_traceback "$CASE_DIR/err4"
exit 0

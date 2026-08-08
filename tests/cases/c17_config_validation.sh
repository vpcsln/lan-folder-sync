#!/bin/bash
# F9/F10: hostile config/env values (leading dash, control chars) must be
# rejected with a log entry and the tool must keep working with defaults.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/a.txt"

LAN_SYNC_HOST='-oProxyCommand=/bin/echo pwned' LAN_SYNC_STATE_DIR="$STATE" \
    "$TOOL" --simulate-local "$L" --simulate-remote "$R" --check \
    >"$CASE_DIR/out1" 2>"$CASE_DIR/err1"; rc=$?
[[ $rc -eq 0 ]] || fail "tool failed with hostile HOST env (rc=$rc)"
grep -q "connection OK" "$CASE_DIR/out1" || fail "no connection OK"
grep -q "config: invalid value for host" "$STATE/log" || fail "no config-validation log entry"

LAN_SYNC_HOST=$'evil\nhost' LAN_SYNC_STATE_DIR="$STATE" \
    "$TOOL" --simulate-local "$L" --simulate-remote "$R" --check \
    >"$CASE_DIR/out2" 2>"$CASE_DIR/err2"; rc=$?
[[ $rc -eq 0 ]] || fail "tool failed with newline HOST env (rc=$rc)"
assert_no_traceback "$CASE_DIR/err2"

# invalid remote_root (relative) must be rejected too
LAN_SYNC_REMOTE_ROOT='relative/path' LAN_SYNC_STATE_DIR="$STATE" \
    "$TOOL" --simulate-local "$L" --simulate-remote "$R" --check \
    >"$CASE_DIR/out3" 2>/dev/null; rc=$?
[[ $rc -eq 0 ]] || fail "tool failed with relative REMOTE_ROOT env (rc=$rc)"
grep -q "config: invalid value for remote_root" "$STATE/log" || fail "no remote_root log entry"
exit 0

#!/bin/bash
# Verified-safe port: the flock is exclusive — a second instance exits 2;
# after the holder exits the lock is free.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/a.txt"

python3 - "$CASE_DIR" <<'EOF' &
import fcntl, os, sys, time
d = sys.argv[1]
os.makedirs(d + "/state", exist_ok=True)
lock = open(d + "/state/lock", "w")
fcntl.flock(lock, fcntl.LOCK_EX)
time.sleep(6)
EOF
HOLDER=$!
sleep 1
LAN_SYNC_STATE_DIR="$STATE" "$TOOL" --simulate-local "$L" --simulate-remote "$R" \
    --list --plain >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?
wait "$HOLDER"
[[ $rc -eq 2 ]] || fail "second instance exit $rc (expected 2)"
grep -q "already running" "$CASE_DIR/err" || fail "no 'already running' message"
LAN_SYNC_STATE_DIR="$STATE" "$TOOL" --simulate-local "$L" --simulate-remote "$R" \
    --list --plain >/dev/null 2>&1 || fail "run after release failed"
exit 0

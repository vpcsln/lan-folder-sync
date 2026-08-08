#!/bin/bash
# F12: the log file must be rotated once it exceeds the cap.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
python3 - "$STATE/log" <<'EOF'
import sys
with open(sys.argv[1], "w") as f:
    f.write("x" * (1024 * 1024 + 100) + "\n")
EOF
printf 'x\n' > "$L/t.txt"
run_sim --push >/dev/null 2>&1 || fail "push failed"
sz=$(stat -c%s "$STATE/log")
[[ $sz -le $((1024 * 1024)) ]] || fail "log not rotated (size=$sz)"
[[ -e "$STATE/log.old" ]] || fail "no log.old after rotation"
exit 0

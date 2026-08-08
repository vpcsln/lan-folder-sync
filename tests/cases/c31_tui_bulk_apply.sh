#!/bin/bash
# Verified-safe port: the interactive TUI — 'q' quits cleanly; '2' then 'y'
# pushes and records state; '1' then 'n' cancels without transfers.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'new\n' > "$L/attack.txt"
python3 - "$TOOL" "$CASE_DIR" <<'EOF'
import fcntl, os, pty, select, struct, sys, termios, time

def reap(pid, code):
    if code is not None:
        return code
    try:
        w, s = os.waitpid(pid, os.WNOHANG)
        if w == pid:
            return os.waitstatus_to_exitcode(s)
    except ChildProcessError:
        return -1
    try:
        os.kill(pid, 9)
        _, s = os.waitpid(pid, 0)
        return os.waitstatus_to_exitcode(s)
    except (ChildProcessError, ProcessLookupError):
        return -9

def drive(keys, budget=8.0):
    d = sys.argv[2]
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["LAN_SYNC_STATE_DIR"] = d + "/state"
        os.execv("/usr/bin/python3", ["python3", sys.argv[1],
                 "--simulate-local", d + "/l", "--simulate-remote", d + "/r"])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    time.sleep(0.8)
    os.write(fd, keys)
    out = b""
    deadline = time.time() + budget
    code = None
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                c = os.read(fd, 65536)
            except OSError:
                break
            if not c:
                break
            out += c
        w, s = os.waitpid(pid, os.WNOHANG)
        if w == pid:
            code = os.waitstatus_to_exitcode(s)
            break
    code = reap(pid, code)
    return code, out

# 1) q quits cleanly
code, out = drive(b"q")
if code != 0:
    print("FAIL: q did not exit 0 (code %s)" % code)
    sys.exit(1)
# 2) fresh state; 2 then y applies
os.system("rm -rf " + sys.argv[2] + "/state; mkdir -p " + sys.argv[2] + "/state")
code, out = drive(b"2y\n")
if b"applied" not in out:
    print("FAIL: no apply confirmation in output")
    sys.exit(1)
if not os.path.exists(sys.argv[2] + "/r/attack.txt"):
    print("FAIL: file not transferred via TUI")
    sys.exit(1)
if not os.path.exists(sys.argv[2] + "/state/state.json"):
    print("FAIL: state not written via TUI")
    sys.exit(1)
# 3) fresh trees; 1 then n cancels
os.system("rm -rf " + sys.argv[2] + "/state " + sys.argv[2] + "/l/* " + sys.argv[2] + "/r/*")
os.makedirs(sys.argv[2] + "/state", exist_ok=True)
open(sys.argv[2] + "/l/cancel.txt", "w").write("x\n")
code, out = drive(b"1n\n")
if os.path.exists(sys.argv[2] + "/r/cancel.txt"):
    print("FAIL: cancel still transferred")
    sys.exit(1)
print("TUI flows ok")
EOF
exit $?

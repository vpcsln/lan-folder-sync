#!/bin/bash
# F13/R8: the TUI must not crash (no traceback) on a 2-row terminal.
. "$ROOT/tests/lib.sh"
STATE="$CASE_DIR/state"; L="$CASE_DIR/l"; R="$CASE_DIR/r"
mkdir -p "$STATE" "$L" "$R"
printf 'x\n' > "$L/a.txt"
python3 - "$TOOL" "$CASE_DIR" <<'EOF'
import fcntl, os, pty, select, struct, sys, termios, time
tool, d = sys.argv[1], sys.argv[2]
os.makedirs(d + "/state", exist_ok=True)
pid, fd = pty.fork()
if pid == 0:
    os.environ["LAN_SYNC_STATE_DIR"] = d + "/state"
    os.execv("/usr/bin/python3", ["python3", tool,
             "--simulate-local", d + "/l", "--simulate-remote", d + "/r"])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 2, 5, 0, 0))
time.sleep(0.8)
os.write(fd, b"q")
out = b""
deadline = time.time() + 5
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
if code is None:
    try:
        w, s = os.waitpid(pid, os.WNOHANG)
        if w == pid:
            code = os.waitstatus_to_exitcode(s)
    except ChildProcessError:
        pass
if code is None:
    try:
        os.kill(pid, 9)
        _, s = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(s)
    except (ChildProcessError, ProcessLookupError):
        code = -9
if code != 0:
    print("TUI exit code:", code)
    sys.exit(1)
if b"Traceback" in out:
    print("traceback in TUI output")
    sys.exit(1)
print("tiny-terminal TUI ok")
EOF
exit $?

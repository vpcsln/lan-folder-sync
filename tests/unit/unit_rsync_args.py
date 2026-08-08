#!/usr/bin/env python3
"""unit_rsync_args.py <lan-sync.py> — R2/R3/R11: run_rsync must use --from0
(NUL-delimited list), -i itemize for truthful transfer counts, an ssh -e
string with ConnectTimeout, --stop-after when configured, and must detect
'skipping non-regular file' (fails pre-fix on all of these)."""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

d = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/tests-regression/unit-rsync"
os.makedirs(d, exist_ok=True)
m.STATE_DIR = d
m.STATE_FILE = os.path.join(d, "state.json")
m.LOG_FILE = os.path.join(d, "log")
m.LOCK_FILE = os.path.join(d, "lock")
m.LOCAL_ROOT = os.path.join(d, "local")
os.makedirs(m.LOCAL_ROOT, exist_ok=True)

captured = {}


class FakeProc:
    def __init__(self, lines):
        self._lines = lines
        self._killed = False
        self.returncode = 0

    @property
    def stdout(self):
        return iter(self._lines)

    def wait(self):
        return 0

    def poll(self):
        return 0 if not self._killed else 0

    def kill(self):
        self._killed = True


def fake_popen(args, **kw):
    captured["args"] = list(args)
    for a in args:
        if a.startswith("--files-from="):
            with open(a.split("=", 1)[1], "rb") as f:
                captured["list"] = f.read()
    return FakeProc([
        ">f+++++++++ a.txt\n",
        "\r             50% 1,2MB/s 0:00:01 (xfr#1, to-chk=0/1)\n",
        ">f+++++++++ b.txt\n",
    ])


m.subprocess.Popen = fake_popen
m.STOP_AFTER = 0
m.HOST = "cachyos"
m.REMOTE_ROOT = "/home/vpc/docs"

# real-remote mode: exercises the -e ssh string
n = m.run_rsync(["a.txt", "b.txt"], "push", None, None)
args = captured["args"]

assert "--from0" in args, "missing --from0 in %r" % args
assert "-i" in args or "--itemize-changes" in args, "missing -i in %r" % args
e = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
assert e == ["ssh -o BatchMode=yes -o ConnectTimeout=5"], "bad -e: %r" % e
assert "--stop-after" not in args, "--stop-after should be absent when disabled"
assert captured["list"].endswith(b"\0"), "files-from list not NUL-terminated"
assert b"a.txt\0" in captured["list"], "files-from list not NUL-delimited"
assert n == 2, "transfer count wrong: %r" % n

# configured stop-after is passed through
m.STOP_AFTER = 60
m.run_rsync(["a.txt"], "push", None, None)
assert "--stop-after=60" in captured["args"], "missing --stop-after=60 in %r" % captured["args"]
m.STOP_AFTER = 0

# a skipped non-regular file must fail the batch
captured["args"] = None


def fake_popen_skip(args, **kw):
    captured["args"] = list(args)
    return FakeProc(['skipping non-regular file "link.txt"\n'])


m.subprocess.Popen = fake_popen_skip
try:
    m.run_rsync(["link.txt"], "push", None, None)
    raise AssertionError("run_rsync did not fail on a skipped file")
except m.SyncError as e:
    assert "skipped" in str(e), "unclear skip error: %s" % e

print("rsync argument hardening ok")

#!/usr/bin/env python3
"""unit_check_connection.py <lan-sync.py> — R10: check_connection must pass
a shlex.quote'd single command string for `test -d` (fails pre-fix: raw
unquoted argument)."""
import importlib.util
import sys
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

m.HOST = "cachyos"
m.REMOTE_ROOT = "/path with space"

calls = []


def fake_run(cmd, **kw):
    calls.append(cmd)
    return SimpleNamespace(returncode=0, stderr=b"")


m.subprocess.run = fake_run
m.check_connection()

assert len(calls) == 2, "expected 2 ssh calls, got %d" % len(calls)
last = calls[1][-1]
assert last == "test -d '/path with space'", "test -d not quoted: %r" % last
print("check_connection quoting ok")

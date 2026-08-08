#!/usr/bin/env python3
"""unit_ssh_timeout.py <lan-sync.py> — subprocess.TimeoutExpired must be
converted to SyncError, never leak as a raw traceback (fails pre-fix)."""
import importlib.util
import subprocess
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

m.HOST = "cachyos"


def fake_run(cmd, **kw):
    raise subprocess.TimeoutExpired(cmd, 10)


m.subprocess.run = fake_run
try:
    m.ssh(["true"], timeout=10)
    print("FAIL: no exception raised")
    sys.exit(1)
except m.SyncError:
    pass
except subprocess.TimeoutExpired:
    print("FAIL: raw TimeoutExpired leaked")
    sys.exit(1)
print("ssh timeout -> SyncError ok")

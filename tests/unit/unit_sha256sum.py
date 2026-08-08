#!/usr/bin/env python3
"""unit_sha256sum.py <lan-sync.py> — R6/F8: the remote hash command must use
the POSIX end-of-options delimiter and ./-prefix paths so leading-dash and
'-' filenames cannot be misparsed (fails pre-fix: no '--', no prefix)."""
import importlib.util
import os
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

d = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/tests-regression/unit-sha"
os.makedirs(d, exist_ok=True)
m.STATE_DIR = d
m.HOST = "cachyos"
m.REMOTE_ROOT = "/home/vpc/docs"

captured = {}


class R:
    returncode = 0
    stdout = (b"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
              b"  ./a.txt\x00" + b"0" * 64 + b"  ./-x\x00")
    stderr = b""


def fake_run(cmd, **kw):
    captured["cmd"] = cmd
    captured["input"] = kw.get("input")
    return R()


m.subprocess.run = fake_run

out = m.hash_remote(["a.txt", "-x"], None)
cmd = captured["cmd"][-1]
assert "sha256sum -z --" in cmd, "missing '--' delimiter in: %r" % cmd
assert b"./a.txt\0" in captured["input"], "path not ./ -prefixed: %r" % captured["input"]
assert b"./-x\0" in captured["input"], "dash filename not ./ -prefixed"
assert out.get("a.txt") == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", out
assert out.get("-x") == "0" * 64, out
print("sha256sum command hardening ok")

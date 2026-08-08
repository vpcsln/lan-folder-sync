#!/usr/bin/env python3
"""unit_config.py <lan-sync.py> — R10/F9/F15: config/env values are
type-checked and validated (leading dash, control chars, relative roots,
non-string JSON) with fallback to defaults (fails pre-fix: hostile values
were used verbatim)."""
import importlib.util
import json
import os
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

d = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/tests-regression/unit-config"
os.makedirs(os.path.join(d, ".config", "lan-folder-sync"), exist_ok=True)
os.makedirs(os.path.join(d, ".local", "share"), exist_ok=True)
os.environ["HOME"] = d

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        print("FAIL:", msg)
        fails += 1


def write_cfg(obj):
    with open(os.path.join(d, ".config", "lan-folder-sync", "config.json"), "w") as f:
        json.dump(obj, f)


# env HOST with leading dash -> rejected, default used
os.environ["LAN_SYNC_HOST"] = "-oProxyCommand=/bin/echo pwned"
m.load_config()
check(m.HOST == "cachyos", "HOST must fall back to default, got %r" % m.HOST)

# env HOST with newline -> rejected
os.environ["LAN_SYNC_HOST"] = "evil\nhost"
m.load_config()
check(m.HOST == "cachyos", "newline HOST accepted: %r" % m.HOST)
del os.environ["LAN_SYNC_HOST"]

# config.json with non-string host -> ignored
write_cfg({"host": ["cachyos"], "remote_user": 42})
m.load_config()
check(m.HOST == "cachyos", "non-string host accepted: %r" % m.HOST)
check(m.REMOTE_USER == "vpc", "non-string remote_user accepted: %r" % m.REMOTE_USER)

# relative remote_root -> rejected
write_cfg({"remote_root": "relative/path"})
m.load_config()
check(m.REMOTE_ROOT == "/home/vpc/Dokumente/studium",
      "relative remote_root accepted: %r" % m.REMOTE_ROOT)

# control chars in config -> rejected
write_cfg({"remote_user": "u\x00ser", "local_root": "x\x1by"})
m.load_config()
check(m.REMOTE_USER == "vpc", "NUL in remote_user accepted: %r" % m.REMOTE_USER)

# valid values still work
write_cfg({"host": "myhost", "remote_root": "/srv/docs", "stop_after_minutes": 30})
m.load_config()
check(m.HOST == "myhost", "valid host rejected: %r" % m.HOST)
check(m.REMOTE_ROOT == "/srv/docs", "valid remote_root rejected: %r" % m.REMOTE_ROOT)
check(m.STOP_AFTER == 30, "stop_after_minutes not parsed: %r" % m.STOP_AFTER)

# env stop_after overrides and garbage is clamped
os.environ["LAN_SYNC_STOP_AFTER"] = "notanumber"
m.load_config()
check(m.STOP_AFTER == 0, "garbage stop_after must clamp to 0, got %r" % m.STOP_AFTER)
os.environ["LAN_SYNC_STOP_AFTER"] = "90"
m.load_config()
check(m.STOP_AFTER == 90, "env stop_after not honored: %r" % m.STOP_AFTER)
del os.environ["LAN_SYNC_STOP_AFTER"]

print("FAILS:", fails)
sys.exit(1 if fails else 0)

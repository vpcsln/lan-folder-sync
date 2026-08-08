#!/usr/bin/env python3
"""unit_state.py <lan-sync.py> — R4/F3: state schema validation, classify
never raises on bad state, load_state ignores non-regular/oversized files
(fails pre-fix: validate_state did not exist, classify crashed)."""
import importlib.util
import json
import os
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

d = sys.argv[2] if len(sys.argv) > 2 else "/tmp/opencode/tests-regression/unit-state"
os.makedirs(d, exist_ok=True)
m.STATE_DIR = d
m.STATE_FILE = os.path.join(d, "state.json")
m.LOG_FILE = os.path.join(d, "log")
m.LOCK_FILE = os.path.join(d, "lock")

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        print("FAIL:", msg)
        fails += 1


cases = [
    ("list top-level", [1, 2], {}),
    ("string entry", {"a.txt": "garbage"}, {}),
    ("l string", {"a.txt": {"l": "bogus", "r": [1, 1.0]}}, {}),
    ("l too short", {"a.txt": {"l": [1], "r": [1, 1.0]}}, {}),
    ("l wrong types", {"a.txt": {"l": ["x", 1.0], "r": [1, 1.0]}}, {}),
    ("r missing ok", {"a.txt": {"l": [1, 1.0]}}, {"a.txt": {"l": [1, 1.0]}}),
    ("version only", {"version": 1}, {"version": 1}),
    ("future version", {"version": 99}, {}),
    ("version wrong type", {"version": "x", "a.txt": {"l": [1, 1.0], "r": [1, 1.0]}},
     {"a.txt": {"l": [1, 1.0], "r": [1, 1.0]}}),
    ("valid", {"version": 1, "a.txt": {"l": [3, 1.0], "r": [3, 1.0]}},
              {"version": 1, "a.txt": {"l": [3, 1.0], "r": [3, 1.0]}}),
]
for name, data, expect in cases:
    try:
        v = m.validate_state(data)
    except Exception as e:  # noqa: BLE001
        check(False, "%s raised %r" % (name, e))
        continue
    check(v == expect, "%s: %r != %r" % (name, v, expect))

# classify must never raise on hostile state content
left = {"a.txt": (3, 1.0), "b.txt": (2, 2.0)}
right = {"a.txt": (3, 1.0)}
for name, state in [
    ("string entry", {"a.txt": "garbage", "b.txt": {"l": [2, 2.0], "r": [2, 2.0]}}),
    ("list", [{"a.txt": 1}]),
    ("version as file", {"version": 1, "a.txt": {"l": [3, 1.0], "r": [3, 1.0]}}),
    ("file named version", {"version": 1}),
]:
    try:
        items = m.classify(left, right, state)
        check(isinstance(items, list), "%s: classify did not return a list" % name)
    except Exception as e:  # noqa: BLE001
        check(False, "%s: classify raised %r" % (name, e))

# load_state: tampered file content is validated, not crashed on
with open(m.STATE_FILE, "w") as f:
    json.dump({"a.txt": "garbage"}, f)
st = m.load_state()
check(st == {}, "load_state should skip malformed entries, got %r" % st)

# load_state: oversized state file is ignored
m.MAX_STATE_BYTES = 8
with open(m.STATE_FILE, "w") as f:
    f.write('{"x": ' + "1" * 100 + "}")
st = m.load_state()
check(st == {}, "oversized state file not ignored")
del m.MAX_STATE_BYTES

# load_state: symlinked state file is ignored
victim = os.path.join(d, "victim.txt")
with open(victim, "w") as f:
    f.write('{"a.txt": {"l": [1, 1.0], "r": [1, 1.0]}}')
os.unlink(m.STATE_FILE)
os.symlink(victim, m.STATE_FILE)
st = m.load_state()
check(st == {}, "symlinked state file was read, got %r" % st)
os.unlink(m.STATE_FILE)

# save_state adds a version field and is reloadable
items = [{"path": "a.txt", "sl": 3, "ml": 1.0, "sr": 3, "mr": 1.0,
          "kind": "same", "act": None}]
m.save_state({"a.txt": {"l": [3, 1.0], "r": [3, 1.0]}})
with open(m.STATE_FILE) as f:
    data = json.load(f)
check(data.get("version") == 1, "version field missing: %r" % data)

print("FAILS:", fails)
sys.exit(1 if fails else 0)

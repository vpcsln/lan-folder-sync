#!/bin/bash
# Verified-safe port: a listed file that vanishes before transfer makes the
# batch fail (SyncError) and state.json must NOT be written.
. "$ROOT/tests/lib.sh"
python3 - "$TOOL" "$CASE_DIR" <<'EOF'
import importlib.util, os, sys
spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
d = sys.argv[2]
os.makedirs(d + "/src", exist_ok=True)
os.makedirs(d + "/dst", exist_ok=True)
m.STATE_DIR = d + "/state"
m.STATE_FILE = d + "/state/state.json"
m.LOG_FILE = d + "/state/log"
m.LOCK_FILE = d + "/state/lock"
open(d + "/src/exists.txt", "w").write("x\n")
items = [{"path": "gone.txt", "sl": 1, "ml": 1.0, "sr": None, "mr": None,
          "kind": "new_left", "act": "push"}]
try:
    m.apply_transfers(items, simulate_remote=d + "/dst")
    print("FAIL: apply_transfers succeeded for a vanished file")
    sys.exit(1)
except m.SyncError:
    pass
if os.path.exists(m.STATE_FILE):
    print("FAIL: state.json written despite batch failure")
    sys.exit(1)
print("vanished-file batch failed cleanly, no state written")
EOF
exit $?

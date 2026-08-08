#!/bin/bash
# Shared helpers for test cases. Source with: . "$ROOT/tests/lib.sh"
set -u

# fresh subdir for this case
CASE_DIR="$SCRATCH/case-$(basename "$0" .sh)"
rm -rf "$CASE_DIR"
mkdir -p "$CASE_DIR"

fail() { echo "ASSERT FAILED: $*" >&2; exit 1; }
ok() { :; }

# assert_file_exists <path>
assert_file_exists() { [[ -e "$1" ]] || fail "file exists: $1"; }
assert_file_absent() { [[ ! -e "$1" ]] || fail "file absent: $1"; }
assert_contains() { # <needle> <haystack-file>
    grep -qF -- "$1" "$2" || fail "expected '$1' in $(basename "$2")"
}
assert_not_contains() {
    grep -qF -- "$1" "$2" && fail "did not expect '$1' in $(basename "$2")"
}
assert_no_traceback() { # <file>
    grep -q "Traceback" "$1" && fail "traceback found in $1"
    return 0
}

# run the tool in simulate mode; args: [tool args...]
run_sim() {
    LAN_SYNC_STATE_DIR="$STATE" "$TOOL" --simulate-local "$L" --simulate-remote "$R" "$@"
}

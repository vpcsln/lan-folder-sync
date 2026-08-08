#!/usr/bin/env bash
# lan-folder-sync regression suite.
# Run:  tests/run_tests.sh
# Every test runs against the tool in $ROOT with --simulate flags or python
# unit imports; launcher tests use a sandbox HOME + stub ssh/ssh-keygen/ip/
# timeout/getent so the real network, ~/.ssh and known_hosts are NEVER
# touched (real ssh-keygen ignores $HOME — see audit F1 disclosure).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH=/tmp/opencode/tests-regression
rm -rf "$SCRATCH"
mkdir -p "$SCRATCH"/{cases-logs,state,home}

TOOL="$ROOT/lan-sync.py"
LAUNCHER="$ROOT/lan-sync.sh"

PASS=0
FAIL=0
FAILED=()

say() { printf '%s\n' "$*"; }

# run <name> <command...>
run() {
    local name="$1"; shift
    if "$@" >"$SCRATCH/cases-logs/$name.log" 2>&1; then
        PASS=$((PASS + 1))
        say "PASS  $name"
    else
        FAIL=$((FAIL + 1))
        FAILED+=("$name")
        say "FAIL  $name   (log: $SCRATCH/cases-logs/$name.log)"
    fi
}

# run_case <name> <case-script>  — runs the case in a clean scratch subdir
run_case() {
    local name="$1"
    run "$name" env ROOT="$ROOT" TOOL="$TOOL" LAUNCHER="$LAUNCHER" \
        SCRATCH="$SCRATCH" LAN_SYNC_STATE_DIR="$SCRATCH/state" \
        bash "$ROOT/tests/cases/$name.sh"
}

# run_unit <name> — python unit test importing the real tool module
run_unit() {
    local name="$1"
    run "$name" env ROOT="$ROOT" TOOL="$TOOL" SCRATCH="$SCRATCH" \
        python3 "$ROOT/tests/unit/$name.py" "$TOOL" "$SCRATCH/unit-$name"
}

say "lan-folder-sync regression suite"
say "repo:      $ROOT"
say "scratch:   $SCRATCH"
say ""

# ---------- fixed-finding tests (fail on the pre-fix code, pass post-fix) ---
run_case c08_cr_rejected
run_case c09_symlink_excluded
run_case c10_state_schema
run_case c11_ansi_stdout
run_case c12_state_dir_hardening
run_case c13_bulk_error_clean
run_case c14_non_tty_clean
run_case c15_discovery_impostor
run_case c16_discovery_pin_required
run_case c17_config_validation
run_case c18_config_mode_preserved
run_case c21_log_rotation
run_case c22_tiny_terminal
run_case c23_state_prune
run_case c24_simulate_check_marker
run_case c26_state_dir_symlink_refused
run_case c30_launcher_os_match_validation

# ---------- python unit tests ------------------------------------------------
run_unit unit_valid_relpath
run_unit unit_sanitize
run_unit unit_state
run_unit unit_sha256sum
run_unit unit_rsync_args
run_unit unit_check_connection
run_unit unit_ssh_timeout
run_unit unit_config

# ---------- ported verified-safe behaviors (must stay green) -----------------
run_case c01_argv_no_shell
run_case c02_files_from_dash_literal
run_case c03_surrogate_roundtrip
run_case c04_vanished_file_no_state
run_case c05_lock_second_instance
run_case c06_verify_mismatch
run_case c07_newline_rejected
run_case c27_symlink_dir_not_followed
run_case c31_tui_bulk_apply

say ""
say "results: $PASS passed, $FAIL failed"
if (( FAIL > 0 )); then
    say "failed: ${FAILED[*]}"
    exit 1
fi
exit 0

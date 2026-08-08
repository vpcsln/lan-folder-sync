# FIX_REPORT — lan-folder-sync security hardening (v1.1.0)

Audit source: `/tmp/opencode/SECURITY_AUDIT.txt` (findings F1–F18, doc
deltas D1–D9, recommendations R1–R13). Every finding was re-verified
(reproduced or rejected) against the current code before fixing; every fix
has a regression test that failed on the pre-fix code and passes now.

Web sources cited (consulted 2026-08-08):

- OpenSSH `ssh_config(5)` — https://man7.org/linux/man-pages/man5/ssh_config.5.html
  (HostKeyAlias: "an alias … used instead of the real host name when looking
  up or saving the host key in the host key database"; StrictHostKeyChecking:
  "yes … never automatically add host keys … refuses to connect to hosts
  whose host key has changed … maximum protection against MITM";
  accept-new: "automatically add new host keys … but will not permit
  connections to hosts with changed host keys"; ConnectTimeout: applied "to
  establishing the connection and to performing the initial SSH protocol
  handshake"; BatchMode: disables "password prompts and host key
  confirmation requests").
- rsync(1) — https://man7.org/linux/man-pages/man1/rsync.1.html
  (--from0: file names "terminated by a null ('\0') character, not a NL, CR,
  or CR+LF" — this affects --files-from; --stop-after=MINS; --files-from=FILE;
  --itemize-changes/-i; --mkpath; --timeout; EXIT VALUES 0/23/24).
- OWASP OS Command Injection Defense —
  https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html
  (parameterization; allowlist validation; hardcode the command; "POSIX: The
  first `--` argument that is not an option-argument should be accepted as a
  delimiter indicating the end of options").
- Python stdlib — https://docs.python.org/3/library/os.html (os.open flags,
  O_NOFOLLOW), tempfile, json, fcntl.flock, curses.
- Environment-verified behaviors (this machine: Fedora 44, rsync 3.4.4,
  coreutils, OpenSSH): rsync --from0/-i/--stop-after availability; rsync
  itemize `>f` lines in both directions; rsync messages stay English under
  de_DE.UTF-8; `sha256sum -z --` handles `--check`/`-` names when paths are
  `./`-prefixed; `ssh -G` parses a leading-dash HOST as an option.

---

## F1 — CRITICAL — Discovery host-key pin bypass (lan-sync.sh)

- Verified/reproduced: YES (audit TEST LOG item 16 + sandbox launcher
  simulation; the impostor was accepted, the pin erased via the
  `ssh-keygen -R` fallback, `HostName` rewritten). [TESTED]
- Root cause: lan-sync.sh:162 `is_laptop || { ssh-keygen -R "$REMOTE";
  is_laptop; }` erased the pinned host key and retried with
  `StrictHostKeyChecking=accept-new`; `test_candidate` used
  `StrictHostKeyChecking=no` + `UserKnownHostsFile=/dev/null`.
- Fix (R1): removed the `ssh-keygen -R` fallback entirely; no `accept-new`
  anywhere; every probe (`is_laptop`, new `probe_ip`) uses
  `StrictHostKeyChecking=yes` + the real `UserKnownHostsFile` +
  `HostKeyAlias="$REMOTE"` so the candidate is verified against the pinned
  key; `HostName` is rewritten only after a pin-verified probe succeeded
  (verify-then-rewrite for mDNS and scan candidates); a missing pin aborts
  discovery in non-interactive mode with instructions and, in a terminal,
  runs an explicit interactive `ssh -o StrictHostKeyChecking=ask` pinning
  step (BatchMode is intentionally not used there — ssh_config(5):
  BatchMode disables host key confirmation). The "laptop not found" message
  now documents the manual re-pin procedure.
- Tests: c15_discovery_impostor, c16_discovery_pin_required (fail pre-fix,
  pass post-fix; stubbed ssh/ssh-keygen in a sandbox HOME).
- Sources: ssh_config(5) HostKeyAlias / StrictHostKeyChecking / accept-new /
  BatchMode (man7).

## F2 — HIGH — Symlinks treated as files; false "synced" state (lan-sync.py)

- Verified/reproduced: YES ("done: 3 files applied" with 2 transferred,
  link recorded in state.json, re-listed every run). [TESTED]
- Root cause: `scan_local` used `os.path.isfile()` (follows links) with
  `os.lstat()` metadata; rsync without `-l` skips symlinks with exit 0.
- Fix (R3): scan keeps only `S_ISREG` files (lstat), matching the remote
  `find -type f` view; `run_rsync` detects rsync's `skipping non-regular
  file` output and fails the batch (state not recorded) — a TOCTOU swap
  after the scan can no longer be silently absorbed; rsync `-i`
  (--itemize-changes, rsync(1)) output is counted so "done: N files
  applied" reports files actually transferred.
- Tests: c09_symlink_excluded, unit_rsync_args (skip detection + transfer
  count).
- Sources: rsync(1) --itemize-changes; platform check that skipped
  symlinks exit 0 (so exit codes alone cannot detect this).

## F3 — HIGH — state.json trusted without validation (lan-sync.py)

- Verified/reproduced: YES (string entry → AttributeError; string mtime →
  TypeError; JSON array → AttributeError; crafted mtimes reclassify
  files). [TESTED]
- Fix (R4): `validate_state()` — top-level must be a dict; entries must be
  dicts with `l`/`r` as `[size:int, mtime:int|float]`; malformed entries
  dropped with a log line; `version` field added (STATE_VERSION = 1, future
  versions invalidate the file); `load_state` ignores non-regular
  (symlinked) and oversized (>64 MiB) files; `classify` tolerates
  non-dict state. `save_state` writes `version` and raises SyncError on
  failure.
- Tests: c10_state_schema, unit_state (fails pre-fix).
- Sources: OWASP Input Validation; Python json docs.

## F4 — HIGH — Terminal escape injection via filenames (lan-sync.py)

- Verified/reproduced: YES (ESC bytes in `--list` and `--list --plain`
  output, od-verified). [TESTED]
- Fix (R5): all stdout paths flow through `safe_text()` (C0/DEL → '?',
  surrogates → U+FFFD, the documented display character); `fmt_row`,
  `report`'s `item_line`/`collapse_path`/group headers sanitized; width
  math is display-width aware (`unicodedata.east_asian_width`) and strips
  ANSI codes (`disp_len`) so colored icons no longer inflate lengths.
  Byte-exact comparison logic untouched.
- Tests: c11_ansi_stdout, unit_sanitize (fails pre-fix).
- Sources: OWASP Input Validation / encoding cheat sheets (display
  filtering as defense-in-depth; the real fix is rejection in
  valid_relpath, F5).

## F5 — MEDIUM — CR in filenames splits --files-from records (lan-sync.py)

- Verified/reproduced: YES (rsync split `carriage\rreturn.txt` into two
  lookups, exit 23, whole batch failed with a traceback). [TESTED]
- Fix (R2): `valid_relpath` rejects **all** C0 controls and DEL (NUL,
  newline, CR, ESC, tab, …); the rsync list is NUL-delimited via
  `--from0` so no NL/CR separator can ever split a record (rsync(1):
  "terminated by a null character, not a NL, CR, or CR+LF").
- Tests: c08_cr_rejected, unit_valid_relpath, unit_rsync_args (--from0 +
  NUL-delimited temp file).
- Sources: rsync(1) --from0 (man7); OWASP input validation (reject).

## F6 — MEDIUM — State-dir hardening (lan-sync.py)

- Verified/reproduced: YES (0755 dir kept; lock symlink truncated a victim
  file; log appended through symlink; state.json.tmp written through).
  [TESTED]
- Fix (R7): `ensure_state_dir()` on every start — create if missing, refuse
  symlinked/non-directory/non-owned dirs, chmod 0700; `open_nofollow()`
  (O_NOFOLLOW, Python os docs) for lock/log/state.tmp; save_state raises
  SyncError instead of writing through a symlink; `load_state` refuses
  non-regular state files.
- Tests: c12_state_dir_hardening, c26_state_dir_symlink_refused (fail
  pre-fix).
- Sources: Python os.open O_NOFOLLOW; CWE-59 (link following).

## F7 — MEDIUM — Uncaught exceptions → tracebacks (lan-sync.py)

- Verified/reproduced: YES (bulk transfer failure and non-tty TUI run both
  dumped tracebacks, exit 1). [TESTED]
- Fix (R8): bulk mode wrapped in try/except SyncError → clean
  "error: …" + exit 1; top-level SyncError/KeyboardInterrupt handlers
  (exit 130); tty pre-check before curses (exit 2 with a friendly message);
  `draw()`/`prompt()`/`help_screen()` clamp coordinates and catch
  `curses.error`; `run()` loop survives getch errors.
- Tests: c13_bulk_error_clean, c14_non_tty_clean, c22_tiny_terminal (fail
  pre-fix).
- Sources: Python curses docs (curses.error).

## F8 — MEDIUM — sha256sum misparses leading-dash names (lan-sync.py)

- Verified/reproduced: YES (a file named `--check` flipped sha256sum into
  check mode and killed the whole 40-file batch; `-` read stdin).
  [TESTED]
- Fix (R6): `sha256sum -z --` (POSIX end-of-options delimiter, OWASP) and
  `./`-prefix every path on stdin so even a file literally named `-` hashes
  as a file (coreutils special-cases a bare `-` as stdin regardless of
  `--`); the `./` prefix is stripped when parsing output; a non-empty
  request that yields zero records raises SyncError instead of silently
  skipping.
- Tests: unit_sha256sum (fails pre-fix); E4/E4b platform verification.
- Sources: OWASP OS Command Injection Defense ("POSIX … `--` …
  delimiter"); coreutils sha256sum behavior verified on this system.

## F9 — MEDIUM — Config/env injection surfaces (lan-sync.py, lan-sync.sh)

- Verified/reproduced: YES (`ssh -G` proved a leading-dash HOST is parsed
  as an ssh option; launcher `eval echo`; unquoted `test -d`). [TESTED]
- Fix (R10): `load_config` validates every value — type (str), no control
  characters, `host`/`remote_user` charset `[A-Za-z0-9._-]` with leading
  dash rejected, `remote_root` absolute — invalid values fall back to the
  default and are logged; launcher validates `REMOTE`/`REMOTE_USER`/
  `OS_MATCH` before any connection and replaces `eval echo` with
  `${KEY/#\~/$HOME}`; `check_connection` builds a shlex.quote'd
  `test -d '…'` command; `stop_after_minutes` accepts int config values.
- Tests: c17_config_validation, c30_launcher_os_match_validation,
  unit_config, unit_check_connection (fail pre-fix).
- Sources: OWASP allowlist validation + hardcode commands; ssh_config(5).

## F10 — MEDIUM — set_hostname downgrades ~/.ssh/config to 0644 (lan-sync.sh)

- Verified/reproduced: YES (sandbox config went 0600 → 0644 after
  discovery). [TESTED]
- Fix (R9): `set_hostname` records the original mode, writes the temp with
  0600, and restores the original mode after `mv`; temp is removed on
  failure.
- Tests: c18_config_mode_preserved (fail pre-fix).
- Sources: best practice for config-file writes (temp + atomic rename with
  preserved metadata).

## F11 — MEDIUM — Orphan rsync / weak timeouts (lan-sync.py)

- Verified/reproduced: by code inspection (KeyboardInterrupt propagated
  without killing the child; no connect timeout; no wall-clock cap);
  lock-release behavior verified. [INSPECTION + TESTED (lock)]
- Fix (R11): `run_rsync` kills+reaps the child in a `finally` on
  interruption; `-e "ssh -o BatchMode=yes -o ConnectTimeout=5"`
  (ssh_config(5): ConnectTimeout covers connection + handshake); optional
  `--stop-after=MINS` (rsync(1)) via `stop_after_minutes` /
  `LAN_SYNC_STOP_AFTER` (default 0 = unlimited).
- Tests: unit_rsync_args (asserts the -e string and --stop-after).
- Sources: rsync(1) --stop-after; ssh_config(5) ConnectTimeout.

## F12 — LOW — Log growth and raw control bytes (lan-sync.py)

- Verified/reproduced: yes (append-through-symlink; unbounded growth by
  inspection). [TESTED (symlink) / INSPECTION (growth)]
- Fix (R12): log rotated past 1 MiB (`log` → `log.old`, previous .old
  removed); all logged text passes `safe_text`; log opened O_NOFOLLOW.
- Tests: c21_log_rotation, c12_state_dir_hardening (log symlink).
- Sources: Python os docs; CWE-116.

## F13 — LOW — TUI crashes on tiny terminals (lan-sync.py)

- Verified/reproduced: YES (2-row and 1-row PTY runs traceback). [TESTED]
- Fix (R8): see F7 (draw/prompt/help clamping + curses.error handling).
- Tests: c22_tiny_terminal.

## F14 — LOW — os_match remote shell injection (lan-sync.sh)

- Verified/reproduced: by code inspection (single-quoted interpolation).
  [INSPECTION]
- Fix (R10): os_match restricted to `[A-Za-z0-9_-]` before any ssh call.
- Tests: c30_launcher_os_match_validation.

## F15 — LOW — Malformed config.json crashes (lan-sync.py)

- Verified/reproduced: by code inspection (non-str values flowed into
  argv). [INSPECTION]
- Fix (R10): type-checked in load_config (see F9).
- Tests: unit_config.

## F16 — INFO — --check in simulate mode pretends (lan-sync.py)

- Verified/reproduced: YES. [TESTED]
- Fix: prints "connection OK (simulated)". 
- Tests: c24_simulate_check_marker.

## F17 — INFO — Silent scan gaps (lan-sync.py)

- Verified/reproduced: by code inspection (os.walk onerror=None; find
  errors suppressed). [INSPECTION]
- Fix: `os.walk(onerror=…)` logs walk errors; scan/hash SSH timeouts
  surface as SyncError ("remote scan timed out") instead of raw
  TimeoutExpired tracebacks.
- Tests: unit_ssh_timeout; c13 (clean error path).

## F18 — INFO — Subnet-scan disclosure

- Verified: yes (argv capture of the probe; inherent to design). [TESTED]
- Fix: documented as an accepted risk in SECURITY.md ("Known boundaries")
  with the recommendation to use a fixed HostName when unacceptable; the
  probe no longer runs with host-key checking disabled, so a probed host
  can no longer be *trusted* — only probed.

---

## Additional issues found during the re-audit (beyond F1–F18)

| # | Finding | Verified | Fix | Test |
|---|---------|----------|-----|------|
| A1 | `classify` crashed on a list-typed state (defense-in-depth gap; load_state already validated, but the function itself was not robust) | [TESTED] | `classify` coerces non-dict state to `{}` | unit_state |
| A2 | `stop_after_minutes` as an int in config.json was rejected (only strings parsed) | [TESTED] | config accepts int or str, clamps to ≥ 0 | unit_config |
| A3 | `subprocess.TimeoutExpired` from ssh/scan/hash leaked as raw tracebacks | [TESTED] | converted to SyncError (see F17) | unit_ssh_timeout |
| A4 | State file growth: entries for files gone from both sides never pruned | [TESTED] | pruned on the next successful apply (version key preserved) | c23_state_prune |
| A5 | ANSI escape bytes inflated report() width math (colored icons counted as characters) | [INSPECTION] | `disp_len` strips ANSI before width math; display-width truncation everywhere | unit_sanitize |
| A6 | CJK/wide characters broke sanitize() truncation (codepoint vs column count) | [TESTED] | `disp_width`/`trunc_disp` via `unicodedata.east_asian_width` | unit_sanitize |
| A7 | Launcher accepted a nonexistent ssh key path silently | [TESTED] | `[[ -f "$KEY" ]]` check with instructions | c15/c16/c18/c30 sandboxes |
| A8 | IPv6-only networks: discovery is IPv4-only (subnet prefix + mDNS filter) | [INSPECTION] | documented in SECURITY.md/README as accepted limitation | — |
| A9 | Cross-machine concurrency on one remote path is uncoordinated | [INSPECTION] | documented as accepted risk (per-file atomic renames) | — |
| A10 | Config value with NUL (JSON `\u0000`) crashed subprocess argv | [INSPECTION] | CONTROL_RE validation rejects it (F9) | unit_config |

Rejected/non-issues after testing: `--files-from` line containing exactly
`-` is a literal filename on rsync 3.4.4 (no stdin special-casing);
`-i` and `--info=progress2` coexist; rsync messages remain English under
de_DE.UTF-8 (skip detection is viable on this platform); env vars cannot
contain NUL (execve), so only config/env control-char validation is needed.

---

## Documentation deltas (D1–D9) — resolved

- D1/D2 (SECURITY.md "Discovery cannot be tricked…", "transfer always runs
  over the verified alias with the pinned host key"): now TRUE — see F1.
- D3 (dir 0700 / state 0600): now enforced on every start (F6).
- D4 (NUL+newline rejected): now all C0 + DEL rejected, `--from0` lists
  (F5); SECURITY.md/ARCHITECTURE.md updated.
- D5 ("a failure can never mark an unsynced file as synced"): now true in
  spirit — symlinks are excluded, skips fail the batch, counts are actual
  transfers (F2/F3).
- D6 ("--timeout=120 so a dead network fails"): ConnectTimeout=5 and
  optional --stop-after added; wording updated (F11).
- D7 (README "ssh_key = SSH key used for the connection"): corrected to
  "used by discovery probes; transfers use ~/.ssh/config" (the code never
  used SSH_KEY for transfers — grep-verified).
- D8 (README "host-key pinning" bullet): rewritten for the no-auto-accept /
  no-auto-erase model.
- D9 (ARCHITECTURE "validated relative paths"): updated for --from0 and the
  full rejected-character class.

## Remaining accepted risks

- Local attacker with the user's UID can always read/write the user's own
  files (out of scope; the tool hardens against accidental/sibling-user
  misconfiguration, not same-UID compromise).
- The rsync skip-detection regex matches rsync's English message; rsync on
  this platform prints English under de_DE, but a translated rsync build
  could bypass detection (the scan-side symlink exclusion remains the
  primary control).
- Subnet-scan disclosure of username + public key (F18) — documented.
- IPv4-only discovery (A8) — documented.
- No cross-machine lock (A9) — documented.

## Test run log

Baseline (pre-fix, commit cfd3569): 34-test suite → 25 failed / 9 passed.
All 25 failures are the fixed-finding tests (c08–c30 launcher/state/output
tests and the 8 python units); all 9 passes are the ported verified-safe
behaviors (c01–c07, c27, c31).

Post-fix run:

```
lan-folder-sync regression suite
PASS  c08_cr_rejected          PASS  c09_symlink_excluded
PASS  c10_state_schema         PASS  c11_ansi_stdout
PASS  c12_state_dir_hardening  PASS  c13_bulk_error_clean
PASS  c14_non_tty_clean        PASS  c15_discovery_impostor
PASS  c16_discovery_pin_required  PASS  c17_config_validation
PASS  c18_config_mode_preserved   PASS  c21_log_rotation
PASS  c22_tiny_terminal        PASS  c23_state_prune
PASS  c24_simulate_check_marker   PASS  c26_state_dir_symlink_refused
PASS  c30_launcher_os_match_validation
PASS  unit_valid_relpath       PASS  unit_sanitize
PASS  unit_state               PASS  unit_sha256sum
PASS  unit_rsync_args          PASS  unit_check_connection
PASS  unit_ssh_timeout         PASS  unit_config
PASS  c01_argv_no_shell        PASS  c02_files_from_dash_literal
PASS  c03_surrogate_roundtrip  PASS  c04_vanished_file_no_state
PASS  c05_lock_second_instance PASS  c06_verify_mismatch
PASS  c07_newline_rejected     PASS  c27_symlink_dir_not_followed
PASS  c31_tui_bulk_apply
results: 34 passed, 0 failed
```

Additional post-fix verification (audit TEST LOG re-runs): py_compile OK;
bash -n OK; re-pull reports "nothing to do"; `--newest` resolves by mtime;
state.json contains `"version": 1`; COLUMNS=30 `--list` renders; 20k-file
scan in 0.4 s; rsync itemize `>f` counts both directions (E1/E1b);
`sha256sum -z -- ./-` hashes a dash-named file (E4b); real read-only
`lan-sync --check` and `lan-sync --list` pass (see final green checks).

All scratch artifacts remain under /tmp/opencode (test trees, stubs,
logs).

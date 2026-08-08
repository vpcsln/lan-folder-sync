# Changelog

## [1.1.0] - 2026-08-08

Security hardening release (fixes findings F1–F18 of the security audit,
see FIX_REPORT.md).

### Critical
- Discovery no longer erases host-key pins (`ssh-keygen -R` fallback
  removed) and never auto-accepts keys (`accept-new` removed). All probes
  verify against the pinned `HostName` key via `HostKeyAlias` with
  `StrictHostKeyChecking=yes`; first use requires an explicit interactive
  pin; `~/.ssh/config` `HostName` is only rewritten for a pin-verified
  host. An impostor on the subnet can no longer hijack transfers
  (F1).

### Data integrity
- Symlinks are excluded from the local scan (regular files only, matching
  the remote view); rsync `skipping non-regular file` output fails the
  batch; "done: N files applied" counts files actually transferred
  (F2).
- `state.json` is schema-validated on load, carries a `version` field,
  and can no longer crash the tool or steer decisions via malformed
  entries; entries for vanished files are pruned (F3).
- `rsync --files-from` lists are NUL-delimited (`--from0`), and
  `valid_relpath` rejects all C0 control characters and DEL — CR/ESC/tab
  filenames can no longer split records or inject output (F4/F5).
- All stdout paths are control-character-filtered (display-safe);
  display truncation is width-aware (CJK, ANSI) (F4).

### Hardening
- State directory re-checked on every start (mode 0700, owner, no
  symlink); lock/log/state-temp files opened with `O_NOFOLLOW` — symlink
  attacks on the state dir fail closed (F6).
- Bulk failures, non-tty runs, tiny terminals and SSH timeouts produce
  clean errors, never tracebacks (F7/F13).
- Remote hashing uses `sha256sum -z --` with `./`-prefixed paths — names
  like `--check` or `-` can no longer break or skew `--verify` (F8).
- Config/env values are validated (safe charsets, absolute remote root,
  no control characters); launcher `eval` removed; `test -d` quoted
  (F9/F10/F14/F15).
- `~/.ssh/config` rewrites preserve the original file mode (F10).
- rsync `-e` adds `ConnectTimeout=5`; optional wall-clock cap
  (`stop_after_minutes` / `LAN_SYNC_STOP_AFTER`, rsync `--stop-after`);
  interrupted transfers kill+reap the rsync child (F11).
- Log rotated past 1 MiB; logged path bytes sanitized (F12).
- `--check` in simulate mode says so; scan timeouts surface as clean
  errors; walk errors logged (F16/F17).

### Testing
- New regression suite `tests/run_tests.sh` (34 tests): one test per fixed
  finding (fails pre-fix, passes post-fix) plus ported verified-safe
  behaviors; launcher tests run against stubbed ssh/ssh-keygen/ip/timeout
  in a sandbox HOME. See README (Development) and FIX_REPORT.md.

## [1.0.0] - 2026-08-08

Initial public release of lan-folder-sync.

- Full-screen interactive difference viewer (curses TUI) with all
  differences shown at once, filters, per-row direction overrides and
  selection
- Bulk modes: pull all / push all / newest wins / apply selection — no
  deletions ever
- "Unsure" detection: files changed on both sides since the last sync, or
  with near-equal mtimes, are flagged and ask for a decision
- State-based conflict detection (`~/.local/share/lan-folder-sync/state.json`)
- `--verify` content hashing (SHA-256, remote via `xargs -0 sha256sum -z`)
- Grouped, colorized `--list` report with summary and next-step hints;
  `--list --plain` for scripts
- Automatic laptop discovery (cached IP → mDNS → verified subnet scan) with
  DHCP-proof host-key pinning (`HostKeyAlias`)
- Configuration via `~/.config/lan-folder-sync/config.json` with environment
  variable overrides
- Security: key-only SSH (BatchMode), validated NUL-separated file lists,
  `rsync --files-from` (0600 temp), atomic transfers, single-instance lock,
  crash-safe state bookkeeping
- Byte-exact handling of non-UTF-8 filenames (surrogateescape, binary
  files-from lists)

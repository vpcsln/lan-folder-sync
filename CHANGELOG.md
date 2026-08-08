# Changelog

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

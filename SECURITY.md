# Security

This document describes the security model of lan-folder-sync. The tool is
designed for use on shared/guest networks (including university Wi-Fi like
eduroam) without exposing credentials or trusting unknown hosts.

## Principle

The tool treats the network as **hostile**: nothing is ever transmitted
without (a) key-based authentication of this machine to the other machine and
(b) verification of the other machine's identity. No password is ever stored,
asked for, or transmitted by the script.

## SSH layer

- **Key-only authentication**: every `ssh` invocation uses `BatchMode=yes`,
  so the script can neither prompt for a password nor fall back to one.
  Credentials are your private key, which never leaves your machine
  (`~/.ssh/id_ed25519_sync`, mode 0600 by `ssh-keygen`).
- **Host keys are never auto-accepted and never auto-erased.** All
  verification happens against the pinned entry for the alias in
  `~/.ssh/known_hosts` (`HostKeyAlias`). Discovery uses
  `StrictHostKeyChecking=yes` plus `HostKeyAlias` on every probe: a host
  whose key does not exactly match the pin is refused. If the laptop's key
  ever changes (spoofing attempt or reinstall), discovery fails with a
  message; re-pinning is a **manual** two-step action
  (`ssh-keygen -R <alias>` + `ssh -o StrictHostKeyChecking=ask <alias> true`)
  and is never performed by the tool itself.
- **First run requires an explicit interactive pin.** If no host key is
  pinned yet, the launcher refuses to proceed when run non-interactively
  (cron/scripts) and, in a terminal, shows the laptop's fingerprint via
  `ssh -o StrictHostKeyChecking=ask` and asks the user to confirm it. There
  is no trust-on-first-use auto-accept (`accept-new` is never used).
- **Discovery cannot be tricked into talking to an impostor.** The subnet
  scan / mDNS probes verify each candidate against the pinned host key
  (via `HostKeyAlias`) *before* any trust is placed in it; the probe runs
  only `grep -qis '<os_match>' /etc/os-release` and transfers no file data.
  The config's `HostName` is only rewritten for a candidate that passed
  pin-verified probing. The actual file transfer always runs over the alias
  with the pinned host key.
- `os_match` and the SSH alias/user are validated to a safe character set
  before use, so config/env values cannot smuggle shell metacharacters or
  `ssh` options into commands.

## Data handling

- **No shell interpolation of filenames.** File lists are NUL-separated
  output of `find -printf` on the remote side; transfers use
  `rsync --files-from` + `--from0` (NUL-delimited records, so no line
  separator — NL or CR — can split a filename) with a 0600 temporary file
  that is deleted afterwards. Commands are built as argument vectors
  (no `shell=True`); the shell command strings (remote `find`, remote
  `sha256sum`) are built with `shlex.quote` from validated configuration.
- **Path validation**: absolute paths, `..`, empty components, and **all
  C0 control characters** (NUL, newline, carriage return, ESC, tab, …) and
  DEL are rejected and logged. Control characters are rejected because they
  break line-based tools and inject terminal sequences (CWE-116). Names are
  decoded with `surrogateescape`, so byte-exact names (including non-UTF-8
  filenames) round-trip without loss or ambiguity.
- **Output is display-safe**: every stdout path (listings, reports) is
  passed through a control-character filter, so a hostile filename cannot
  inject ANSI/terminal escape sequences into a terminal or a script's
  output. Byte-exact comparison logic is untouched — only the display is
  filtered.
- **No deletions, ever.** The tool has no code path that removes files
  (`rsync --delete` is never used, no `rm`). Even in "full" modes missing
  files are only reported.
- **Atomic transfers**: `rsync` writes to a temporary file and renames into
  place; an interrupted transfer leaves the target untouched.
- **Crash-safe state**: the state file is written only after a successful
  transfer batch, and only for files that were actually transferred (or
  already identical). A failure — including rsync skipping a listed file
  because it changed into a symlink/fifo after the scan — can never mark an
  unsynced file as synced.
- **State schema is validated**: `state.json` entries are type-checked on
  load; malformed entries are skipped with a log line instead of crashing;
  the file carries a `version` field; oversized or non-regular (e.g.
  symlinked) state files are ignored.
- **Local state protection**: state/log/lock live in a directory that is
  re-checked and re-tightened to mode 0700, owned by the current user, and
  never a symlink, on every start. All state files are opened with
  `O_NOFOLLOW`; a symlinked lock/log/state-temp file is refused, so a local
  attacker cannot redirect writes or truncate arbitrary files through the
  state directory. The log is rotated past 1 MiB.

## Concurrency & robustness

- A file lock guarantees a single running instance; a second instance exits
  with an error instead of racing.
- SSH calls have timeouts (10 s connection check, 120 s scan, 600 s hash)
  that surface as clean errors, not tracebacks. `rsync` uses
  `--timeout=120` (idle) plus an optional wall-clock cap
  (`stop_after_minutes` / `LAN_SYNC_STOP_AFTER`, rsync `--stop-after`) so a
  dead or trickling network fails instead of hanging.
- Files that vanish between scan and transfer cause `rsync` to fail the
  batch (state not updated) — no silent "synced" marks.
- On interruption (Ctrl-C), the rsync child is killed and reaped; no orphan
  transfer keeps writing after the user cancelled.
- The TUI survives tiny terminals and resizes without crashing; running it
  without a terminal produces a clean error instead of a curses traceback.

## Known boundaries & accepted risks

- Trust model: both machines are yours, and the SSH key is the root of trust.
  Anyone with your private key can read/write the synced folders — protect
  the key as usual.
- The remote `find`/`sha256sum`/`rsync` binaries run under your remote user
  account; keep that account's login protections in place.
- **Subnet scan disclosure**: discovery probes every host on the current
  IPv4 subnet with a TCP port-22 connect and, for responders, a key-auth
  probe. Each probed host learns your username and public key (the public
  key is public by design). This is inherent to automatic discovery; if this
  is unacceptable, use a fixed `HostName` in `~/.ssh/config` (the cached
  path) and never let discovery fall back to the scan.
- **IPv4-only discovery**: the subnet scan derives its prefix from
  `ip -4 route`, and mDNS answers are filtered to IPv4. On IPv6-only
  networks discovery will not find the laptop via scan; use the cached
  `HostName` or mDNS with an IPv4 address.
- **No cross-machine lock**: the single-instance lock protects concurrent
  runs on one machine only. Two machines syncing the same remote folder at
  the same time are not coordinated (rsync's per-file atomic rename keeps
  individual files consistent).
- Guest Wi-Fi may block direct connections entirely (client isolation); the
  tool fails with a clear message — it does not downgrade security to work
  around it.
- The rsync "skipping non-regular file" detection matches rsync's English
  message; rsync on this platform prints English regardless of locale, but
  the detection is best-effort. The scan itself already excludes symlinks,
  so a skip indicates a TOCTOU swap and fails the batch conservatively.

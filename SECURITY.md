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
- **Host-key verification is never disabled for data transfer.** The real
  connection goes through the `HostKeyAlias` entry in `~/.ssh/config`, so the
  laptop's host key is pinned under a stable name. If the laptop's key ever
  changes (spoofing attempt or reinstall), SSH refuses to connect rather than
  silently trusting a new key.
- **Discovery cannot be tricked into talking to an impostor.** The subnet
  scan probes a candidate only to check "does the key work AND does
  `/etc/os-release` match `os_match`?" — the probe uses a throwaway known
  hosts file and transfers no data. The actual file transfer always runs over
  the verified alias with the pinned host key.

## Data handling

- **No shell interpolation of filenames.** File lists are NUL-separated
  output of `find -printf` on the remote side; transfers use
  `rsync --files-from` with a 0600 temporary file that is deleted afterwards.
  Commands are built as argument vectors (no `shell=True`); the one shell
  command string (remote `find`) is built with `shlex.quote` from a constant.
- **Path validation**: absolute paths, `..`, empty components, NUL and
  newline characters are rejected and logged. Names are decoded with
  `surrogateescape`, so byte-exact names (including non-UTF-8 filenames)
  round-trip without loss or ambiguity.
- **No deletions, ever.** The tool has no code path that removes files
  (`rsync --delete` is never used, no `rm`). Even in "full" modes missing
  files are only reported.
- **Atomic transfers**: `rsync` writes to a temporary file and renames into
  place; an interrupted transfer leaves the target untouched.
- **Crash-safe state**: the state file is written only after a successful
  transfer batch. A failure can never mark an unsynced file as synced.
- **Local state protection**: state/log/lock live in
  `~/.local/share/lan-folder-sync/` (directory 0700, state file 0600).

## Concurrency & robustness

- A file lock guarantees a single running instance; a second instance exits
  with an error instead of racing.
- SSH calls have timeouts; `rsync` uses `--timeout=120` so a dead network
  fails instead of hanging.
- Files that vanish between scan and transfer cause `rsync` to fail the batch
  (state not updated) — no silent "synced" marks.

## Known boundaries

- Trust model: both machines are yours, and the SSH key is the root of trust.
  Anyone with your private key can read/write the synced folders — protect
  the key as usual.
- The remote `find`/`sha256sum`/`rsync` binaries run under your remote user
  account; keep that account's login protections in place.
- Guest Wi-Fi may block direct connections entirely (client isolation); the
  tool fails with a clear message — it does not downgrade security to work
  around it.

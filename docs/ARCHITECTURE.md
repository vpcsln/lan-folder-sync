# Architecture

This document explains how lan-folder-sync works internally. It is aimed at
maintainers and curious users.

## Pipeline

```
scan (local walk + remote find)
   → classify (state-aware comparison)
   → decide (interactive TUI or bulk mode / --resolve)
   → transfer (rsync --files-from --from0 over SSH)
   → record (state file update, only on success)
```

## 1. Scan

- **Local**: `os.walk(..., followlinks=False)` + `os.lstat`, keeping only
  regular files (`S_ISREG`). Symlinks — to files, directories, or broken —
  are excluded, matching the remote `find -type f` view exactly, so the two
  sides can never disagree about a symlink. Walk errors are logged.
- **Remote**: a single SSH call
  `find <remote_root> -type f -printf '%P\0%T@\0%s\0'`.
  The format string is quoted with `shlex.quote` because `ssh` concatenates
  its arguments into a remote shell command — an unquoted `\0` would be eaten
  by the remote shell. Output is NUL-separated (`<path>\0<mtime>\0<size>\0`),
  parsed in triplets.
- Both sides decode filenames with `surrogateescape` (byte-exact, safe for
  non-UTF-8 names). Paths that are absolute, contain `..`, empty components,
  or **any C0 control character / DEL** (NUL, newline, CR, ESC, tab, …) are
  rejected and logged (`valid_relpath`). Control characters are rejected
  because they break line-based tools and inject terminal sequences; the
  remaining names are byte-exact.

A full scan of a 7.5 GB / ~2 300 file tree takes about 1 s.

## 2. Classify

Constants: `THRESHOLD = 2.0 s` (mtime difference for "clearly newer"),
`CHANGE_EPS = 0.5 s` (change detection vs. the state file).

Per path, from `left` (local) and `right` (remote) metadata and the state
file:

| Case | Result |
|------|--------|
| only on remote | `new_right` → pull |
| only on local | `new_left` → push |
| both, no state entry (first run) | mtime difference > 2 s → newer side wins; sizes equal → `same`; otherwise → `⚠ unsure` |
| both, state entry | side(s) whose mtime differs > 0.5 s from the recorded value = "changed"; one side changed → that direction; both changed → `⚠ unsure`; neither → `same` |
| file in state but missing on one side | not listed as an action — **never deleted**, informational only (see Limitations) |

The state file is **schema-validated on load** (`validate_state`): entries
must be dicts with `l`/`r` as `[size:int, mtime:number]`; malformed entries
are dropped with a log line; the file carries a `version` field (an unknown
future version invalidates the whole file); oversized or non-regular state
files are ignored. `classify` additionally tolerates non-dict state, so a
corrupted state file can never crash the tool — at worst it is treated as
empty (a full re-comparison).

## 3. Decide

- **Bulk modes**: `pull` = all `pull` items, `⚠` items resolved per
  `--resolve` (or the interactive prompt); `push` mirrors; `newest` resolves
  `⚠` by higher mtime (ties are skipped). Already-forced per-row choices are
  respected (rows with an explicit action are left alone).
- **Interactive**: rows can be flipped with `>`/`<`; `⚠` rows become
  actionable when flipped. Bulk actions prompt once for the `⚠` resolution,
  then a confirmation screen shows count + total size before anything runs.

## 4. Transfer

One `rsync` invocation per direction with a `--files-from` temporary file
(0600, deleted afterwards, binary-written with `surrogateescape`):

```
rsync -rt --mkpath --timeout=120 --from0 -i --info=progress2 \
      --files-from=<tmpfile> [-e "ssh -o BatchMode=yes -o ConnectTimeout=5"] \
      <host>:<remote_root>/  <local_root>/
```

- `-rt`: recurse + preserve mtimes (no owner/group/permission copies — not
  needed for documents, and avoids root).
- `--mkpath`: create missing parent directories on the destination.
- `--timeout=120`: idle timeout so a dead network fails instead of hanging;
  `-e` also sets `ConnectTimeout=5`. An overall wall-clock cap can be set
  with `stop_after_minutes` / `LAN_SYNC_STOP_AFTER` (rsync `--stop-after`;
  0 = unlimited).
- `--from0`: the file list is **NUL-delimited**. rsync's default list format
  treats NL *and CR* as record separators; `--from0` makes a filename
  containing CR (or any byte except NUL) transfer safely as one record.
  `valid_relpath` still rejects CR and other control characters as
  defense-in-depth and for display safety.
- `--files-from` entries are the validated relative paths; rsync interprets
  them relative to the source root (no `--relative`).
- `-i` (`--itemize-changes`): rsync emits one line per transferred file
  (`>f...`); the tool counts them so "done: N files applied" reports files
  **actually transferred**, not files merely listed.
- **Skip detection**: if rsync reports `skipping non-regular file`, the
  batch fails and state is not recorded. After the scan-side symlink
  exclusion this only happens on a TOCTOU swap (file replaced by a symlink
  or FIFO between scan and transfer) and must not be silently absorbed.
- rsync writes temp files and renames into place → atomic per file.

Progress: `--info=progress2` output is parsed for a `NN%` value to drive the
TUI status line. The progress line updates coarsely (rsync carriage-returns
between newlines); this is intentional.

## 5. Record

`state.json` maps `relative_path` → `{"l": [size, mtime], "r": [size, mtime]}`
as recorded after the last successful sync of that file, plus a `version`
field. Written atomically (tmp + `os.replace`, fsync'd, 0600) **only after**
the corresponding rsync batch succeeded — a failed batch leaves the old state
intact, so next run re-detects the transfer as pending. Entries for files
that no longer exist on either side are pruned on the next successful apply,
so the state file cannot grow without bound.

## Verify (`--verify`, `v` key)

For files classified `same` (near-equal mtime and equal size — the only case
mtime cannot distinguish), compare SHA-256 hashes:

- Local: chunked `hashlib.sha256` in-process.
- Remote: one SSH call
  `cd <remote_root> && xargs -0 -n 40 sha256sum -z -- 2>/dev/null; true`,
  candidate paths fed NUL-separated on **stdin**, each prefixed with `./`.
  The `--` end-of-options delimiter (POSIX) and the `./` prefix make names
  like `--check` or `-` hash as files instead of being misparsed as options
  or stdin. `-z` output (`<hash>␣␣<name>\0`) is NUL-split and parsed by
  `hash`/two-spaces/`name`, stripping the `./` prefix; `-z` disables
  coreutils' backslash escaping for tricky names. Files that cannot be
  parsed or hashed are ignored (never falsely marked as mismatched); a
  completely empty result for a non-empty input is treated as an error.
- Mismatch → the item becomes `⚠ unsure` and is logged.

Why `xargs`/`sha256sum -z` and not `--files0-from=-`: coreutils 9.10/9.11
(Fedora 44, Arch) do not ship `--files0-from`.

## Discovery (launcher `lan-sync.sh`)

Cascade: (1) SSH alias works as configured (cached IP in `~/.ssh/config`) →
(2) mDNS `host.local` → (3) TCP port-22 scan of the current subnet. See
[SECURITY.md](SECURITY.md) for why this cannot be spoofed into accepting an
impostor — in short: every probe verifies the candidate against the **pinned**
host key (`StrictHostKeyChecking=yes` + `HostKeyAlias`), no key is ever
auto-accepted (`accept-new` is never used), the pin is never erased
automatically, and `HostName` is only rewritten after a pin-verified probe
succeeded. First-ever use requires an explicit interactive pin
(`ssh -o StrictHostKeyChecking=ask <alias> true`); without a pin, discovery
refuses to run (and never does so silently in scripts). The probe command is
`grep -qis '<os_match>' /etc/os-release` — no file data crosses it.
`~/.ssh/config` rewrites preserve the original file mode (0600).

## Configuration

Resolution order per key: environment variable → `~/.config/lan-folder-sync/config.json` → built-in default. Values are validated: `host`/`remote_user` must match a safe charset (no leading `-`, no control characters), `remote_root` must be absolute, all values must be strings without control characters; invalid values fall back to the default and are logged. `stop_after_minutes` (int) / `LAN_SYNC_STOP_AFTER` sets the rsync wall-clock cap. The launcher resolves `host`/`remote_user`/`ssh_key`/`os_match` the same way (via a small embedded Python helper) and validates them before any connection, so discovery and transfer always agree.

## Development / testing hooks

`--simulate-local DIR --simulate-remote DIR` (hidden flags) treat both sides
as local directories: scans use `scan_local`, transfers use local rsync
without `-e ssh`, and remote hashing uses local files. Use them to test
classification and transfer logic without a network.

## Regression tests

`tests/run_tests.sh` runs the full suite (fixed-finding tests, python unit
tests, and ported verified-safe behaviors) against the tool in this repo,
with all scratch state under `/tmp/opencode/tests-regression`. Launcher
tests use stubbed `ssh`/`ssh-keygen`/`ip`/`timeout`/`getent` in a sandbox
`HOME` — the real network and real `~/.ssh` are never touched (the real
`ssh-keygen` resolves `known_hosts` via the passwd database, not `$HOME`,
so it must never run in tests). Run: `tests/run_tests.sh`; see the README's
Development section.

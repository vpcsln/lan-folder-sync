# Architecture

This document explains how lan-folder-sync works internally. It is aimed at
maintainers and curious users.

## Pipeline

```
scan (local walk + remote find)
   → classify (state-aware comparison)
   → decide (interactive TUI or bulk mode / --resolve)
   → transfer (rsync --files-from over SSH)
   → record (state file update, only on success)
```

## 1. Scan

- **Local**: `os.walk(..., followlinks=False)` + `os.lstat`. Symlinks are
  skipped. Paths are relative to `local_root`.
- **Remote**: a single SSH call
  `find <remote_root> -type f -printf '%P\0%T@\0%s\0'`.
  The format string is quoted with `shlex.quote` because `ssh` concatenates
  its arguments into a remote shell command — an unquoted `\0` would be eaten
  by the remote shell. Output is NUL-separated (`<path>\0<mtime>\0<size>\0`),
  parsed in triplets.
- Both sides decode filenames with `surrogateescape` (byte-exact, safe for
  non-UTF-8 names). Paths that are absolute, contain `..`, empty components,
  NUL or newlines are rejected and logged (`valid_relpath`). Newline rejection
  matters because `rsync --files-from` is line-based.

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

"Changed since last sync" detection is what makes `⚠` meaningful: two sides
can differ by minutes while *both* changed since the last sync, and only the
state file reveals that.

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
rsync -rt --mkpath --timeout=120 --info=progress2 \
      --files-from=<tmpfile> -e "ssh -o BatchMode=yes" \
      <host>:<remote_root>/  <local_root>/
```

- `-rt`: recurse + preserve mtimes (no owner/group/permission copies — not
  needed for documents, and avoids root).
- `--mkpath`: create missing parent directories on the destination.
- `--timeout=120`: idle timeout so a dead network fails instead of hanging.
- `--files-from` entries are the validated relative paths; rsync interprets
  them relative to the source root (no `--relative`).
- rsync writes temp files and renames into place → atomic per file.

Progress: `--info=progress2` output is parsed for a `NN%` value to drive the
TUI status line. The progress line updates coarsely (rsync carriage-returns
between newlines); this is intentional.

## 5. Record

`state.json` maps `relative_path` → `{"l": [size, mtime], "r": [size, mtime]}`
as recorded after the last successful sync of that file. Written atomically
(tmp + `os.replace`, fsync'd, 0600) **only after** the corresponding rsync
batch succeeded — a failed batch leaves the old state intact, so next run
re-detects the transfer as pending.

## Verify (`--verify`, `v` key)

For files classified `same` (near-equal mtime and equal size — the only case
mtime cannot distinguish), compare SHA-256 hashes:

- Local: chunked `hashlib.sha256` in-process.
- Remote: one SSH call
  `cd <remote_root> && xargs -0 -n 40 sha256sum -z 2>/dev/null; true`,
  candidate paths fed NUL-separated on **stdin** (no filename appears on any
  command line). `-z` output (`<hash>␣␣<name>\0`) is NUL-split and parsed by
  `hash`/two-spaces/`name`; `-z` disables coreutils' backslash escaping for
  tricky names. Files that cannot be parsed or hashed are ignored (never
  falsely marked as mismatched).
- Mismatch → the item becomes `⚠ unsure` and is logged.

Why `xargs`/`sha256sum -z` and not `--files0-from=-`: coreutils 9.10/9.11
(Fedora 44, Arch) do not ship `--files0-from`.

## Discovery (launcher `lan-sync.sh`)

Cascade: (1) SSH alias works as configured (cached IP in `~/.ssh/config`) →
(2) mDNS `host.local` → (3) TCP port-22 scan of the current subnet with per
candidate: key auth + `os_match` check in `/etc/os-release`. On success the
found IP is written to the `HostName` line of the SSH config (state for the
next run). See [SECURITY.md](SECURITY.md) for why this cannot be spoofed into
accepting an impostor.

## Configuration

Resolution order per key: environment variable → `~/.config/lan-folder-sync/config.json` → built-in default. See the README's configuration table. The launcher resolves `host`/`remote_user`/`ssh_key`/`os_match` the same way (via a small embedded Python helper), so discovery and transfer always agree.

## Development / testing hooks

`--simulate-local DIR --simulate-remote DIR` (hidden flags) treat both sides
as local directories: scans use `scan_local`, transfers use local rsync
without `-e ssh`, and remote hashing uses local files. Use them to test
classification and transfer logic without a network.

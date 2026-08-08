# lan-folder-sync

Bidirectional folder synchronisation between two Linux computers on the same
LAN, with a full-screen difference viewer, one-key bulk modes, and strict
"never delete anything" safety.

Instead of a plain mirror, the tool **shows you every difference at once**
(path, size, modification time on both sides), decides by itself when the
newest version is obvious, and **asks you only when it is not sure** (e.g. a
file that changed on both machines). Deletions are never performed.

```
$ lan-sync --list

Synchronising: /home/you/Dokumente/studium  ↔  cachyos:/home/vpc/Dokumente/studium
Scanned 2296 local / 2283 laptop files in 0.3 s · nothing is ever deleted

SUMMARY
  ⇣ 13 files (28.5M)   to copy FROM laptop      run: lan-sync --pull
  ⚠  2 files            changed on BOTH sides    run: lan-sync (interactive)
  ✓ 2283 files          identical

GROUP semester2/…/tempKlausur/   8 files · 26.3M
  ⇡ GGI2_Probeklausur24_Musterlösung_N...    12.7M  Jul 28 2025  new on this PC
  ...

CHANGED ON BOTH SIDES — need your decision
  ⚠ a2/unsure.txt
        here:    today 13:53 · 9B
        laptop:  today 13:53 · 8B

Next step: lan-sync --pull   (copies 13 files from the laptop)
```

## Features

- **Full-screen interactive viewer** (curses TUI): all differences at once,
  sortable, filterable, per-file direction overrides, selection
- **One-key bulk modes**: `1` pull everything from the laptop (no deletes),
  `2` push everything, `3` newest wins, `4` apply your selection
- **Asks only when unsure**: files changed on both sides (or with
  near-identical modification times) are flagged `⚠` and need a decision
- **Never deletes anything**, ever — files missing on one side are reported
  but never removed
- **Non-interactive modes** (`--pull`, `--push`, `--newest`, `--list`) for
  scripting and cron
- **`--verify`**: hashes files with equal mtime+size on both sides to catch
  hidden changes (e.g. same-second rewrites)
- **Automatic laptop discovery**: cached IP → mDNS (`host.local`) → subnet
  scan, verified by SSH key + OS identity — no reconfiguration when the DHCP
  address changes
- **Secure by design**: key-only SSH, pinned host keys (never auto-accepted
  or auto-erased), validated paths (no control characters, byte-exact
  non-UTF-8 names), display-safe output, no shell interpolation of
  filenames (see [SECURITY.md](SECURITY.md))
- **Atomic transfers** via `rsync` (temp file + rename), single-instance lock,
  crash-safe state bookkeeping

## Requirements

Both machines:

- Linux (any mainstream distro; developed on Fedora + CachyOS/Arch)
- Python 3.8+
- `rsync` ≥ 3.2.3 (for `--mkpath`)
- OpenSSH client (this machine) and server (`sshd` on the other machine)
- GNU `find` and `sha256sum` on the remote machine (standard on every distro)
- Optional: fish shell for the alias

## Quick start

### 1. Install the scripts

Clone or copy this project, then make the scripts available on `PATH`:

```bash
mkdir -p ~/bin
ln -s ~/projects/lan-folder-sync/lan-sync.py ~/bin/lan-sync.py
ln -s ~/projects/lan-folder-sync/lan-sync.sh ~/bin/lan-sync.sh
```

Optional fish alias:

```fish
alias lan-sync "$HOME/bin/lan-sync.sh"
```

### 2. Configure

Copy `config.example.json` to `~/.config/lan-folder-sync/config.json` and
adjust the values:

```bash
mkdir -p ~/.config/lan-folder-sync
cp config.example.json ~/.config/lan-folder-sync/config.json
```

| Key | Meaning | Default |
|-----|---------|---------|
| `host` | SSH alias of the other machine (see step 3) | `cachyos` |
| `remote_user` | username on the other machine | `vpc` |
| `local_root` | folder to sync on this machine | `~/Dokumente/studium` |
| `remote_root` | folder to sync on the other machine | `/home/vpc/Dokumente/studium` |
| `ssh_key` | SSH key used by discovery probes (transfers use `~/.ssh/config`) | `~/.ssh/id_ed25519_sync` |
| `os_match` | string that identifies the laptop in `/etc/os-release` (used by discovery) | `cachyos` |
| `stop_after_minutes` | wall-clock cap per transfer (rsync `--stop-after`; `0` = unlimited) | `0` |

Every setting can also be overridden by an environment variable:

| Env var | Overrides |
|---------|-----------|
| `LAN_SYNC_HOST` | `host` |
| `LAN_SYNC_REMOTE_USER` | `remote_user` |
| `LAN_SYNC_LOCAL_ROOT` | `local_root` |
| `LAN_SYNC_REMOTE_ROOT` | `remote_root` |
| `LAN_SYNC_SSH_KEY` | `ssh_key` |
| `LAN_SYNC_OS_MATCH` | `os_match` |
| `LAN_SYNC_STOP_AFTER` | `stop_after_minutes` |

Config and env values are validated (safe character sets, absolute remote
root, no control characters); invalid values fall back to the defaults and
are logged.

If no config file exists, the defaults in the table above are used — the tool
works out of the box for a CachyOS laptop with user `vpc`.

### 3. One-time setup on the other machine

```bash
# on the other machine (e.g. CachyOS)
sudo pacman -S openssh rsync   # or your distro's packages
sudo systemctl enable --now sshd
mkdir -p /home/<user>/Dokumente/studium   # create the remote folder
```

```bash
# on this machine: passwordless SSH with a dedicated key
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_sync -N ""
ssh-copy-id -i ~/.ssh/id_ed25519_sync.pub <user>@<ip-of-other-machine>
```

Add an SSH config entry so the tool (and discovery) finds the machine:

```
Host cachyos
    HostName <ip-or-hostname>
    User <user>
    IdentityFile ~/.ssh/id_ed25519_sync
    IdentitiesOnly yes
    ConnectTimeout 5
    AddressFamily inet
    HostKeyAlias cachyos
```

`HostKeyAlias` is important: it pins the laptop's host key under a stable
name, so a changing DHCP address never breaks host-key verification.

### 4. First run

```bash
lan-sync.sh --check   # discovery + connection check
lan-sync --check      # verify connection and unison-free pipeline
lan-sync --list       # read-only difference report
lan-sync              # interactive viewer
```

On the very first run the laptop's host key is not pinned yet. The launcher
then shows you the machine's fingerprint and asks you to confirm it
interactively (it refuses to auto-accept keys — there is no
trust-on-first-use). If you run it from a script or cron, pin the key once
by hand instead:

```bash
ssh -o StrictHostKeyChecking=ask cachyos true   # verify the fingerprint, answer yes
```

The first sync run has no history, so files differing on both sides with
similar mtimes are reported as `⚠` and you decide. After the first successful
sync, a state file enables real conflict detection ("changed on both sides
since the last sync").

## CLI reference

| Option | Description |
|--------|-------------|
| *(no args)* | Open the interactive viewer (TUI) |
| `--check` | Test SSH connection + remote folder, exit |
| `--list` | Print the grouped difference report, change nothing |
| `--list --plain` | One plain line per differing file (for scripts) |
| `--pull` | Copy everything newer/only on the remote to this machine, delete nothing |
| `--push` | Copy everything newer/only on this machine to the remote, delete nothing |
| `--newest` | Apply the newest version (by mtime) everywhere |
| `--verify` | Hash equal-mtime+size files on both sides, flag content mismatches as `⚠` |
| `--resolve newest\|local\|remote\|skip` | Resolution for `⚠` files in non-interactive modes |
| `--reset-state` | Forget sync history (safe: nothing is deleted, next run re-compares) |

## Interactive viewer (TUI) reference

```
L: /home/you/Dokumente/studium   R: cachyos:/home/vpc/Dokumente/studium
  ⇣ 59 (1.2 GB) in   ⇡ 13 (184 MB) out   ⚠ 2 unsure   ✓ 2203 same   filter: actionable   verify: off
⇣  semester2/…/klausuren/2026-07-11-Notiz-14-57.xopp    9.2M  Jul 29 19:10   |       - -
...
[1] pull all  [2] push all  [3] newest wins  [4] apply selection  space select  >/< force dir  arrows move  n/u/a filter  h help  q quit
```

| Key | Action |
|-----|--------|
| `1` | Pull all: copy everything newer/only on the laptop here (no deletes) |
| `2` | Push all: copy everything newer/only here to the laptop (no deletes) |
| `3` | Newest wins everywhere (`⚠` files: one prompt, then apply) |
| `4` / `Enter` | Apply the rows you selected with `space` |
| `space` | Select / deselect the row under the cursor |
| `>` / `<` | Force the row: keep the laptop / local version (resolves `⚠` rows) |
| arrows, PgUp/PgDn/Home/End | Move the cursor |
| `n` / `u` / `a` | Filter: new only / unsure only / all rows |
| `v` | Toggle content verification (hashes equal-mtime files, ~30 s on large trees) |
| `h` / `?` | Help screen |
| `q` | Quit without changing anything |

| Icon | Meaning |
|------|---------|
| `⇣` | Will copy **FROM** the laptop (pull) |
| `⇡` | Will copy **TO** the laptop (push) |
| `⚠` | Changed on **both** sides — needs a decision |
| `✓` | Identical (shown in the `all` filter) |

Before anything runs you get a confirmation with the file count and total
size; nothing is written until you confirm.

## How it works (short version)

1. **Scan**: walk the local tree; fetch the remote tree in one SSH call
   (`find -printf`, NUL-separated, byte-safe for non-UTF-8 filenames)
2. **Classify** each file: only on one side → new; mtime differs by more than
   the 2 s threshold → newer side wins; both sides changed since the last
   sync (state file) or near-equal mtimes → `⚠` unsure
3. **Decide**: you (bulk key or per-row), or the `--resolve` flag
4. **Transfer**: one `rsync --files-from` batch per direction over SSH
   (atomic temp+rename, `--mkpath` for parent dirs)
5. **Record**: the state file is updated only for successfully transferred
   files, so a failure can never mark unsynced files as synced

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full details.

## Troubleshooting

**"ERROR: laptop not found."** — the machine is not reachable:
- Is it on the same network and is `sshd` running there?
  (`sudo systemctl enable --now sshd`)
- Is your key installed? (`ssh-copy-id -i ~/.ssh/id_ed25519_sync.pub user@ip`)
- Did the laptop's host key change (reinstall)? Discovery refuses machines
  whose key does not match the pinned one. Re-pin manually after verifying
  the new fingerprint:
  `ssh-keygen -R cachyos && ssh -o StrictHostKeyChecking=ask cachyos true`
- IPv6-only network? Discovery's subnet scan and mDNS filtering are IPv4;
  set a fixed `HostName` in `~/.ssh/config` instead.
- University/guest Wi-Fi (eduroam) often blocks direct device connections —
  check with `ping <ip>`; if ping works but port 22 is blocked, a firewall on
  the remote machine is the likely cause (`sudo ufw allow 22/tcp`).

**"nothing to do"** — that is correct behaviour: with no differences in the
chosen direction there is nothing to apply. Use `--list` to see the report.

**Filenames with weird characters** (e.g. a Windows-1252 `ö` displayed as
`�`): files are compared and transferred byte-exact; only the *display* shows
a replacement character.

**A file changed on both sides** — it is marked `⚠`. Decide per file (`>`/`<`)
or once for all (`3` or `--resolve newest`). "Newest" means highest mtime;
with identical mtimes the file is skipped.

## Limitations & design choices

- **No deletions, ever** — by design. Missing files are reported but never
  removed; use another tool (or `rsync --delete` by hand) if you need mirrors.
- **mtime+size based fast-check** like unison's `fastcheck`; equal mtime and
  size are assumed identical. Use `--verify` (or the `v` key) to hash-compare
  them.
- **Per-second mtime resolution** on some filesystems: two edits within the
  same second are treated as near-equal (`⚠` asks) unless `--verify` confirms
  them.
- The tool is single-instance (file lock); concurrent runs refuse to start.
- Transfers go through your own SSH key; the script never stores or prompts
  for passwords.
- No cross-machine lock: two machines syncing the same remote folder at the
  same time are not coordinated (per-file atomic renames keep individual
  files consistent).

## Development

Run the regression suite (needs only Python 3, rsync, and standard shell
tools; it never touches the network or your real `~/.ssh`):

```bash
tests/run_tests.sh
```

The suite covers every security fix (hostile filenames, symlinks, state
tampering, state-dir symlink attacks, discovery impostor rejection, config
validation, terminal-escape safety, log rotation, …) plus the verified-safe
behaviors (argv-only command construction, NUL-delimited file lists, byte
round-trips, lock semantics, `--verify`). Launcher tests run in a sandbox
`HOME` with stubbed `ssh`/`ssh-keygen`/`ip`/`timeout`/`getent` — the real
`ssh-keygen` resolves `known_hosts` via the passwd database (not `$HOME`),
so it must never be executed by the tests. Test trees live under
`/tmp/opencode/tests-regression`.

## License

GPL-3.0 — see [LICENSE](LICENSE).

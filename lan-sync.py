#!/usr/bin/env python3
# lan-folder-sync - bidirectional LAN folder sync with interactive comparison.
# Copyright (C) 2026  the author
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
import argparse
import curses
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import datetime

APP_NAME = "lan-folder-sync"
DEFAULT_HOST = "cachyos"
DEFAULT_REMOTE_USER = "vpc"
DEFAULT_LOCAL_ROOT = "~/Dokumente/studium"
DEFAULT_REMOTE_ROOT = "/home/vpc/Dokumente/studium"
DEFAULT_SSH_KEY = "~/.ssh/id_ed25519_sync"
THRESHOLD = 2.0
CHANGE_EPS = 0.5
STATE_VERSION = 1
MAX_STATE_BYTES = 64 << 20    # refuse oversized state files (DoS guard)
MAX_LOG_BYTES = 1 << 20       # rotate the log file past 1 MiB
STOP_AFTER = 0                # rsync --stop-after minutes; 0 = unlimited
HOST_PAT = re.compile(r"^[A-Za-z0-9._-]+$")
USER_PAT = re.compile(r"^[A-Za-z0-9._-]+$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

HOST = DEFAULT_HOST
REMOTE_USER = DEFAULT_REMOTE_USER
LOCAL_ROOT = os.path.expanduser(DEFAULT_LOCAL_ROOT)
REMOTE_ROOT = DEFAULT_REMOTE_ROOT
SSH_KEY = os.path.expanduser(DEFAULT_SSH_KEY)
STATE_DIR = os.path.expanduser("~/.local/share/" + APP_NAME)
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "log")
LOCK_FILE = os.path.join(STATE_DIR, "lock")


def load_config():
    global HOST, REMOTE_USER, LOCAL_ROOT, REMOTE_ROOT, SSH_KEY
    global STATE_DIR, STATE_FILE, LOG_FILE, LOCK_FILE, STOP_AFTER
    cfg = {}
    path = os.path.join(os.path.expanduser("~/.config"), APP_NAME, "config.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        pass
    if not isinstance(cfg, dict):
        cfg = {}

    notes = []

    def pick(key, env, default, pattern=None, absolute=False):
        """env -> config -> default, validating the chosen value.
        Invalid values (non-string, control chars, pattern mismatch,
        non-absolute paths) are rejected with a log note and the default
        is used instead."""
        raw = os.environ.get(env)
        if raw is None:
            raw = cfg.get(key)
        if isinstance(raw, str) and raw and not CONTROL_RE.search(raw) \
                and (pattern is None or pattern.match(raw)) \
                and (not absolute or raw.startswith("/")):
            return raw
        notes.append("config: invalid value for %s (using default)" % key)
        return default

    HOST = pick("host", "LAN_SYNC_HOST", DEFAULT_HOST, HOST_PAT)
    if HOST.startswith("-"):
        HOST = DEFAULT_HOST
        notes.append("config: invalid value for host (using default)")
    REMOTE_USER = pick("remote_user", "LAN_SYNC_REMOTE_USER", DEFAULT_REMOTE_USER, USER_PAT)
    LOCAL_ROOT = os.path.abspath(os.path.expanduser(
        pick("local_root", "LAN_SYNC_LOCAL_ROOT", DEFAULT_LOCAL_ROOT)))
    REMOTE_ROOT = pick("remote_root", "LAN_SYNC_REMOTE_ROOT", DEFAULT_REMOTE_ROOT,
                       absolute=True)
    SSH_KEY = os.path.abspath(os.path.expanduser(
        pick("ssh_key", "LAN_SYNC_SSH_KEY", DEFAULT_SSH_KEY)))
    state_dir = os.path.abspath(os.path.expanduser(
        pick("state_dir", "LAN_SYNC_STATE_DIR", "~/.local/share/" + APP_NAME)))
    STATE_DIR = state_dir
    STATE_FILE = os.path.join(STATE_DIR, "state.json")
    LOG_FILE = os.path.join(STATE_DIR, "log")
    LOCK_FILE = os.path.join(STATE_DIR, "lock")
    try:
        raw_stop = os.environ.get("LAN_SYNC_STOP_AFTER")
        if raw_stop is None:
            raw_stop = cfg.get("stop_after_minutes", "0")
        STOP_AFTER = max(0, int(raw_stop))
    except (TypeError, ValueError):
        STOP_AFTER = 0
        notes.append("config: invalid stop_after_minutes (using 0 = unlimited)")
    for n in notes:
        log(n)


class SyncError(Exception):
    pass


def safe_text(s):
    """Byte-safe, control-free text for display (no truncation)."""
    s = s.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return "".join(ch if ch >= " " and ch != "\x7f" else "?" for ch in s)


def disp_width(s):
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def trunc_disp(s, width):
    if width <= 0:
        return ""
    w = 0
    out = []
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width:
            break
        w += cw
        out.append(ch)
    return "".join(out)


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# rsync prints this (in English, even under de_DE locale on this platform)
# when a --files-from entry is a symlink/fifo/device instead of a regular
# file — i.e. a TOCTOU swap after the scan. It must fail the batch.
SKIP_RE = re.compile(r"skipping non-regular file")


def disp_len(s):
    """Display width of a string with ANSI SGR sequences stripped."""
    return disp_width(ANSI_RE.sub("", s))


def ensure_state_dir():
    """Create/harden the state directory: must be a real directory owned by
    the current user, mode 0700, never a symlink (CWE-59)."""
    try:
        st = os.lstat(STATE_DIR)
    except FileNotFoundError:
        try:
            os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        except OSError as e:
            raise SyncError("cannot create state directory %s: %s" % (STATE_DIR, e))
        st = os.lstat(STATE_DIR)
    except OSError as e:
        raise SyncError("cannot access state directory %s: %s" % (STATE_DIR, e))
    if stat.S_ISLNK(st.st_mode):
        raise SyncError("state directory %s is a symlink; refusing" % STATE_DIR)
    if not stat.S_ISDIR(st.st_mode):
        raise SyncError("state path %s is not a directory" % STATE_DIR)
    if st.st_uid != os.geteuid():
        raise SyncError("state directory %s is not owned by the current user" % STATE_DIR)
    try:
        os.chmod(STATE_DIR, 0o700)
    except OSError:
        pass


def open_nofollow(path, mode, perms=0o600):
    """open() that refuses to follow symlinks (O_NOFOLLOW)."""
    flags = {"r": os.O_RDONLY,
             "w": os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
             "a": os.O_WRONLY | os.O_CREAT | os.O_APPEND}[mode[0]]
    flags |= getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, perms)
    return os.fdopen(fd, mode, encoding="utf-8", errors="replace")


def log(msg):
    try:
        ensure_state_dir()
        try:
            if os.path.getsize(LOG_FILE) > MAX_LOG_BYTES:
                try:
                    os.unlink(LOG_FILE + ".old")
                except OSError:
                    pass
                os.replace(LOG_FILE, LOG_FILE + ".old")
        except OSError:
            pass
        with open_nofollow(LOG_FILE, "a") as f:
            f.write("%s %s\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                 safe_text(str(msg))))
    except (OSError, SyncError):
        pass


def human_size(n):
    if n is None:
        return "-"
    for unit in ("B", "K", "M", "G", "T"):
        if n < 1024 or unit == "T":
            return "%d%s" % (n, unit) if unit == "B" else "%.1f%s" % (n, unit)
        n /= 1024.0
    return str(n)


def human_date(t):
    if t is None:
        return "-"
    d = datetime.fromtimestamp(t)
    now = datetime.now()
    if d.date() == now.date():
        return "today %02d:%02d" % (d.hour, d.minute)
    if d.year == now.year:
        return d.strftime("%b %d %H:%M")
    return d.strftime("%b %d %Y")


def valid_relpath(p):
    if not p or p.startswith("/"):
        return False
    for part in p.split("/"):
        if part in ("", ".", ".."):
            return False
    # reject all C0 control characters (NUL, newline, CR, ESC, tab, ...)
    # and DEL: they break line-based tools, inject terminal sequences, and
    # are never legitimately needed in synced filenames (CWE-116)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in p):
        return False
    return True


def ssh(args, timeout=None):
    cmd = ["ssh", "-o", "BatchMode=yes", HOST] + args
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise SyncError("ssh to %s timed out" % HOST)


def check_connection():
    r = ssh(["true"], timeout=10)
    if r.returncode != 0:
        raise SyncError("no SSH connection to %s" % HOST)
    r = ssh(["test -d %s" % shlex.quote(REMOTE_ROOT)], timeout=10)
    if r.returncode != 0:
        raise SyncError("remote directory %s not accessible" % REMOTE_ROOT)


def scan_local(root):
    out = {}
    onerr = lambda e: log("walk error: %s" % e)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=onerr):
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root)
            if not valid_relpath(rel):
                log("skip local path (invalid): %r" % rel)
                continue
            try:
                st = os.lstat(full)
            except OSError:
                continue
            # regular files only, matching the remote `find -type f` view;
            # symlinks (and fifos/devices) are never treated as files (F2)
            if not stat.S_ISREG(st.st_mode):
                continue
            out[rel] = (st.st_size, st.st_mtime)
    return out


def scan_remote():
    fmt = "%P\\0%T@\\0%s\\0"
    cmd = "find %s -type f -printf '%s'" % (shlex.quote(REMOTE_ROOT), fmt)
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd],
                           capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise SyncError("remote scan timed out")
    if r.returncode != 0:
        raise SyncError("remote scan failed: %s" % r.stderr.decode(errors="replace")[:300])
    data = r.stdout.split(b"\0")
    out = {}
    i = 0
    while i + 2 < len(data):
        p = data[i].decode("utf-8", "surrogateescape")
        t = data[i + 1].decode("utf-8", "surrogateescape")
        s = data[i + 2].decode("utf-8", "surrogateescape")
        i += 3
        if not p:
            continue
        if not valid_relpath(p):
            log("skip remote path (invalid): %r" % p)
            continue
        try:
            out[p] = (int(float(s)), float(t))
        except ValueError:
            log("skip remote path (bad metadata): %r" % p)
    return out


def validate_state(data):
    """Return a safe copy of the state dict: entries must be dicts with
    "l"/"r" as [size:int, mtime:number]. Malformed entries are dropped with
    a log line; an unknown future "version" invalidates the whole file."""
    if not isinstance(data, dict):
        log("state: ignoring non-dict state file")
        return {}
    version = data.get("version")
    if isinstance(version, int) and version > STATE_VERSION:
        log("state: unknown state version %r; ignoring" % version)
        return {}
    out = {}
    for k, v in data.items():
        if k == "version":
            if isinstance(v, int):
                out[k] = v
            continue
        if not isinstance(k, str) or not isinstance(v, dict):
            log("state: skipping invalid entry %r" % k)
            continue
        ok = True
        for side in ("l", "r"):
            e = v.get(side)
            if e is None:
                continue  # missing side is legal (file absent on that side)
            if not (isinstance(e, list) and len(e) == 2
                    and isinstance(e[0], int)
                    and isinstance(e[1], (int, float))):
                ok = False
                break
        if not ok:
            log("state: skipping invalid entry %r" % k)
            continue
        out[k] = v
    return out


def load_state():
    try:
        st = os.lstat(STATE_FILE)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_STATE_BYTES:
            log("state: ignoring non-regular or oversized state file")
            return {}
        with open_nofollow(STATE_FILE, "r") as f:
            return validate_state(json.load(f))
    except (OSError, ValueError):
        return {}


def save_state(state):
    ensure_state_dir()
    state = dict(state)
    state["version"] = STATE_VERSION
    tmp = STATE_FILE + ".tmp"
    try:
        with open_nofollow(tmp, "w") as f:
            json.dump(state, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, STATE_FILE)
    except OSError as e:
        raise SyncError("cannot write state file: %s" % e)


def classify(left, right, state):
    items = []
    if not isinstance(state, dict):
        state = {}
    paths = set(left) | set(right)
    for p in sorted(paths):
        sl, ml = left.get(p, (None, None))
        sr, mr = right.get(p, (None, None))
        entry = state.get(p)
        if not isinstance(entry, dict):
            entry = None
        if sl is None:
            items.append({"path": p, "sl": None, "ml": None, "sr": sr, "mr": mr,
                          "kind": "new_right", "act": "pull"})
            continue
        if sr is None:
            items.append({"path": p, "sl": sl, "ml": ml, "sr": None, "mr": None,
                          "kind": "new_left", "act": "push"})
            continue
        if entry is None:
            if mr - ml > THRESHOLD:
                act, kind = "pull", "newer_right"
            elif ml - mr > THRESHOLD:
                act, kind = "push", "newer_left"
            elif sl == sr:
                act, kind = None, "same"
            else:
                act, kind = None, "unsure"
            items.append({"path": p, "sl": sl, "ml": ml, "sr": sr, "mr": mr,
                          "kind": kind, "act": act})
            continue
        cl = entry.get("l") is None or abs(ml - entry["l"][1]) > CHANGE_EPS
        cr = entry.get("r") is None or abs(mr - entry["r"][1]) > CHANGE_EPS
        if cl and cr:
            act, kind = None, "unsure"
        elif cr:
            act, kind = "pull", "changed_right"
        elif cl:
            act, kind = "push", "changed_left"
        else:
            act, kind = None, "same"
        items.append({"path": p, "sl": sl, "ml": ml, "sr": sr, "mr": mr,
                      "kind": kind, "act": act})
    return items


def choose_bulk(items, mode, resolve):
    for it in items:
        if it["kind"] == "unsure":
            if it["act"] is not None:
                continue
            if mode == "pull":
                it["act"] = "pull" if resolve == "remote" else None
            elif mode == "push":
                it["act"] = "push" if resolve == "local" else None
            else:
                if resolve == "remote":
                    it["act"] = "pull"
                elif resolve == "local":
                    it["act"] = "push"
                elif resolve == "skip":
                    it["act"] = None
                elif it["mr"] > it["ml"]:
                    it["act"] = "pull"
                elif it["ml"] > it["mr"]:
                    it["act"] = "push"
                else:
                    it["act"] = None
            continue
        if mode == "pull" and it["act"] == "push":
            it["act"] = None
        elif mode == "push" and it["act"] == "pull":
            it["act"] = None
    return [it for it in items if it["act"]]


def run_rsync(paths, direction, simulate_remote, progress_cb):
    if not paths:
        return 0
    ensure_state_dir()
    tmp = tempfile.NamedTemporaryFile(mode="wb", dir=STATE_DIR, prefix="files-", delete=False)
    try:
        # NUL-delimited list (rsync --from0): no NL/CR record splitting (F5)
        for p in sorted(paths):
            tmp.write(p.encode("utf-8", "surrogateescape") + b"\0")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.chmod(tmp.name, 0o600)
        args = ["rsync", "-rt", "--mkpath", "--timeout=120", "--from0", "-i",
                "--info=progress2", "--files-from=" + tmp.name]
        if STOP_AFTER > 0:
            args.append("--stop-after=%d" % STOP_AFTER)
        if simulate_remote:
            if direction == "pull":
                args += [simulate_remote.rstrip("/") + "/", LOCAL_ROOT.rstrip("/") + "/"]
            else:
                args += [LOCAL_ROOT.rstrip("/") + "/", simulate_remote.rstrip("/") + "/"]
        else:
            args += ["-e", "ssh -o BatchMode=yes -o ConnectTimeout=5"]
            if direction == "pull":
                args += ["%s:%s/" % (HOST, REMOTE_ROOT.rstrip("/")), LOCAL_ROOT.rstrip("/") + "/"]
            else:
                args += [LOCAL_ROOT.rstrip("/") + "/", "%s:%s/" % (HOST, REMOTE_ROOT.rstrip("/"))]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors="replace")
        transferred = 0
        skipped = False
        try:
            last = 0
            prog = re.compile(r"(\d+)%")
            for line in proc.stdout:
                if SKIP_RE.search(line):
                    skipped = True
                # rsync -i itemize: ">f..." = regular file transferred
                if line.startswith(">f"):
                    transferred += 1
                m = prog.search(line)
                if m:
                    last = int(m.group(1))
                if progress_cb:
                    progress_cb(last, line.rstrip())
        finally:
            # never leave an orphan rsync behind on KeyboardInterrupt (F11)
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        if skipped:
            raise SyncError(
                "rsync %s: a listed file was skipped (non-regular); "
                "refusing to record state" % direction)
        if proc.returncode != 0:
            raise SyncError("rsync %s failed (%d)" % (direction, proc.returncode))
        return transferred
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_remote(paths, simulate_remote):
    if simulate_remote:
        out = {}
        for p in paths:
            try:
                out[p] = sha256_file(os.path.join(simulate_remote, p))
            except OSError:
                pass
        return out
    payload = b"".join(("./" + p).encode("utf-8", "surrogateescape") + b"\0"
                       for p in sorted(paths))
    # '--' = POSIX end-of-options (OWASP); './' prefix makes even a file
    # literally named "-" hash as a file, not stdin (coreutils special case)
    cmd = ("cd %s && xargs -0 -n 40 sha256sum -z -- 2>/dev/null; true"
           % shlex.quote(REMOTE_ROOT))
    try:
        r = subprocess.run(["ssh", "-o", "BatchMode=yes", HOST, cmd], input=payload,
                           capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        raise SyncError("remote hashing timed out")
    if r.returncode != 0:
        raise SyncError("remote hashing failed: %s" % r.stderr.decode(errors="replace")[:300])
    out = {}
    for rec in r.stdout.split(b"\0"):
        if not rec:
            continue
        h, sep, name = rec.partition(b"  ")
        if len(h) != 64 or not sep:
            continue
        if name.startswith(b"./"):
            name = name[2:]
        p = name.decode("utf-8", "surrogateescape")
        if not valid_relpath(p):
            continue
        out[p] = h.decode("ascii", "replace")
    if paths and not out:
        raise SyncError("remote hashing produced no results")
    return out


def verify_contents(left, right, items, simulate_remote):
    cands = [it for it in items if it["kind"] == "same"]
    if not cands:
        return
    paths = [it["path"] for it in cands]
    lh = {}
    for p in paths:
        try:
            lh[p] = sha256_file(os.path.join(LOCAL_ROOT, p))
        except OSError:
            pass
    rh = hash_remote(paths, simulate_remote)
    for it in cands:
        l, r = lh.get(it["path"]), rh.get(it["path"])
        if l and r and l != r:
            it["kind"] = "unsure"
            it["act"] = None
            log("content mismatch: %s" % safe_text(it["path"]))


def apply_transfers(items, simulate_remote, progress_cb=None):
    pulls = [it for it in items if it["act"] == "pull"]
    pushes = [it for it in items if it["act"] == "push"]
    state = load_state()
    pulled = pushed = 0
    if pulls:
        pulled = run_rsync([it["path"] for it in pulls], "pull", simulate_remote, progress_cb)
        for it in pulls:
            state[it["path"]] = {"l": [it["sr"], it["mr"]], "r": [it["sr"], it["mr"]]}
    if pushes:
        pushed = run_rsync([it["path"] for it in pushes], "push", simulate_remote, progress_cb)
        for it in pushes:
            state[it["path"]] = {"l": [it["sl"], it["ml"]], "r": [it["sl"], it["ml"]]}
    if pulls or pushes:
        # prune state entries for files that no longer exist on either side
        live = {it["path"] for it in items}
        state = {k: v for k, v in state.items() if k == "version" or k in live}
        save_state(state)
    return pulled, pushed


ICON_PULL = "\u21e3"
ICON_PUSH = "\u21e1"
ICON_UNSURE = "\u26a0"
ICON_SAME = "\u2713"
C_BOLD = "\033[1m"
C_BLUE = "\033[94m"
C_YELLOW = "\033[93m"
C_RED = "\033[91m"
C_DIM = "\033[2m"
C_RESET = "\033[0m"


def item_icon(it):
    if it["act"] == "pull":
        return ICON_PULL
    if it["act"] == "push":
        return ICON_PUSH
    if it["kind"] == "unsure":
        return ICON_UNSURE
    if it["kind"] == "same":
        return ICON_SAME
    return " "


def annotation(it):
    k = it["kind"]
    if k in ("new_right", "newer_right", "changed_right"):
        return "new on laptop" if k == "new_right" else "newer on laptop"
    if k in ("new_left", "newer_left", "changed_left"):
        return "new on this PC" if k == "new_left" else "newer on this PC"
    return ""


def fmt_row(it):
    line = "%s  %-22s %9s %s   |   %9s %s" % (
        item_icon(it), it["path"], human_size(it["sl"]), human_date(it["ml"]),
        human_size(it["sr"]), human_date(it["mr"]))
    return safe_text(line)


def sanitize(s, width):
    s = safe_text(s)
    if disp_width(s) > width:
        s = trunc_disp(s, max(0, width - 3)) + "..."
    return s


def collapse_path(p, width):
    p = safe_text(p)
    if width <= 4:
        return "..." if p else ""
    if disp_width(p) <= width:
        return p
    parts = p.split("/")
    if len(parts) <= 2:
        return trunc_disp(p, max(0, width - 3)) + "..."
    head, tail = parts[0], parts[-1]
    out = head
    for part in parts[1:-1]:
        cand = out + "/" + part
        if disp_width(cand) + disp_width(tail) + 6 <= width:
            out = cand
        else:
            break
    if disp_width(out) + disp_width(tail) + 4 <= width:
        return out + "/\u2026/" + tail
    return out


def report(items, color, scan_seconds):
    try:
        width = shutil.get_terminal_size().columns
    except OSError:
        width = 100
    width = max(60, width)

    def st(t, code=None):
        return code + t + C_RESET if color and code else t

    pulls = [i for i in items if i["act"] == "pull"]
    pushes = [i for i in items if i["act"] == "push"]
    unsures = [i for i in items if i["kind"] == "unsure"]
    sames = [i for i in items if i["kind"] == "same"]

    def total(itlist, key):
        return sum(i[key] or 0 for i in itlist)

    def files(n):
        return "%d file%s" % (n, "" if n == 1 else "s")

    def item_line(it):
        icon = st(ICON_PULL, C_BLUE) if it["act"] == "pull" else st(ICON_PUSH, C_YELLOW)
        name = safe_text(it["path"].split("/")[-1])
        size = human_size(it["sr"] if it["act"] == "pull" else it["sl"])
        date = human_date(it["mr"] if it["act"] == "pull" else it["ml"])
        ann = annotation(it)
        prefix = "  %s %s" % (icon, name)
        suffix = "  %8s  %s  %s" % (size, date, ann)
        avail = max(20, width - disp_len(suffix))
        if disp_len(prefix) > avail:
            # truncate by display width, ignoring ANSI codes in the icon
            budget = max(1, avail - disp_len("  " + icon + " ") - 3)
            name = trunc_disp(name, budget) + "..."
            prefix = "  %s %s" % (icon, name)
        return prefix + suffix

    lines = []
    if not (pulls or pushes or unsures):
        lines.append(st("Synchronising: %s  \u2194  %s:%s" % (LOCAL_ROOT, HOST, REMOTE_ROOT), C_BOLD))
        lines.append("No differences \u2014 everything is in sync.")
        print("\n".join(lines))
        return

    nl = sum(1 for i in items if i["sl"] is not None)
    nr = sum(1 for i in items if i["sr"] is not None)
    lines.append(st("Synchronising: %s  \u2194  %s:%s" % (LOCAL_ROOT, HOST, REMOTE_ROOT), C_BOLD))
    lines.append("Scanned %d local / %d laptop files in %.1f s \u00b7 nothing is ever deleted" % (nl, nr, scan_seconds))
    lines.append("")
    lines.append(st("SUMMARY", C_BOLD))
    if pulls:
        lines.append("  %s %s (%s)   to copy FROM laptop      run: lan-sync --pull" % (
            st(ICON_PULL, C_BLUE), files(len(pulls)), human_size(total(pulls, "sr"))))
    if pushes:
        lines.append("  %s %s (%s)   to copy TO laptop        run: lan-sync --push" % (
            st(ICON_PUSH, C_YELLOW), files(len(pushes)), human_size(total(pushes, "sl"))))
    if unsures:
        lines.append("  %s %s            changed on BOTH sides    run: lan-sync (interactive)" % (
            st(ICON_UNSURE, C_RED), files(len(unsures))))
    lines.append("  %s %s            identical" % (st(ICON_SAME, C_DIM), files(len(sames))))

    grouped = {}
    for i in pulls + pushes:
        d = os.path.dirname(i["path"]) or "(root)"
        grouped.setdefault(d, []).append(i)

    def group_bytes(its):
        return sum((i["sr"] if i["act"] == "pull" else i["sl"]) or 0 for i in its)

    for d, its in sorted(grouped.items(), key=lambda kv: -group_bytes(kv[1])):
        lines.append("")
        lines.append(st("GROUP %s/   %s \u00b7 %s" % (collapse_path(d, width // 2), files(len(its)), human_size(group_bytes(its))), C_BOLD))
        for it in sorted(its, key=lambda i: i["path"])[:15]:
            lines.append(item_line(it))
        if len(its) > 15:
            lines.append("  \u2026 and %d more" % (len(its) - 15))

    if unsures:
        lines.append("")
        lines.append(st("CHANGED ON BOTH SIDES \u2014 need your decision", C_RED))
        for it in sorted(unsures, key=lambda i: i["path"]):
            lines.append("  %s %s" % (st(ICON_UNSURE, C_RED), collapse_path(it["path"], width - 4)))
            lines.append("        here:    %s \u00b7 %s" % (human_date(it["ml"]), human_size(it["sl"])))
            lines.append("        laptop:  %s \u00b7 %s" % (human_date(it["mr"]), human_size(it["sr"])))
        lines.append("        resolve:  lan-sync --resolve newest|local|remote|skip")

    lines.append("")
    if pulls:
        lines.append(st("Next step: lan-sync --pull   (copies %s from the laptop)" % files(len(pulls)), C_BOLD))
    elif unsures:
        lines.append(st("Next step: lan-sync   (review the unsure files)", C_BOLD))
    elif pushes:
        lines.append(st("Next step: lan-sync --push   (copies %s to the laptop)" % files(len(pushes)), C_BOLD))
    print("\n".join(lines))


class App:
    def __init__(self, items, simulate_remote):
        self.items = items
        self.filter = "actionable"
        self.sel = set()
        self.cursor = 0
        self.scroll = 0
        self.msg = ""
        self.sim = simulate_remote
        self.ask_resolve = "newest"
        self.verify = False

    def visible(self):
        if self.filter == "all":
            return self.items
        if self.filter == "new":
            return [i for i in self.items if i["kind"] in ("new_left", "new_right")]
        if self.filter == "unsure":
            return [i for i in self.items if i["kind"] == "unsure"]
        return [i for i in self.items if i["act"]]

    def counts(self):
        c = {"pull": 0, "push": 0, "unsure": 0, "same": 0, "pull_b": 0, "push_b": 0}
        for i in self.items:
            if i["act"]:
                c[i["act"]] += 1
                if i["act"] == "pull":
                    c["pull_b"] += i["sr"] or 0
                else:
                    c["push_b"] += i["sl"] or 0
            elif i["kind"] == "unsure":
                c["unsure"] += 1
            elif i["kind"] == "same":
                c["same"] += 1
        return c

    def move_cursor(self, delta):
        vis = self.visible()
        if not vis:
            self.cursor = 0
            return
        self.cursor = max(0, min(len(vis) - 1, self.cursor + delta))

    def clamp_view(self, h):
        vis = self.visible()
        if not vis:
            self.scroll = 0
            self.cursor = 0
            return
        self.cursor = max(0, min(len(vis) - 1, self.cursor))
        rows = max(1, h - 4)
        if self.cursor < self.scroll:
            self.scroll = self.cursor
        elif self.cursor >= self.scroll + rows:
            self.scroll = self.cursor - rows + 1

    def draw(self, scr):
        try:
            h, w = scr.getmaxyx()
            if h < 3 or w < 10:
                return
            scr.erase()
            c = self.counts()
            header = "L: %s   R: %s:%s" % (LOCAL_ROOT, HOST, REMOTE_ROOT)
            scr.addstr(0, 0, sanitize(header, w), curses.A_BOLD | curses.A_REVERSE)
            status = "  %s %d (%s) in   %s %d (%s) out   %s %d unsure   %s %d same   filter: %s   verify: %s" % (
                ICON_PULL, c["pull"], human_size(c["pull_b"]),
                ICON_PUSH, c["push"], human_size(c["push_b"]),
                ICON_UNSURE, c["unsure"], ICON_SAME, c["same"],
                self.filter, "on" if self.verify else "off")
            scr.addstr(1, 0, sanitize(status, w), curses.A_DIM)
            vis = self.visible()
            self.clamp_view(h)
            for row in range(2, h - 3):
                idx = self.scroll + row - 2
                if idx >= len(vis):
                    break
                it = vis[idx]
                line = fmt_row(it)
                attr = curses.A_NORMAL
                if it["act"] is None and it["kind"] == "unsure":
                    attr = curses.A_BOLD
                if idx == self.cursor:
                    attr |= curses.A_UNDERLINE
                if idx in self.sel:
                    attr |= curses.A_REVERSE
                scr.addstr(row, 0, sanitize(line, w), attr)
            if len(vis) == 0 and h > 4:
                scr.addstr(3, 0, "no differences")
            footer = ("[1] pull all  [2] push all  [3] newest wins  [4] apply selection  "
                      "space select  >/< force dir  arrows move  n/u/a filter  h help  q quit")
            scr.addstr(h - 2, 0, sanitize(footer, w), curses.A_REVERSE)
            scr.addstr(h - 1, 0, sanitize(self.msg, w))
            scr.refresh()
        except curses.error:
            pass  # terminal too small / mid-resize; next draw will retry

    def prompt(self, scr, text):
        h, w = scr.getmaxyx()
        if h < 1 or w < 1:
            return ""
        try:
            scr.addstr(h - 1, 0, sanitize(text, w))
            curses.echo()
            try:
                scr.refresh()
                return scr.getstr(h - 1, min(len(text), w - 1)).decode("utf-8", "replace").strip()
            finally:
                curses.noecho()
        except curses.error:
            return ""

    def current(self):
        vis = self.visible()
        if not vis:
            return None
        self.cursor = max(0, min(len(vis) - 1, self.cursor))
        return vis[self.cursor]

    def toggle_cursor(self):
        it = self.current()
        if it is None or not it["act"]:
            self.msg = "only actionable rows can be selected"
            return
        idx = self.current_path_index(it["path"])
        if idx in self.sel:
            self.sel.discard(idx)
        else:
            self.sel.add(idx)
        self.move_cursor(1)

    def current_path_index(self, path):
        for i, it in enumerate(self.items):
            if it["path"] == path:
                return i
        return None

    def force_dir(self, direction):
        it = self.current()
        if it is None:
            return
        if it["kind"] == "unsure":
            it["act"] = "pull" if direction == "pull" else "push"
            self.msg = "%s: %s version kept" % (it["path"], "laptop" if direction == "pull" else "local")
            return
        if it["act"] is None:
            self.msg = "row has no pending action"
            return
        if direction == "pull" and it["act"] == "push":
            it["act"] = "pull"
            self.msg = "%s: now copied FROM laptop" % it["path"]
        elif direction == "push" and it["act"] == "pull":
            it["act"] = "push"
            self.msg = "%s: now copied TO laptop" % it["path"]
        else:
            self.msg = "%s: already %s" % (it["path"], it["act"])

    def help_screen(self, scr):
        try:
            h, w = scr.getmaxyx()
            if h < 2 or w < 10:
                return
            scr.erase()
            lines = [
                "KEYS",
                "  1          pull all: copy everything newer/only on the laptop here",
                "  2          push all: copy everything newer/only here to the laptop",
                "  3          newest wins: newest mtime wins everywhere",
                "  4 / Enter  apply the rows you selected with space",
                "  space      select / deselect the row under the cursor",
                "  > / <      force row: keep laptop / local version",
                "  arrows     move cursor (PgUp/PgDn/Home/End also work)",
                "  n / u / a  filter: new only / unsure only / all rows",
                "  v          verify: hash equal-mtime files, detect hidden changes",
                "  q          quit without changing anything",
                "",
                "ICONS",
                "  %s          copy FROM laptop (pull)" % ICON_PULL,
                "  %s          copy TO laptop (push)" % ICON_PUSH,
                "  %s          unsure (changed on both sides) - decide with >/< or the bulk prompt" % ICON_UNSURE,
                "  %s          identical (shown only in 'all' filter)" % ICON_SAME,
                "",
                "SAFETY",
                "  nothing is ever deleted; transfers are confirmed before they run;",
                "  a summary with file count and size appears before applying.",
            ]
            for i, ln in enumerate(lines):
                if i < h - 1:
                    scr.addstr(i, 0, sanitize(ln, w))
            scr.addstr(h - 1, 0, sanitize("press any key to return", w), curses.A_REVERSE)
            scr.refresh()
            scr.getch()
        except curses.error:
            pass

    def bulk(self, scr, mode, sel_only):
        if sel_only:
            picks = [it for it in self.items if self.current_path_index(it["path"]) in self.sel and it["act"]]
            if not picks:
                self.msg = "no selected rows (use space first)"
                return
        else:
            target = [it for it in self.items]
            unsure = [it for it in target if it["kind"] == "unsure"]
            resolve = "newest" if mode == "newest" else self.ask_resolve
            if unsure:
                ans = self.prompt(scr, "unsure files: keep [n]ewest, [r]emote, [l]ocal or [s]kip? (n/r/l/s) ")
                resolve = {"n": "newest", "r": "remote", "l": "local", "s": "skip"}.get(ans.lower(), "newest")
                self.ask_resolve = resolve
            picks = choose_bulk(target, mode, resolve)
            if not picks:
                self.msg = "nothing to do"
                return
        mb = sum(it["sl"] or 0 for it in picks if it["act"] == "push") + \
             sum(it["sr"] or 0 for it in picks if it["act"] == "pull")
        ans = self.prompt(scr, "apply %d files (%s)? [y/n] " % (len(picks), human_size(mb)))
        if ans.lower() != "y":
            self.msg = "cancelled"
            return
        self.apply(scr, picks)

    def apply(self, scr, picks):
        n = len(picks)
        self.msg = "transferring %d files..." % n
        self.draw(scr)

        def cb(pct, line):
            self.msg = "transferring: %d%% (%d files)" % (pct, n)
            self.draw(scr)

        try:
            pulls, pushes = apply_transfers(picks, self.sim, cb)
            log("applied %d files (%d pulled, %d pushed)" % (n, pulls, pushes))
            self.msg = "done: %d files applied" % (pulls + pushes)
        except SyncError as e:
            log("error: %s" % e)
            self.msg = "error: %s" % e
        self.rescan()

    def rescan(self):
        try:
            left = scan_local(LOCAL_ROOT)
            right = scan_remote() if not self.sim else scan_local(self.sim)
            items = classify(left, right, load_state())
            if self.verify:
                verify_contents(left, right, items, self.sim)
            self.items = items
        except SyncError as e:
            self.msg = "rescan error: %s" % e
        self.sel = set()
        self.scroll = 0
        self.cursor = 0

    def run(self, scr):
        curses.curs_set(0)
        while True:
            try:
                self.draw(scr)
                key = scr.getch()
            except curses.error:
                continue  # terminal too small or mid-resize; keep the loop alive
            if key in (ord("q"), 27):
                return
            elif key in (ord("1"),):
                self.bulk(scr, "pull", False)
            elif key == ord("2"):
                self.bulk(scr, "push", False)
            elif key == ord("3"):
                self.bulk(scr, "newest", False)
            elif key in (ord("4"), ord("\n")):
                self.bulk(scr, "pull", True)
            elif key == ord(" "):
                self.toggle_cursor()
            elif key == ord(">"):
                self.force_dir("pull")
            elif key == ord("<"):
                self.force_dir("push")
            elif key == curses.KEY_UP:
                self.move_cursor(-1)
            elif key == curses.KEY_DOWN:
                self.move_cursor(1)
            elif key == curses.KEY_PPAGE:
                self.move_cursor(-20)
            elif key == curses.KEY_NPAGE:
                self.move_cursor(20)
            elif key == curses.KEY_HOME:
                self.cursor = 0
            elif key == curses.KEY_END:
                self.cursor = 10 ** 9
            elif key == curses.KEY_RESIZE:
                pass
            elif key in (ord("n"), ord("N")):
                self.filter = "new" if self.filter != "new" else "actionable"
                self.cursor = 0
            elif key in (ord("u"), ord("U")):
                self.filter = "unsure" if self.filter != "unsure" else "actionable"
                self.cursor = 0
            elif key in (ord("a"), ord("A")):
                self.filter = "all" if self.filter != "all" else "actionable"
                self.cursor = 0
            elif key in (ord("v"), ord("V")):
                self.verify = not self.verify
                self.msg = "verifying contents (hashes equal-mtime files)..." if self.verify else "verification off"
                self.draw(scr)
                self.rescan()
            elif key in (ord("h"), ord("H"), ord("?")):
                self.help_screen(scr)

def main():
    p = argparse.ArgumentParser(description="bidirectional LAN folder sync with interactive comparison")
    p.add_argument("--check", action="store_true", help="test connection and exit")
    p.add_argument("--list", action="store_true", help="show all differences and exit")
    p.add_argument("--plain", action="store_true", help="with --list: one line per file, no formatting")
    p.add_argument("--pull", action="store_true", help="copy everything newer/only on laptop, delete nothing")
    p.add_argument("--push", action="store_true", help="copy everything newer/only here to laptop, delete nothing")
    p.add_argument("--newest", action="store_true", help="apply newest version everywhere")
    p.add_argument("--resolve", choices=["newest", "local", "remote", "skip"], default="skip",
                   help="resolution for unsure files in non-interactive modes")
    p.add_argument("--verify", action="store_true",
                   help="hash files with equal mtime+size to detect hidden changes")
    p.add_argument("--reset-state", action="store_true", help="forget sync history")
    p.add_argument("--simulate-remote", metavar="DIR", help=argparse.SUPPRESS)
    p.add_argument("--simulate-local", metavar="DIR", help=argparse.SUPPRESS)
    args = p.parse_args()
    load_config()
    if bool(args.simulate_remote) != bool(args.simulate_local):
        print("--simulate-remote and --simulate-local must be used together", file=sys.stderr)
        sys.exit(2)
    global LOCAL_ROOT, REMOTE_ROOT
    if args.simulate_local:
        LOCAL_ROOT = os.path.abspath(args.simulate_local)
        REMOTE_ROOT = os.path.abspath(args.simulate_remote)

    try:
        ensure_state_dir()
        fd = os.open(LOCK_FILE, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(fd, "w")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except SyncError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(2)
    except BlockingIOError:
        print("another sync is already running", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print("cannot acquire sync lock: %s" % e, file=sys.stderr)
        sys.exit(2)

    try:
        if args.reset_state:
            try:
                os.unlink(STATE_FILE)
            except OSError:
                pass
            print("state reset")
            return

        if not args.simulate_remote:
            try:
                check_connection()
            except SyncError as e:
                print("connection error: %s" % e, file=sys.stderr)
                sys.exit(1)

        if args.check:
            if args.simulate_remote:
                print("connection OK (simulated): %s -> %s" % (HOST, REMOTE_ROOT))
            else:
                print("connection OK: %s -> %s" % (HOST, REMOTE_ROOT))
            return

        t0 = time.perf_counter()
        try:
            left = scan_local(LOCAL_ROOT)
            right = scan_remote() if not args.simulate_remote else scan_local(args.simulate_remote)
        except SyncError as e:
            print("scan error: %s" % e, file=sys.stderr)
            sys.exit(1)
        scan_seconds = time.perf_counter() - t0
        items = classify(left, right, load_state())
        if args.verify:
            print("verifying contents...", file=sys.stderr)
            verify_contents(left, right, items, args.simulate_remote)

        if args.list:
            if args.plain:
                for it in items:
                    if it["kind"] == "same":
                        continue
                    print(fmt_row(it))
                print("total differences: %d" % sum(1 for it in items if it["kind"] != "same"))
            else:
                report(items, color=sys.stdout.isatty(), scan_seconds=scan_seconds)
            return

        if args.pull or args.push or args.newest:
            mode = "pull" if args.pull else ("push" if args.push else "newest")
            resolve = args.resolve if args.resolve != "skip" else ("newest" if mode == "newest" else "skip")
            picks = choose_bulk(items, mode, resolve)
            if not picks:
                print("nothing to do")
                return
            pulls, pushes = apply_transfers(picks, args.simulate_remote)
            log("applied %d files (%d pulled, %d pushed)" % (len(picks), pulls, pushes))
            print("done: %d files applied" % (pulls + pushes))
            return

        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("interactive mode requires a terminal; use --list, --pull or --push instead",
                  file=sys.stderr)
            sys.exit(2)

        app = App(items, args.simulate_remote)
        try:
            curses.wrapper(app.run)
        except KeyboardInterrupt:
            pass
    except SyncError as e:
        print("error: %s" % e, file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()

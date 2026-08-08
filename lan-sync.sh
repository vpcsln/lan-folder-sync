#!/usr/bin/env bash
# lan-folder-sync - launcher: finds the remote machine, runs lan-sync.py.
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
set -euo pipefail

SSH_CONFIG="$HOME/.ssh/config"
KNOWN_HOSTS="$HOME/.ssh/known_hosts"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=3"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

config_get() {
    python3 - "$1" <<'PYEOF'
import json
import os
import sys

key = sys.argv[1]
cfg = {}
path = os.path.expanduser("~/.config/lan-folder-sync/config.json")
try:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
except (OSError, ValueError):
    pass

envs = {
    "host": "LAN_SYNC_HOST",
    "remote_user": "LAN_SYNC_REMOTE_USER",
    "ssh_key": "LAN_SYNC_SSH_KEY",
    "os_match": "LAN_SYNC_OS_MATCH",
}
defaults = {
    "host": "cachyos",
    "remote_user": "vpc",
    "ssh_key": "~/.ssh/id_ed25519_sync",
    "os_match": "cachyos",
}
v = os.environ.get(envs[key], "")
print(v if v else (cfg.get(key) or defaults[key]))
PYEOF
}

REMOTE="$(config_get host)"
REMOTE_USER="$(config_get remote_user)"
KEY="$(eval echo "$(config_get ssh_key)")"
OS_MATCH="$(config_get os_match)"

usage() {
    cat <<EOF
Usage: lan-sync.sh [sync options]

Finds the laptop, then runs the interactive sync tool.
Paths and host come from ~/.config/lan-folder-sync/config.json
(or LAN_SYNC_HOST / LAN_SYNC_REMOTE_USER / LAN_SYNC_REMOTE_ROOT / LAN_SYNC_LOCAL_ROOT env vars).

The laptop is found automatically (cached IP -> mDNS -> subnet scan).
The sync tool shows all differences at once and offers bulk modes
(pull all / push all / newest wins), with no deletions ever.

Sync options (passed to the tool):
  --check                 test connection and exit
  --list                  show a grouped difference report, change nothing
  --list --plain          same, one plain line per file (for scripts)
  --pull                  copy everything newer/only on the laptop here
  --push                  copy everything newer/only here to the laptop
  --newest                apply newest version everywhere
  --verify                hash equal-mtime files to detect hidden changes
  --resolve newest|local|remote|skip   unsure files (non-interactive modes)
  -h, --help              show this help
EOF
}

for arg in "$@"; do
    case "$arg" in
        -h|--help) usage; exit 0;;
        --check) ;;
        --list) ;;
        --plain) ;;
        --pull) ;;
        --push) ;;
        --newest) ;;
        --verify) ;;
        --resolve) ;;
        --reset-state) ;;
        *) ;;
    esac
done

current_hostname() {
    awk -v host="$REMOTE" '/^Host /{h=$2; next} h==host && /^[[:space:]]*HostName /{print $2; exit}' "$SSH_CONFIG"
}

set_hostname() {
    awk -v host="$REMOTE" -v h="$1" '
        /^Host /{h2=$2; print; next}
        h2==host && /^[[:space:]]*HostName /{print "    HostName " h; next}
        {print}
    ' "$SSH_CONFIG" > "$SSH_CONFIG.tmp" && mv "$SSH_CONFIG.tmp" "$SSH_CONFIG"
}

is_laptop() {
    ssh $SSH_OPTS -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile="$KNOWN_HOSTS" "$REMOTE" "grep -qis '$OS_MATCH' /etc/os-release" 2>/dev/null
}

test_candidate() {
    ssh $SSH_OPTS -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
        -o IdentitiesOnly=yes -i "$KEY" "$REMOTE_USER@$1" "grep -qis '$OS_MATCH' /etc/os-release" 2>/dev/null
}

mdns_ip() {
    getent hosts "$REMOTE.local" 2>/dev/null | awk '$1 !~ /:/ {print $1; exit}'
}

subnet_prefix() {
    ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | awk -F. '{printf "%s.%s.%s.", $1, $2, $3}'
}

scan_candidates() {
    local pre
    pre="$(subnet_prefix)" || return 1
    for i in $(seq 1 254); do
        ( timeout 0.35 bash -c "</dev/tcp/$pre$i/22" 2>/dev/null && echo "$pre$i" ) &
    done
    wait
}

ensure_laptop() {
    echo "Looking for laptop ($REMOTE)..."
    if is_laptop; then
        echo "  found at $(current_hostname) (cached)"
        return 0
    fi

    local ip
    ip="$(mdns_ip || true)"
    if [[ -n "$ip" ]]; then
        set_hostname "$ip"
        if is_laptop; then
            echo "  found via mDNS: $ip"
            return 0
        fi
    fi

    local found=""
    while read -r ip; do
        [[ -n "$ip" ]] || continue
        if test_candidate "$ip"; then
            set_hostname "$ip"
            if is_laptop || { ssh-keygen -R "$REMOTE" >/dev/null 2>&1; is_laptop; }; then
                found="$ip"
                break
            fi
        fi
    done < <(scan_candidates || true)

    if [[ -n "$found" ]]; then
        echo "  found via subnet scan: $found"
        return 0
    fi

    echo "ERROR: laptop not found." >&2
    echo "  - Is it on the same network/WiFi?" >&2
    echo "  - Is sshd running there? (sudo systemctl enable --now sshd)" >&2
    echo "  - Is your key installed? (ssh-copy-id -i $KEY.pub ${REMOTE_USER}@<laptop-ip>)" >&2
    echo "  - eduroam may block direct device connections." >&2
    return 1
}

ensure_laptop
exec python3 "$SCRIPT_DIR/lan-sync.py" "$@"

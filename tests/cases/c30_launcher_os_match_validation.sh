#!/bin/bash
# R10/F14: an invalid os_match value must abort the launcher with exit 2
# before any connection attempt — no shell metacharacters may reach the
# remote grep command.
. "$ROOT/tests/lib.sh"
H="$CASE_DIR/home"
mkdir -p "$H/.ssh" "$H/.config/lan-folder-sync" "$H/bin"
cp "$ROOT"/tests/stubs/{ssh,ssh-keygen,ip,timeout,getent} "$H/bin/"
chmod +x "$H/bin/"*
printf 'dummy-private-key\n' > "$H/.ssh/id_ed25519_sync"
chmod 600 "$H/.ssh/id_ed25519_sync"
cat > "$H/.ssh/config" <<'EOF'
Host cachyos
    HostName 10.0.0.99
    User vpc
    IdentityFile ~/.ssh/id_ed25519_sync
    IdentitiesOnly yes
    ConnectTimeout 5
    AddressFamily inet
    HostKeyAlias cachyos
EOF
printf 'cachyos ssh-ed25519 AAAAREALKEY laptop\n' > "$H/.ssh/known_hosts"
chmod 600 "$H/.ssh/known_hosts"
printf '{"host": "cachyos", "remote_user": "vpc", "local_root": "/tmp/x",\n "remote_root": "/home/vpc/docs", "ssh_key": "~/.ssh/id_ed25519_sync",\n "os_match": "cachyos\047; touch /tmp/opencode/pwned #"}\n' \
    > "$H/.config/lan-folder-sync/config.json"
rm -f /tmp/opencode/pwned
LOG="$CASE_DIR/ssh.log"

env HOME="$H" PATH="$H/bin:/usr/bin:/bin" FAKE_SSH_LOG="$LOG" FAKE_SSH_COUNTER="$CASE_DIR/grep_count" \
    bash "$LAUNCHER" --check >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?
[[ $rc -eq 2 ]] || fail "expected exit 2 for invalid os_match, got $rc"
grep -q "invalid os_match" "$CASE_DIR/err" || fail "no os_match error message"
[[ ! -e /tmp/opencode/pwned ]] || fail "os_match injection executed a command"
[[ ! -s "$LOG" ]] || fail "any ssh connection attempted despite invalid os_match"
exit 0

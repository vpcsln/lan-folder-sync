#!/bin/bash
# F10/R9: successful discovery (mDNS path) must preserve ~/.ssh/config mode
# (0600) — the rewrite must not downgrade it to 0644.
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
chmod 600 "$H/.ssh/config"
printf 'cachyos ssh-ed25519 AAAAREALKEY laptop\n' > "$H/.ssh/known_hosts"
chmod 600 "$H/.ssh/known_hosts"
cat > "$H/.config/lan-folder-sync/config.json" <<'EOF'
{"host": "cachyos", "remote_user": "vpc", "local_root": "/tmp/opencode/x/docs",
 "remote_root": "/home/vpc/docs", "ssh_key": "~/.ssh/id_ed25519_sync", "os_match": "cachyos"}
EOF
LOG="$CASE_DIR/ssh.log"

env HOME="$H" PATH="$H/bin:/usr/bin:/bin" FAKE_SSH_LOG="$LOG" FAKE_SSH_COUNTER="$CASE_DIR/grep_count" \
    FAKE_SERVER_KEY="AAAAREALKEY" FAKE_CMD_OK=1 FAKE_FIRST_GREP_FAIL=1 \
    FAKE_MDNS_IP="192.168.1.50" \
    bash "$LAUNCHER" --check >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?

[[ $rc -eq 0 ]] || { fail "launcher failed (rc=$rc)"; cat "$CASE_DIR/err" >&2; }
grep -q "found via mDNS: 192.168.1.50" "$CASE_DIR/out" || fail "mDNS discovery failed"
grep -q "HostName 192.168.1.50" "$H/.ssh/config" || fail "HostName not updated"
[[ "$(stat -c%a "$H/.ssh/config")" == "600" ]] \
    || fail "config mode changed to $(stat -c%a "$H/.ssh/config")"
exit 0

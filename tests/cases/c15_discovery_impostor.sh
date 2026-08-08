#!/bin/bash
# F1: the launcher must NOT accept an impostor on the subnet. With the real
# laptop unreachable and an impostor that "accepts the key + matches
# os-release", discovery must fail, the pinned host key must survive, the
# config must not be rewritten, and ssh-keygen -R must never be called.
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
    FAKE_SERVER_KEY="AAAABADKEY" FAKE_CMD_OK=1 FAKE_FIRST_GREP_FAIL=1 \
    bash "$LAUNCHER" --check >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?

[[ $rc -ne 0 ]] || fail "launcher accepted the impostor (exit 0)"
grep -q "laptop not found" "$CASE_DIR/err" || fail "expected 'laptop not found'"
grep -q "AAAAREALKEY" "$H/.ssh/known_hosts" || fail "real host-key pin was erased"
grep -q "HostName 10.0.0.99" "$H/.ssh/config" || fail "config HostName was rewritten"
grep -q "ssh-keygen -R CALLED" "$LOG" && fail "ssh-keygen -R was called (pin auto-erase)"
exit 0

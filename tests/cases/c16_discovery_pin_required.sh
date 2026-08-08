#!/bin/bash
# F1/TOFU: with no pinned host key and no interactive terminal, the launcher
# must refuse to proceed and give manual pinning instructions — it must NOT
# auto-accept a key (no accept-new TOFU in non-interactive mode).
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
: > "$H/.ssh/known_hosts"   # no pin
chmod 600 "$H/.ssh/known_hosts"
cat > "$H/.config/lan-folder-sync/config.json" <<'EOF'
{"host": "cachyos", "remote_user": "vpc", "local_root": "/tmp/opencode/x/docs",
 "remote_root": "/home/vpc/docs", "ssh_key": "~/.ssh/id_ed25519_sync", "os_match": "cachyos"}
EOF
LOG="$CASE_DIR/ssh.log"

env HOME="$H" PATH="$H/bin:/usr/bin:/bin" FAKE_SSH_LOG="$LOG" FAKE_SSH_COUNTER="$CASE_DIR/grep_count" \
    FAKE_SERVER_KEY="AAAAREALKEY" FAKE_CMD_OK=1 \
    bash "$LAUNCHER" --check >"$CASE_DIR/out" 2>"$CASE_DIR/err"; rc=$?

[[ $rc -ne 0 ]] || fail "launcher ran without a pinned host key (exit 0)"
grep -q "no host key is pinned" "$CASE_DIR/err" || fail "expected pin-required message"
grep -q "StrictHostKeyChecking=ask" "$CASE_DIR/err" || fail "expected manual pinning instructions"
[[ -s "$H/.ssh/known_hosts" ]] && fail "known_hosts was written without interactive confirmation"
exit 0

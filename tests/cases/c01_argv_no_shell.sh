#!/bin/bash
# Verified-safe port: no shell=True / os.system / eval / exec anywhere in
# lan-sync.py; remote shell commands are built with shlex.quote.
grep -nE "shell=True|os\.system\(|eval\(|exec\(" "$TOOL" && fail "unsafe pattern found in $TOOL"
grep -q "shlex.quote" "$TOOL" || fail "shlex.quote not used for remote command strings"
exit 0

#!/usr/bin/env python3
"""unit_valid_relpath.py <lan-sync.py> — F5/F4: C0 control rejection in
valid_relpath (fails pre-fix: CR/ESC/tab were accepted)."""
import importlib.util
import sys

spec = importlib.util.spec_from_file_location("lan_sync", sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        print("FAIL:", msg)
        fails += 1


# C0 controls + DEL must be rejected (post-fix)
for bad in ["a\rb", "a\x1bb", "a\tb", "a\nb", "a\x00b", "\x7f",
            "cr\r", "\x1b[31mRED", "a\x01b", "a\x1fb"]:
    check(not m.valid_relpath(bad), "should reject %r" % bad)

# structural rejects
for bad in ["/abs", "a/../b", "a/./b", "a//b", "", ".", ".."]:
    check(not m.valid_relpath(bad), "should reject %r" % bad)

# valid names (spaces, dashes, surrogates, long, literal-dotdot tricks)
for good in ["normal.txt", "with space.txt", "-dash", "--inject", "-",
             "sub/dir/file.txt", "a\\b", "long_" + "a" * 200 + ".txt",
             "\udc94name.txt", "a..b", "..%2f..%2fetc%2fpasswd",
             "sub dir/inside.txt"]:
    check(m.valid_relpath(good), "should accept %r" % good)

print("FAILS:", fails)
sys.exit(1 if fails else 0)

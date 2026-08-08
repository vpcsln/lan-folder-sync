#!/usr/bin/env python3
"""unit_sanitize.py <lan-sync.py> — R5/F4: safe_text control mapping and
display-width-aware truncation (fails pre-fix: helpers did not exist)."""
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


# safe_text maps C0/DEL to '?'; surrogates display as U+FFFD (documented)
s = m.safe_text("a\x1b[31m\x0d\x00b\udc94c")
check(s == "a?[31m??b\ufffdc", "safe_text mapping wrong: %r" % s)
check("\x1b" not in m.safe_text("x\x1by"), "ESC survived safe_text")

# display width: CJK wide chars count 2
check(m.disp_width("abc") == 3, "ascii width")
check(m.disp_width("\u65e5\u672c\u8a9e") == 6, "CJK width")

# trunc_disp truncates by display width, not codepoints
t = m.trunc_disp("a\u65e5\u672cb", 4)
check(m.disp_width(t) <= 4, "trunc_disp overshoots: %r" % t)
check(t == "a\u65e5", "trunc_disp wrong cut: %r" % t)

# sanitize truncates by display width and appends '...'
s = m.sanitize("\u65e5\u672c\u8a9e\u3067\u3059", 6)
check(m.disp_width(s) <= 6, "sanitize overshoots: %r (%d)" % (s, m.disp_width(s)))
check(s.endswith("..."), "sanitize missing ellipsis: %r" % s)

# long ascii
s = m.sanitize("x" * 100, 20)
check(m.disp_width(s) <= 20, "sanitize ascii overshoots")

print("FAILS:", fails)
sys.exit(1 if fails else 0)

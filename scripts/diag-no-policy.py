#!/usr/bin/env python3
"""Diagnostic-only: skip SukiSU SELinux policy injection for boot bisect.

This is intentionally not a supported root configuration.  It keeps KSU and
SUSFS compiled in but skips the `apply_kernelsu_rules()` call made while init
execs second_stage, so a boot failure can be attributed to the policy reload
instead of the KSU/SUSFS core.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

MARKER = "ksu54_diag_no_policy"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True, type=pathlib.Path)
    args = ap.parse_args()

    path = args.kernel / "KernelSU/kernel/runtime/ksud_integration.c"
    if not path.is_file():
        print(f"missing {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        print("ksud_integration.c: no_policy diagnostic already applied")
        return 0

    old = (
        "            ksu_preinit_release();\n"
        "            ksu_selinux_hide_handle_second_stage();\n"
        "            apply_kernelsu_rules();\n"
        "            cache_sid();"
    )
    new = (
        "            ksu_preinit_release();\n"
        "            /* ksu54_diag_no_policy: skip SELinux policy injection for boot bisect */\n"
        "            cache_sid();"
    )
    if old not in text:
        print("ksud_integration.c: init second_stage block not found (upstream changed?)", file=sys.stderr)
        return 1

    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")
    print("ksud_integration.c: skipped apply_kernelsu_rules() for no_policy diagnostic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

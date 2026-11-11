#!/usr/bin/env bash
# Static self-test for the SukiSU odin repository. Does not compile the kernel.
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FAIL=0
ok()   { printf '  ok   %s\n' "$1"; }
bad()  { printf '  FAIL %s\n' "$1"; FAIL=1; }
have() { [ -e "$ROOT/$1" ] && ok "$1" || bad "missing $1"; }
grepf(){ grep -q "$1" "$ROOT/$2" 2>/dev/null && ok "$3" || bad "$3"; }

echo "== repository files =="
have README.md
have .github/workflows/build-sukisu.yml
have scripts/sukisu-setup.py
have scripts/ksu54-compat.h
have scripts/ak3-ksud.sh
have scripts/sched-tune.sh
have scripts/power-tune.sh
have scripts/sched-patches

echo "== python syntax =="
python3 -m py_compile "$ROOT/scripts/sukisu-setup.py" && ok "sukisu-setup.py" || bad "sukisu-setup.py syntax"

echo "== YAML syntax =="
python3 - "$ROOT/.github/workflows/build-sukisu.yml" <<'PY' && ok "build-sukisu.yml" || bad "build-sukisu.yml"
import sys, yaml
yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
PY

echo "== setup script markers =="
for marker in KSU54_SELINUX_POLICY_SHIM KSU54_POLICY_FIELD ksu54_sepolicy_backport \
              ksu54_selinux_hide_54 ksu54_pmd_sect susfs_is_current_ksu_domain \
              ksu_handle_susfs_command susfs_start_sdcard_monitor_fn \
              susfs_set_current_proc_umounted 'config KSU_SUSFS'; do
  grepf "$marker" scripts/sukisu-setup.py "setup emits $marker"
done
grepf 'ksu_handle_execveat' scripts/sukisu-setup.py "setup strips legacy execveat hook"
grepf 'ksu_handle_stat' scripts/sukisu-setup.py "setup strips legacy stat hook"

echo "== workflow guards =="
grepf 'KSU_VERSION' .github/workflows/build-sukisu.yml "workflow pins KSU version"
grepf 'drivers/kernelsu/' .github/workflows/build-sukisu.yml "workflow builds KSU subtree"
grepf 'device.name1=odin' .github/workflows/build-sukisu.yml "workflow sets odin device"
grepf 'by-name/boot' .github/workflows/build-sukisu.yml "workflow writes boot partition"
grepf 'ksud-aarch64-linux-android' .github/workflows/build-sukisu.yml "workflow embeds ksud"
grepf 'security/selinux/' .github/workflows/build-sukisu.yml "workflow builds selinux headers"

exit "$FAIL"

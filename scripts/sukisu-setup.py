#!/usr/bin/env python3
"""
sukisu-setup.py - make SukiSU-Ultra v4.3.0-r2 build on the odin 5.4 vendor tree.

The kernel is a Xiaomi SM8350 5.4 tree (kernel_xiaomi_odin, resukisu branch).
SukiSU's main branch is written mostly against 6.x ABI.  This script applies the
same 5.4 compatibility layer that the FinaSU odin build already proved, plus the
odin-specific sys_call_table/block-PMD fix.

Usage (from the workflow, kernel checked out at ./kernel):
    python3 scripts/sukisu-setup.py --kernel kernel

Every edit is idempotent: markers are checked before writing.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path

MARK = "ksu54"
HOOKS = "ksu54_legacy_hooks"


def fail(msg: str) -> "NoReturn":
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def read(path: Path) -> str:
    if not path.is_file():
        fail(f"missing file: {path}")
    return path.read_text(encoding="utf-8", errors="surrogateescape")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def replace_once(text: str, old: str, new: str, what: str) -> str:
    if old not in text:
        fail(f"anchor not found ({what}); SukiSU/kernel source changed?")
    return text.replace(old, new, 1)


def remove_once(text: str, old: str, what: str) -> str:
    if old not in text:
        fail(f"anchor not found ({what}); SukiSU/kernel source changed?")
    return text.replace(old, "", 1)


def ensure_include(text: str, line: str, what: str) -> str:
    if line in text:
        return text
    return line + "\n" + text


def strip_legacy_hooks(kdir: Path) -> None:
    """Remove old ReSukiSU manual-hook call sites.

    SukiSU main has no ksu_handle_execveat/faccessat/stat/sys_reboot/
    setresuid/input_handle_event/sys_read symbols (or has different
    signatures).  Its kprobe/tracepoint backend hooks these paths at runtime,
    so the in-tree calls are dead weight and break the build.
    """
    edits = {
        "drivers/input/input.c": [
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "extern struct static_key_true ksu_is_input_hook_enabled;\n"
                "extern __attribute__((cold)) int ksu_handle_input_handle_event(\n"
                "\t\t\tunsigned int *type, unsigned int *code, int *value);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "\tif (static_branch_unlikely(&ksu_is_input_hook_enabled))\n"
                "\t\tksu_handle_input_handle_event(&type, &code, &value);\n"
                "#endif\n",
                "",
            ),
        ],
        "fs/exec.c": [
            (
                "#ifdef CONFIG_KSU\n"
                "__attribute__((hot))\n"
                "extern int ksu_handle_execveat(int *fd, struct filename **filename_ptr,\n"
                "\t\t\t\tvoid *argv, void *envp, int *flags);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU\n"
                "\tksu_handle_execveat((int *)AT_FDCWD, &filename, &argv, &envp, 0);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU // 32-bit ksud and 32-on-64 support\n"
                "\tksu_handle_execveat((int *)AT_FDCWD, &filename, &argv, &envp, 0);\n"
                "#endif\n",
                "",
            ),
        ],
        "fs/open.c": [
            (
                "#ifdef CONFIG_KSU\n"
                "__attribute__((hot))\n"
                "extern int ksu_handle_faccessat(int *dfd, const char __user **filename_user,\n"
                "\t\t\t\tint *mode, int *flags);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU\n"
                "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n"
                "#endif\n",
                "",
            ),
        ],
        "fs/read_write.c": [
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "extern struct static_key_true ksu_is_init_rc_hook_enabled;\n"
                "extern __attribute__((cold)) void ksu_handle_sys_read(unsigned int fd);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "\tif (static_branch_unlikely(&ksu_is_init_rc_hook_enabled))\n"
                "\t\tksu_handle_sys_read(fd);\n"
                "#endif\n",
                "",
            ),
        ],
        "fs/stat.c": [
            (
                "#ifdef CONFIG_KSU\n"
                "__attribute__((hot))\n"
                "extern int ksu_handle_stat(int *dfd, const char __user **filename_user,\n"
                "\t\t\t\tint *flags);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU\n"
                "\tksu_handle_stat(&dfd, &filename, &flag);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU // 32-bit su\n"
                "\tksu_handle_stat(&dfd, &filename, &flag);\n"
                "#endif\n",
                "",
            ),
        ],
        "kernel/reboot.c": [
            (
                "#if defined(CONFIG_KSU) && !defined(CONFIG_KSU_KPROBES_KSUD)\n"
                "extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n"
                "#endif\n",
                "",
            ),
            (
                "#if defined(CONFIG_KSU) && !defined(CONFIG_KSU_KPROBES_KSUD)\n"
                "\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n"
                "#endif\n",
                "",
            ),
        ],
        "kernel/sys.c": [
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "extern int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);\n"
                "#endif\n",
                "",
            ),
            (
                "#ifdef CONFIG_KSU_SUSFS\n"
                "\t(void)ksu_handle_setresuid(ruid, euid, suid);\n"
                "#endif\n",
                "",
            ),
        ],
    }

    for rel, pairs in edits.items():
        path = kdir / rel
        text = read(path)
        changed = False
        for old, new in pairs:
            # Some blocks may already have been removed by a previous run.
            if old in text:
                text = text.replace(old, new, 1)
                changed = True
        if changed:
            write(path, text)
            print(f"  stripped legacy KSU hooks: {rel}")


def install_compat_header(kdir: Path, su: Path, script_dir: Path) -> None:
    src = script_dir / "ksu54-compat.h"
    if not src.is_file():
        fail(f"missing {src}")
    dest = kdir / "include/linux/ksu54_compat.h"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    kbuild = su / "Kbuild"
    text = read(kbuild)
    line = "ccflags-y += -include $(srctree)/include/linux/ksu54_compat.h"
    if line not in text:
        text = ensure_include(text, line, "SukiSU Kbuild")
        write(kbuild, text)
        print("  installed 5.4 header into include/linux/ksu54_compat.h")


def install_header_shims(kdir: Path) -> None:
    """Provide headers that were split out after 5.4.

    SukiSU/ksud upstream includes <linux/hex.h> and <linux/minmax.h>; this
    vendor 5.4 tree still declares those APIs in <linux/kernel.h>.
    """
    shims = {
        "hex.h": "#include <linux/kernel.h>\n",
        "minmax.h": "#include <linux/kernel.h>\n",
        "pgtable.h": "#include <asm/pgtable.h>\n",
        "unaligned.h": "#include <asm-generic/unaligned.h>\n",
    }
    inc = kdir / "include/linux"
    inc.mkdir(parents=True, exist_ok=True)
    for name, include in shims.items():
        dest = inc / name
        if dest.exists():
            continue
        dest.write_text(
            "/* ksu54_header_shim: split out after Linux 5.4. */\n" + include,
            encoding="utf-8",
        )
        print(f"  include/linux/{name}: 5.4 header shim")


def add_susfs_kconfig(su: Path) -> None:
    path = su / "Kconfig"
    text = read(path)
    if "config KSU_SUSFS" in text:
        return
    block = r"""
config KSU_SUSFS
	bool "SUSFS support (odin 5.4 v2.1.0)"
	depends on KSU
	default y
	help
	  Enable the in-tree SUSFS v2.1.0 implementation on this 5.4 kernel.
	  SukiSU's extension only advertises SUSFS; the syscall ABI lives in
	  fs/susfs.c.  Newer SukiSU manager features that need SUSFS v2.3
	  commands may report "not supported" on this kernel.

config KSU_SUSFS_ENABLE_LOG
	bool "SUSFS logging"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
	bool "Hide KSU/SUSFS symbols"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_OPEN_REDIRECT
	bool "SUSFS open redirect"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
	bool "SUSFS spoof cmdline/bootconfig"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SPOOF_UNAME
	bool "SUSFS spoof uname"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_KSTAT
	bool "SUSFS sus kstat"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_MAP
	bool "SUSFS sus map"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_MOUNT
	bool "SUSFS sus mount"
	depends on KSU_SUSFS
	default y

config KSU_SUSFS_SUS_PATH
	bool "SUSFS sus path"
	depends on KSU_SUSFS
	default y

"""
    idx = text.rfind("endmenu")
    if idx < 0:
        fail("SukiSU Kconfig has no endmenu")
    text = text[:idx] + block + text[idx:]
    write(path, text)
    print("  added KSU_SUSFS Kconfig menu")


def patch_sepolicy_h(su: Path) -> None:
    path = su / "selinux/sepolicy.h"
    text = read(path)
    if "KSU54_SELINUX_POLICY_SHIM" in text:
        return
    anchor = "struct selinux_policy *ksu_dup_sepolicy"
    block = r"""#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 7, 0)
#define KSU54_SELINUX_POLICY_SHIM 1
#include <linux/sched.h>
#include "ss/services.h"
struct selinux_policy {
	struct policydb policydb;
	u32 latest_granting;
};
extern struct selinux_state selinux_state;
#endif

"""
    text = replace_once(text, anchor, block + anchor, "sepolicy.h dup_sepolicy")
    write(path, text)
    print("  selinux/sepolicy.h: 5.4 struct selinux_policy shim")


def patch_rules(su: Path) -> None:
    path = su / "selinux/rules.c"
    text = read(path)
    if "KSU54_POLICY_FIELD" in text:
        print("  selinux/rules.c: 5.4 policy accessors already applied")
        return

    # Do the call-site substitutions BEFORE inserting the macro block: one of
    # the 6.x macro definitions contains the same rcu_dereference_protected()
    # text we are replacing, and a global replace would make it self-referential.
    text = text.replace("mutex_lock(&selinux_state.policy_mutex);", "KSU_POLICY_LOCK();")
    text = text.replace("mutex_unlock(&selinux_state.policy_mutex);", "KSU_POLICY_UNLOCK();")
    text = text.replace(
        "rcu_dereference_protected(selinux_state.policy, lockdep_is_held(&selinux_state.policy_mutex))",
        "KSU_POLICY_GET()",
    )
    text = text.replace("rcu_assign_pointer(selinux_state.policy, pol);", "KSU_POLICY_SET(pol);")

    if "KSU54_POLICY_FIELD" not in text:
        anchor = "struct selinux_policy *backup_sepolicy;"
        block = r"""#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 7, 0)
#define KSU54_POLICY_FIELD 1
static u32 ksu54_policy_generation;
static struct selinux_policy *ksu54_current_policy(void)
{
	static struct selinux_policy shadow;
	shadow.policydb = selinux_state.ss->policydb;
	shadow.latest_granting = ksu54_policy_generation;
	return &shadow;
}
#define KSU_POLICY_GET() ksu54_current_policy()
#define KSU_POLICY_SET(pol) do { \
	ksu54_policy_generation = (pol)->latest_granting; \
	selinux_state.ss->policydb = (pol)->policydb; \
} while (0)
#define KSU_POLICY_LOCK() mutex_lock(&selinux_state.ss->status_lock)
#define KSU_POLICY_UNLOCK() mutex_unlock(&selinux_state.ss->status_lock)
#else
#define KSU_POLICY_GET() rcu_dereference_protected(selinux_state.policy, lockdep_is_held(&selinux_state.policy_mutex))
#define KSU_POLICY_SET(pol) rcu_assign_pointer(selinux_state.policy, (pol))
#define KSU_POLICY_LOCK() mutex_lock(&selinux_state.policy_mutex)
#define KSU_POLICY_UNLOCK() mutex_unlock(&selinux_state.policy_mutex)
#endif

"""
        text = replace_once(text, anchor, anchor + "\n" + block, "rules.c backup_sepolicy")

    if "backup_sepolicy->sidtab = kzalloc" in text:
        start = text.index("        backup_sepolicy->sidtab = kzalloc")
        end_marker = "    pol = ksu_dup_sepolicy(old_pol);"
        end = text.index(end_marker, start)
        text = text[:start] + "        (void)0;\n    }\n" + text[end:]

    # The 5.4 KSU_POLICY_GET() returns a static shadow; never free it.
    text = text.replace(
        "    ksu_destroy_sepolicy(old_pol);",
        "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 7, 0)\n"
        "    ksu_destroy_sepolicy(old_pol);\n"
        "#endif",
    )

    # 5.4 has no selinux_state.policy; keep the generation stable.
    text = text.replace("reset_avc_cache(pol->latest_granting);", "reset_avc_cache(0);")
    write(path, text)
    print("  selinux/rules.c: 5.4 policy accessors applied")


def patch_sepolicy_c(su: Path) -> None:
    path = su / "selinux/sepolicy.c"
    text = read(path)
    if "ksu54_sepolicy_backport" in text:
        return

    text = re.sub(
        r"void ksu_destroy_sepolicy\(struct selinux_policy \*pol\)\s*\{.*?\n\}\n",
        "",
        text,
        count=1,
        flags=re.S,
    )
    text = re.sub(
        r"struct selinux_policy \*ksu_dup_sepolicy\(struct selinux_policy \*old_pol\)\s*\{.*?\n\}\n",
        "",
        text,
        count=1,
        flags=re.S,
    )

    backport = r"""
/* ksu54_sepolicy_backport: 5.4 has no struct selinux_policy; duplicate the
 * embedded policydb through policydb_write()/policydb_read(). */
#include <linux/lockdep.h>
#include <linux/rcupdate.h>
#include <linux/slab.h>
#include <linux/vmalloc.h>
#include <linux/version.h>
#include "ss/services.h"
#include "selinux.h"
#include "sepolicy.h"
#include "klog.h" // IWYU pragma: keep

void ksu_destroy_sepolicy(struct selinux_policy *pol)
{
	if (!pol)
		return;
	policydb_destroy(&pol->policydb);
	kfree(pol);
}

struct selinux_policy *ksu_dup_sepolicy(struct selinux_policy *old_pol)
{
	struct selinux_policy *new_pol;
	struct policy_file fp;
	void *data;
	size_t len, buf_len;
	int ret;

	/* policydb_read() adds every type to its own attribute map; preserve
	 * room for one ebitmap entry per type so the buffer cannot overflow. */
	buf_len = old_pol->policydb.len +
		  (size_t)old_pol->policydb.p_types.nprim *
			  (sizeof(u32) + sizeof(u64));
	data = vmalloc(buf_len);
	if (!data) {
		pr_err("sepolicy54: alloc policy buffer len %zu\n", buf_len);
		return ERR_PTR(-ENOMEM);
	}

	fp.data = data;
	fp.len = buf_len;
	ret = policydb_write(&old_pol->policydb, &fp);
	if (ret) {
		pr_err("sepolicy54: policydb_write: %d\n", ret);
		goto out_free_data;
	}
	len = buf_len - fp.len;

	/* 5.4 keeps the Android netlink config bits in policydb; older
	 * policydb_read() rejects a written image without them. */
	if (len >= 20 + sizeof(u32)) {
		u32 *config_ptr = (u32 *)((unsigned long)data + 20);
		if (old_pol->policydb.android_netlink_route)
			*config_ptr |= POLICYDB_CONFIG_ANDROID_NETLINK_ROUTE;
		if (old_pol->policydb.android_netlink_getneigh)
			*config_ptr |= POLICYDB_CONFIG_ANDROID_NETLINK_GETNEIGH;
	}

	new_pol = kmemdup(old_pol, sizeof(*old_pol), GFP_KERNEL);
	if (!new_pol) {
		ret = -ENOMEM;
		goto out_free_data;
	}
	memset(&new_pol->policydb, 0, sizeof(new_pol->policydb));

	fp.data = data;
	fp.len = len;
	ret = policydb_read(&new_pol->policydb, &fp);
	if (ret) {
		pr_err("sepolicy54: policydb_read: %d\n", ret);
		kfree(new_pol);
		goto out_free_data;
	}
	new_pol->policydb.len = len;
	kvfree(data);
	pr_info("sepolicy54: dup policydb ok, len %zu\n", len);
	return new_pol;

out_free_data:
	kvfree(data);
	return ERR_PTR(ret);
}
/* ksu54_sepolicy_backport done */
"""
    text = text.rstrip() + "\n" + backport
    write(path, text)
    print("  selinux/sepolicy.c: 5.4 policydb dup/destroy backport")


def patch_selinux_hide(su: Path) -> None:
    path = su / "feature/selinux_hide.c"
    text = read(path)
    if "ksu54_selinux_hide_54" in text:
        return

    old_enable = (
        "    if (!backup_sepolicy) {\n"
        '        pr_err("no backup sepolicy available, please save feature and reboot to retry!\\n");\n'
        "        return -EAGAIN;\n"
        "    }\n"
    )
    new_enable = "    /* ksu54_selinux_hide_54: live policy queried directly */\n"
    text = replace_once(text, old_enable, new_enable, "selinux_hide enable guard")

    old_drop = (
        "        sidtab_destroy(backup_sepolicy->sidtab);\n"
        "        kfree(backup_sepolicy->sidtab);\n"
        "        ksu_destroy_sepolicy(backup_sepolicy);\n"
        "        backup_sepolicy = NULL;"
    )
    new_drop = (
        "        /* ksu54_selinux_hide_54: shim policy owns no sidtab */\n"
        "        backup_sepolicy = NULL;"
    )
    text = replace_once(text, old_drop, new_drop, "selinux_hide drop block")

    marker = "/*\n * Caveat:  Mutates scontext.\n */"
    idx = text.find(marker)
    if idx < 0:
        fail("selinux_hide.c: Caveat marker not found")
    head, tail = text[:idx], text[idx:]
    tail = (
        "#if 0 /* ksu54_selinux_hide_54: 5.7-only policydb/sidtab internals */\n"
        + tail
        + "\n#endif /* ksu54_selinux_hide_54 internals */\n"
    )
    text = (head + tail).replace("selinux_state.status_lock", "selinux_state.ss->status_lock")
    text = text.replace("selinux_state.status_page", "selinux_state.ss->status_page")

    shims = r"""
/* ksu54_selinux_hide_54: 5.4 keeps the live policy in
 * selinux_state.ss->policydb and its services take &selinux_state. */
static int security_context_to_sid_with_policy(struct selinux_policy *policy,
		const char *scontext, u32 scontext_len, u32 *sid,
		u32 def_sid, gfp_t gfp_flags, u32 *orig_sid_p, int *orig_rc_p)
{
	int rc;
	(void)policy;
	rc = security_context_to_sid_default(&selinux_state, scontext, scontext_len,
			sid, def_sid, gfp_flags);
	if (orig_rc_p)
		*orig_rc_p = rc;
	if (orig_sid_p)
		*orig_sid_p = rc ? SECSID_NULL : *sid;
	return rc;
}

static int security_sid_to_context_with_policy(struct selinux_policy *policy,
		u32 sid, char **scontext, u32 *scontext_len)
{
	(void)policy;
	return security_sid_to_context(&selinux_state, sid, scontext, scontext_len);
}

static void security_compute_av_user_with_policy(struct selinux_policy *policy,
		u32 ssid, u32 tsid, u16 tclass, struct av_decision *avd)
{
	(void)policy;
	security_compute_av_user(&selinux_state, ssid, tsid, tclass, avd);
}
/* ksu54_selinux_hide_54 done */
"""
    write(path, text + shims)
    print("  feature/selinux_hide.c: 5.4 selinux service shims")


def patch_patch_memory(su: Path) -> None:
    path = su / "hook/arm64/patch_memory.c"
    text = read(path)
    if "ksu54_pmd_sect" in text:
        return
    old = """    pmd = pmd_offset(pud, addr);
#if defined(pmd_leaf)
    if (pmd_leaf(*pmd)) {
        return __pmd_to_phys(*pmd) + ((addr & ~PMD_MASK));
    }
#endif
"""
    new = """    pmd = pmd_offset(pud, addr);
#if defined(pmd_leaf)
    if (pmd_leaf(*pmd)) {
        return __pmd_to_phys(*pmd) + ((addr & ~PMD_MASK));
    }
#elif defined(pmd_sect)
    /* ksu54_pmd_sect: 5.4 has no pmd_leaf(); pmd_bad() rejects block PMDs,
     * so sys_call_table patching (and ksud init.rc injection) failed. */
    if (pmd_sect(*pmd)) {
        return __pmd_to_phys(*pmd) + ((addr & ~PMD_MASK));
    }
#endif
"""
    text = replace_once(text, old, new, "patch_memory phys_from_virt")
    write(path, text)
    print("  hook/arm64/patch_memory.c: 5.4 block-PMD fallback")


def patch_sucompat_pgtable(su: Path) -> None:
    path = su / "feature/sucompat.c"
    text = read(path)
    if "ksu54_sucompat_pgtable" in text:
        return
    old = "#include <linux/pgtable.h>\n"
    new = """#include <linux/version.h>
/* ksu54_sucompat_pgtable: <linux/pgtable.h> was split out in 5.8. */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 8, 0)
#include <asm/pgtable.h>
#else
#include <linux/pgtable.h>
#endif
"""
    text = replace_once(text, old, new, "sucompat pgtable include")
    write(path, text)
    print("  feature/sucompat.c: 5.4 pgtable include fallback")


def patch_core_init(su: Path) -> None:
    path = su / "core/init.c"
    text = read(path)
    if "susfs_init()" in text:
        return
    anchor = """    ret = ksu_selinux_inode_init();
    if (ret) {
        put_cred(ksu_cred);
        ksu_cred = NULL;
        return ret;
    }
"""
    add = """
#ifdef CONFIG_KSU_SUSFS
    /* susfs_init() lives in fs/susfs.c and expects ksu_cred + SELinux ready. */
    {
        extern void susfs_init(void);
        susfs_init();
    }
#endif
"""
    text = replace_once(text, anchor, anchor + add, "core/init.c selinux init")
    write(path, text)
    print("  core/init.c: call susfs_init()")


def patch_selinux_wrapper(su: Path) -> None:
    path = su / "selinux/selinux.c"
    text = read(path)
    if "susfs_is_current_ksu_domain" in text:
        return
    block = r"""
/* ksu54 SUSFS glue: fs/susfs.c resolves this symbol, SukiSU calls it
 * is_ksu_domain().  Built-in only, no EXPORT_SYMBOL needed. */
#ifdef CONFIG_KSU_SUSFS
bool susfs_is_current_ksu_domain(void)
{
	return is_ksu_domain();
}
#endif
"""
    text = text.rstrip() + "\n" + block
    write(path, text)
    print("  selinux/selinux.c: susfs_is_current_ksu_domain() wrapper")


def patch_susfs_dispatch(su: Path) -> None:
    """Wire the in-tree SUSFS v2.1.0 command ABI into SukiSU.

    SukiSU main only ships a stub extension handler; ksud still sends every
    SUSFS command through reboot(KSU_INSTALL_MAGIC1, SUSFS_MAGIC, cmd, payload).
    The old KernelSU submodule used to provide this dispatcher; the odin
    fs/susfs.c only defines the individual command functions.
    """
    path = su / "extension/susfs_extension.c"
    text = read(path)
    if "ksu_handle_susfs_command" in text:
        print("  extension/susfs_extension.c: SUSFS command dispatch already applied")
        return
    for inc in ("#include <linux/cred.h>", "#include <linux/susfs.h>", "#include <linux/susfs_def.h>"):
        if inc not in text:
            text = replace_once(
                text,
                "#include <linux/errno.h>\n",
                "#include <linux/errno.h>\n" + inc + "\n",
                "susfs_extension includes",
            )
    text += r'''

#ifdef CONFIG_KSU_SUSFS
/*
 * ksu_handle_susfs_command - dispatch the reboot(2)-based SUSFS ABI.
 *
 * ksud passes a user pointer to the command payload.  The SUSFS helpers take
 * a kernel pointer to that user pointer, so keep a local copy and hand its
 * address to them.  This runs from task_work, never from kprobe context, so
 * sleeping operations (kern_path, copy_from_user, mutexes) are safe.
 */
int ksu_handle_susfs_command(unsigned int cmd, void __user *payload)
{
    void __user *p = payload;

    if (current_uid().val != 0)
        return -EPERM;

    switch (cmd) {
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
    case CMD_SUSFS_ADD_SUS_PATH:
        susfs_add_sus_path(&p);
        return 0;
    case CMD_SUSFS_ADD_SUS_PATH_LOOP:
        susfs_add_sus_path_loop(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
    case CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS:
        susfs_set_hide_sus_mnts_for_non_su_procs(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
    case CMD_SUSFS_ADD_SUS_KSTAT:
    case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:
        susfs_add_sus_kstat(&p);
        return 0;
    case CMD_SUSFS_UPDATE_SUS_KSTAT:
        susfs_update_sus_kstat(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
    case CMD_SUSFS_SET_UNAME:
        susfs_set_uname(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
    case CMD_SUSFS_ENABLE_LOG:
        susfs_enable_log(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
    case CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:
        susfs_set_cmdline_or_bootconfig(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
    case CMD_SUSFS_ADD_OPEN_REDIRECT:
        susfs_add_open_redirect(&p);
        return 0;
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
    case CMD_SUSFS_ADD_SUS_MAP:
        susfs_add_sus_map(&p);
        return 0;
#endif
    case CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING:
        susfs_set_avc_log_spoofing(&p);
        return 0;
    case CMD_SUSFS_SHOW_ENABLED_FEATURES:
        susfs_get_enabled_features(&p);
        return 0;
    case CMD_SUSFS_SHOW_VARIANT:
        susfs_show_variant(&p);
        return 0;
    case CMD_SUSFS_SHOW_VERSION:
        susfs_show_version(&p);
        return 0;
    default:
        return -EINVAL;
    }
}
#endif /* CONFIG_KSU_SUSFS */
'''
    write(path, text)
    print("  extension/susfs_extension.c: SUSFS command dispatch (reboot ABI)")


def patch_susfs_reboot_hook(su: Path) -> None:
    """Schedule SUSFS reboot-ABI commands from SukiSU's reboot kprobe.

    The kprobe pre_handler is atomic; queue a task_work callback so the SUSFS
    helpers can sleep.  ksud's payload pointer is still valid when task_work
    runs on the return-to-user path.
    """
    path = su / "supercall/supercall.c"
    text = read(path)
    if "ksu_susfs_tw_func" in text:
        print("  supercall/supercall.c: SUSFS reboot hook already applied")
        return
    text = replace_once(
        text,
        "#include <linux/version.h>\n",
        "#include <linux/version.h>\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "#include <linux/susfs_def.h>\n"
        "extern int ksu_handle_susfs_command(unsigned int cmd, void __user *payload);\n"
        "struct ksu_susfs_tw {\n"
        "    struct callback_head cb;\n"
        "    unsigned int cmd;\n"
        "    void __user *payload;\n"
        "};\n"
        "static void ksu_susfs_tw_func(struct callback_head *cb)\n"
        "{\n"
        "    struct ksu_susfs_tw *tw = container_of(cb, struct ksu_susfs_tw, cb);\n"
        "    ksu_handle_susfs_command(tw->cmd, tw->payload);\n"
        "    kfree(tw);\n"
        "}\n"
        "#endif\n",
        "supercall susfs includes",
    )
    text = replace_once(
        text,
        "        if (task_work_add(current, &tw->cb, TWA_RESUME)) {\n"
        "            kfree(tw);\n"
        "            pr_warn(\"install fd add task_work failed\\n\");\n"
        "        }\n"
        "    }\n"
        "\n"
        "    return 0;\n"
        "}",
        "        if (task_work_add(current, &tw->cb, TWA_RESUME)) {\n"
        "            kfree(tw);\n"
        "            pr_warn(\"install fd add task_work failed\\n\");\n"
        "        }\n"
        "    }\n"
        "\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "    if (magic1 == KSU_INSTALL_MAGIC1 && (unsigned int)magic2 == SUSFS_MAGIC) {\n"
        "        struct ksu_susfs_tw *tw;\n"
        "        unsigned int cmd = (unsigned int)PT_REGS_PARM3(real_regs);\n"
        "        void __user *payload = (void __user *)PT_REGS_SYSCALL_PARM4(real_regs);\n"
        "\n"
        "        tw = kzalloc(sizeof(*tw), GFP_ATOMIC);\n"
        "        if (!tw)\n"
        "            return 0;\n"
        "        tw->cmd = cmd;\n"
        "        tw->payload = payload;\n"
        "        tw->cb.func = ksu_susfs_tw_func;\n"
        "        if (task_work_add(current, &tw->cb, TWA_RESUME)) {\n"
        "            kfree(tw);\n"
        "            pr_warn(\"susfs add task_work failed\\n\");\n"
        "        }\n"
        "    }\n"
        "#endif\n"
        "\n"
        "    return 0;\n"
        "}",
        "supercall reboot kprobe",
    )
    write(path, text)
    print("  supercall/supercall.c: SUSFS reboot task_work hook")


def patch_susfs_sdcard_monitor(su: Path) -> None:
    path = su / "runtime/boot_event.c"
    text = read(path)
    if "susfs_start_sdcard_monitor_fn" in text:
        print("  runtime/boot_event.c: sdcard monitor already started")
        return
    if "#include <linux/susfs.h>" not in text:
        text = replace_once(
            text,
            "#include <linux/printk.h>\n",
            "#include <linux/printk.h>\n#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n",
            "boot_event susfs include",
        )
    text = replace_once(
        text,
        "    ksu_avc_spoof_late_init();\n",
        "    ksu_avc_spoof_late_init();\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "    susfs_start_sdcard_monitor_fn();\n"
        "#endif\n",
        "boot_event sdcard monitor call",
    )
    write(path, text)
    print("  runtime/boot_event.c: susfs_start_sdcard_monitor_fn()")


def ensure_driver_links(kdir: Path, su: Path) -> None:
    """The setup.sh symlink is normally created by the workflow; make the
    script self-sufficient for local/static verification."""
    drv = kdir / "drivers/kernelsu"
    if not (drv / "Kbuild").exists():
        if drv.exists() or drv.is_symlink():
            if drv.is_dir() and not drv.is_symlink():
                # Do not delete a real directory with content.
                if any(drv.iterdir()):
                    fail(f"{drv} exists but is not the SukiSU kernel dir")
                drv.rmdir()
            else:
                drv.unlink()
        os.symlink("../KernelSU/kernel", drv)
        print("  created drivers/kernelsu -> ../KernelSU/kernel")

    mk = read(kdir / "drivers/Makefile")
    if "obj-$(CONFIG_KSU) += kernelsu/" not in mk:
        write(kdir / "drivers/Makefile", mk + "\nobj-$(CONFIG_KSU) += kernelsu/\n")
    kc = read(kdir / "drivers/Kconfig")
    if 'source "drivers/kernelsu/Kconfig"' not in kc:
        write(kdir / "drivers/Kconfig", kc + '\nsource "drivers/kernelsu/Kconfig"\n')


def patch_susfs_setuid_mark(su: Path) -> None:
    """Mark zygote children as umounted so the SUSFS inode hooks apply.

    SUSFS checks SUSFS_IS_INODE_* via susfs_is_current_proc_umounted_app(),
    which needs TIF_PROC_UMOUNTED on the app process.  SukiSU's setuid hook is
    the equivalent of FinaSU's, but it never set that flag, so sus_path /
    sus_map / open_redirect entries were accepted by the dispatcher and then
    ignored for every app.  SELinux still reports the zygote domain after
    setresuid() (the transition happens at exec), which is why the existing
    ksu_handle_umount() check works at this point.
    """
    path = su / "hook/setuid_hook.c"
    text = read(path)
    if "susfs_set_current_proc_umounted" in text:
        print("  hook/setuid_hook.c: SUSFS app marking already applied")
        return

    anchor = '#include "feature/mount_hide.h"\n'
    add = '''#include "feature/mount_hide.h"

#ifdef CONFIG_KSU_SUSFS
#include <linux/workqueue.h>
#include <linux/susfs_def.h>
#include "selinux/selinux.h"

extern struct work_struct susfs_extra_works;
#endif
'''
    text = replace_once(text, anchor, add, "setuid_hook includes")

    anchor = "    // Handle kernel umount\n    ksu_handle_umount(old_uid, new_uid);\n"
    add = '''    // Handle kernel umount
    ksu_handle_umount(old_uid, new_uid);

#ifdef CONFIG_KSU_SUSFS
    /* ksu54_susfs_setuid: mark app processes so SUSFS inode checks apply. */
    if (is_zygote(current_cred()) &&
        (is_appuid(new_uid) || new_uid == WEBVIEW_ZYGOTE_UID ||
         is_isolated_process(new_uid))) {
        susfs_set_current_proc_umounted();
        schedule_work(&susfs_extra_works);
    }
#endif
'''
    text = replace_once(text, anchor, add, "setuid_hook SUSFS marking")
    write(path, text)
    print("  hook/setuid_hook.c: mark app processes for SUSFS")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", default="kernel", help="kernel tree root")
    ap.add_argument("--sukisu", default=None, help="SukiSU kernel dir (default <kernel>/KernelSU/kernel)")
    args = ap.parse_args()

    kdir = Path(args.kernel).resolve()
    su = Path(args.sukisu).resolve() if args.sukisu else kdir / "KernelSU/kernel"
    if not (su / "Kbuild").is_file():
        fail(f"not a SukiSU kernel tree: {su}")
    if not (kdir / "Makefile").is_file():
        fail(f"not a kernel tree: {kdir}")

    script_dir = Path(__file__).resolve().parent
    print(f"[sukisu-setup] kernel={kdir}")
    print(f"[sukisu-setup] sukisu={su}")

    ensure_driver_links(kdir, su)
    install_compat_header(kdir, su, script_dir)
    install_header_shims(kdir)
    strip_legacy_hooks(kdir)
    add_susfs_kconfig(su)
    patch_sepolicy_h(su)
    patch_rules(su)
    patch_sepolicy_c(su)
    patch_selinux_hide(su)
    patch_patch_memory(su)
    patch_sucompat_pgtable(su)
    patch_core_init(su)
    patch_selinux_wrapper(su)
    patch_susfs_dispatch(su)
    patch_susfs_reboot_hook(su)
    patch_susfs_sdcard_monitor(su)
    patch_susfs_setuid_mark(su)

    print("[sukisu-setup] done")


if __name__ == "__main__":
    main()


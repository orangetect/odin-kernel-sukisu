/*
 * ksu54_compat.h - Linux 5.4 compatibility layer for SukiSU on sm8350 (odin)
 *
 * Design: fill in APIs that simply do not exist on 5.4; do not change
 * semantics.  The file is copied to <kernel>/include/linux/ksu54_compat.h by
 * scripts/sukisu-setup.py and injected into every kernelsu translation unit:
 *
 *     ccflags-y += -include $(srctree)/include/linux/ksu54_compat.h
 *
 * Structural differences (struct seccomp_filter.filter_count,
 * struct selinux_policy, ...) are handled by explicit source edits in
 * scripts/sukisu-setup.py, not by this header.
 */
#ifndef _KSU54_COMPAT_H
#define _KSU54_COMPAT_H

#include <linux/version.h>
#include <linux/types.h>
#include <linux/kernel.h>
#include <linux/string.h>
#include <linux/errno.h>

/* 5.8: <linux/pgtable.h> was split out of <asm/pgtable.h>. */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 8, 0)
#include <asm/pgtable.h>

/* p4d is folded into pgd before 5.8. */
#ifndef __p4d_to_phys
#define __p4d_to_phys(p4d) __pgd_to_phys(p4d)
#endif
#endif /* < 5.8 */


/* 5.8: task_work TWA_* enum; 5.4 task_work_add() takes a bool. */
#include <linux/task_work.h>

#ifndef TWA_RESUME
#define TWA_RESUME	true
#endif
#ifndef TWA_NONE
#define TWA_NONE	false
#endif
#ifndef TWA_SIGNAL
#define TWA_SIGNAL	true
#endif

/* 5.10: <linux/minmax.h> split out of <linux/kernel.h>. */
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 10, 0)
#ifndef min_t
#define min_t(type, x, y) \
	({ type __min1 = (x); type __min2 = (y); __min1 < __min2 ? __min1 : __min2; })
#endif
#ifndef max_t
#define max_t(type, x, y) \
	({ type __max1 = (x); type __max2 = (y); __max1 > __max2 ? __max1 : __max2; })
#endif
#endif /* < 5.10 */

/* 6.2: <linux/hex.h> split out; 5.4 declares bin2hex() in <linux/kernel.h>. */

#endif /* _KSU54_COMPAT_H */




# odin-kernel-sukisu

> 小米 MIX 4（odin / SM8350-AC）Linux 5.4 内核，内置
> [SukiSU-Ultra](https://github.com/SukiSU-Ultra/SukiSU-Ultra) v4.3.0-r2 + odin 自带 SUSFS v2.1.0。
>
> 本仓库由 [odin-kernel-finaisu](https://github.com/orangetect/odin-kernel-finaisu2) 改造而来，
> 内核源码使用 [Inkypen79/kernel_xiaomi_odin](https://github.com/Inkypen79/kernel_xiaomi_odin)
> 的 `resukisu` 分支（已带 SUSFS 与 KSU 钩子），机型配置参考
> [Inkypen79/device_xiaomi_odin](https://github.com/Inkypen79/device_xiaomi_odin)。
>
> ⚠️ **尚未在 MIX 4 实机上验证。** 5.4 厂商内核与 SukiSU 6.x 代码存在大量 ABI 差异，
> 本仓库用 5.4 兼容层做了静态适配；刷机风险自负。

---

## 目标设备

| 项 | 值 |
|---|---|
| 机型 | Xiaomi MIX 4（odin / 2106118C） |
| SoC | Snapdragon 888+ / SM8350-AC（lahaina 平台） |
| 内核基线 | Linux 5.4.302，`Inkypen79/kernel_xiaomi_odin` @ `resukisu` |
| Root | SukiSU-Ultra v4.3.0-r2（KSU 版本 41150） |
| SUSFS | 内核树自带 v2.1.0（基础功能） |
| 分区 | A/B，只刷 `boot`；`vendor_boot` 模块不动 |

## 功能

- SukiSU-Ultra `main` 分支的 kprobe / `sys_enter` tracepoint 钩子，**不依赖旧版内核里的
  `ksu_handle_*` 手动调用点**。
- odin 内核树自带的 SUSFS v2.1.0：`sus_path`、`sus_mount`、`sus_kstat`、`open_redirect`、
  `sus_map`、`spoof_uname`、`spoof_cmdline` 等基础功能。
- SukiSU 的 SUSFS 控制面已接上：`reboot(SUSFS_MAGIC, ...)` 命令在 `reboot` kprobe 里
  转入 `task_work`，再分发给 odin `fs/susfs.c` 的各命令处理函数；启动完成时调用
  `susfs_start_sdcard_monitor_fn()`。
- setuid 钩子会给 zygote 派生的应用进程设置 `TIF_PROC_UMOUNTED`，并调度
  `susfs_extra_works`；否则 SUSFS 的 `sus_path` / `sus_map` / `open_redirect`
  规则只会在内核里登记，不会真正命中应用进程。
- 5.4 兼容层：
  - `struct selinux_policy` / `selinux_state.policy` → `selinux_state.ss` 影子策略；
  - `ksu_dup_sepolicy()` / `ksu_destroy_sepolicy()` 的 5.4 `policydb_write/read` 回移；
  - `selinux_hide` 的 `security_context_to_sid_default()` 等 5.4 服务替换；
  - `phys_from_virt()` 的 5.4 block-PMD 识别（否则 `sys_call_table` 补丁失败，
    `ksud` 永远不会启动，管理器就会显示“未 root”）；
  - `pkg_observer` 的 5.4 `fsnotify_ops.handle_event` 适配（5.4 没有 `handle_inode_event` 字段）；
  - `put_task_struct()` 的 `sched/task.h` 头文件、`clocksource.vdso_clock_mode` 的 5.4 保护；
  - `sepolicy` 的 5.4 filename transition 回退（5.4 没有 `filename_trans_key` 链表）；
  - `supercall/dispatch` 的 5.4 `tasklist_lock` / `init_task` 头文件补齐；
  - 删除 odin 树里旧 ReSukiSU 的 `ksu_handle_execveat/faccessat/stat/...` 调用点。
- 输入 boost 关闭、io-is-busy 关闭、schedutil 使用 PELT 的调度补丁（沿用 FinaSU 仓库）。
- AnyKernel3 包内内置与 v4.3.0-r2 匹配的 `ksud-aarch64-linux-android`。

## 构建

1. 把本目录推到自己的 GitHub 仓库。
2. Actions → **Build odin kernel with SukiSU-Ultra (5.4 + SUSFS)** → Run workflow。
3. 默认参数：
   - `sukisu_ref=v4.3.0-r2`（也可以填 `main`；main 版本号会按完整提交数计算）
   - `kernel_ref=resukisu`
   - `ksu_version=41150`（仅 tag 构建使用；main 构建会自动计算）
   - `embed_ksud=true`
4. 构建完成后下载 `odin-SukiSU-<date>-run<N>.zip`，以及 artifact 里的 `Image` / `kernel.config`。

工作流会：

- clone 内核与 SukiSU；
- 运行 `scripts/sukisu-setup.py` 打 5.4 兼容补丁；
- 先编译 `security/selinux/` 与 `drivers/kernelsu/` 做快速门禁；
- 用 ZyC clang 14.0.6 编译 `Image` / `Image.gz`；
- 打包 AnyKernel3（`device.name1=odin`，`BLOCK=/dev/block/bootdevice/by-name/boot`，
  `IS_SLOT_DEVICE=1`）；
- 发一个 prerelease。

## 刷机

- 用 TWRP 或内核刷写工具刷 AnyKernel3 zip；
- 只写 `boot`，不要刷 `vendor_boot`；
- 首次启动后安装 **SukiSU-Ultra v4.3.0-r2 管理器**：
  <https://github.com/SukiSU-Ultra/SukiSU-Ultra/releases/download/v4.3.0-r2/SukiSU_v4.3.0-r2_41150-release.apk>
  （包名 `com.sukisu.ultra`）；
- 保留原厂 `boot.img` 备份，方便回滚。

## 已知限制

- **未实机验证**：SukiSU 官方只保证 GKI 2.0（5.10+），4.14/5.4 属于“可识别但需自行适配”。
  本仓库的 5.4 兼容层是静态移植，首次启动仍可能失败。
- **SUSFS 是 v2.1.0**：SukiSU v4.3.0 的 `ksud` 认识 `CMD_SUSFS_SET_PRIORITY_UID_FILTER`
  （0x60030），odin 的 v2.1.0 没有该命令；管理器中“优先级 UID 过滤”一类新开关可能报
  `not supported`。基础隐藏功能不受影响。
- `susfs4ksu` 的 `kernel-5.4` 分支停留在 2025-02，无法直接升级到 v2.3；本仓库没有做
  SUSFS 大版本移植。
- 内核用 ZyC clang 14.0.6 构建；`odin_defconfig` 里有 LTO/CFI 相关选项，若 CI 报
  LTO/CFI 错误，可在 `out/.config` 关闭后重试。
- `vendor_boot` 里的模块（`msm_drm.ko`、`fts_touch_spi.ko`、`hwid.ko`、
  `xiaomi_touch.ko`）没有随内核更新；若内核与模块 vermagic 不一致，可能影响显示/触控。
- 只支持已解锁 bootloader 的设备；AVB 行为与 ROM 有关。

## 目录

```
.github/workflows/build-sukisu.yml   CI：clone → 5.4 适配 → 编译 → AK3 → release
scripts/sukisu-setup.py              5.4 兼容层（SELinux / SUSFS / PMD / 旧钩子清理）
scripts/ksu54-compat.h               5.4 头文件/内联函数兼容
scripts/ak3-ksud.sh                  AnyKernel3 安装 ksud
scripts/sched-tune.sh                调度补丁
scripts/power-tune.sh                默认 governor / 功耗配置
scripts/sched-patches/               s1/s2/pelt 补丁
```

## 验证要点

刷入后：

```sh
adb shell cat /proc/version
adb shell dmesg | grep -iE 'KernelSU|SukiSU|ksu|susfs|hook_manager|patch syscall|ksud'
adb shell ls -lZ /data/adb/ksud /data/adb/ksu/bin/ksud
adb shell /data/adb/ksud -V
```

期望：

- `KernelSU version: 41150` 或 `SukiSU ... 41150`；
- `patch syscall` / `dispatcher installed` / `sys_enter tracepoint registered` 一类日志；
- `/data/adb/ksud -V` 输出 `4.3.0-r2`；
- 管理器能识别内核版本并出现 root 授权页。

如果管理器仍显示未 root，优先看 `dmesg` 里 `patch syscall` 是否失败，以及
`/data/adb/ksud` 是否存在。

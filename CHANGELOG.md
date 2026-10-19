# Changelog

本项目的所有重要变更都记录在这里。

格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本 SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 低电量弹窗：检测到 Steam 游戏退出且电量低于阈值时弹出置顶窗口
- 设置页：常规 / 悬浮窗 / 低电量弹窗 / 电量曲线四组共 13 项开关，改动即时生效
- `--settings` 参数可直接打开设置页

### 修复

- 修复托盘进程随机崩溃：`GetModuleHandleW` 未声明 `restype`，64 位 `HMODULE` 被截断后
  作为 `hInstance` 传入窗口类注册，触发偶发访问冲突（已同步到 `main` 的 v1.0.1）
- 退出时等待采样线程结束，避免 Python 3.13+ 在解释器 finalize 阶段报 GIL 致命错误

## [1.1.0] - 2026-10-19

### 新增

- 新增电量曲线窗口（右键托盘 → 电量曲线…）
- 新增剩余使用时长预估（最近 3 小时放电速率线性回归）

## [1.0.0] - 2026-10-19

### Added

- 托盘图标：电池形状，填充比例与颜色随电量变化，鼠标悬停显示百分比
- 桌面悬浮窗：置顶、可拖动、记住位置、每 30 秒自动刷新
- 低电量三档配色：>50% 绿 / 21–50% 琥珀 / ≤20% 红（数字、进度条、托盘图标同步）
- 充电状态显示：使用中 / 充电中 / 已充满
- 命令行模式，支持 `--json`、`--raw`、`--frame`、`--list`、`-n/-i`、`--version`
- 开机自启安装 / 移除脚本
- 托盘图标运行时自动生成（仓库不含二进制 .ico）
- 逆向出的 HID 协议文档：`docs/findings-static.md`
- 逆向过程探针脚本存档：`recon/`

### Changed

- 100% 且插线时显示「已充满」（设备固件不会上报 `state=2`）
- 「放电中」文案改为「使用中」

### Fixed

- 无

[Unreleased]: https://github.com/Nefeli0721/g3m-battery/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Nefeli0721/g3m-battery/releases/tag/v1.0.0

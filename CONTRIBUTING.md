# 贡献与分支模型

## 三条分支

| 分支 | 定位 | 包含功能 | 允许的变更 | 版本号 |
|---|---|---|---|---|
| **`main`** | **标准版**（默认分支） | 托盘 + 悬浮窗 + 电量曲线 + 设置页 + 低电量弹窗 | 全部：新功能 / 修复 / 设备适配 | minor / major / patch |
| **`lite`** | **极简版** | 托盘 + 悬浮窗 + 命令行（无曲线 / 设置 / 弹窗） | 只收 **bug 修复** 与 **设备适配** | 只发 patch，保持 `1.0.x` |
| **`dev`** | **开发/集成分支** | 与 `main` 同步 + 正在开发的功能 | 所有新功能先在这里 | 不直接发版 |

## 典型流程

**加新功能**

```powershell
git switch dev
# ...开发、提交...
git commit -am "feat: 一个有趣的新功能"
# 自测通过后合并到标准版
git switch main
git merge dev
python release.py 1.3.0 "新增一个有趣的新功能" --kind feature
```

**修 bug（标准版）**

```powershell
git switch main
git commit -am "fix: 修复某个问题"
python release.py 1.2.2 "修复某个问题" --kind bugfix
```

**修 bug（极简版）**

```powershell
git switch lite
git commit -am "fix: 修复某个问题"
python release.py 1.0.2 "修复某个问题" --kind bugfix
```

修在 `main` 上的问题通常要**手动移植**到 `lite`（两条线代码不同，不能直接 merge 新功能过去）。

## `release.py` 强制校验

- 在 `dev` 上发布 → 拒绝，提示先合并到 `main`
- 在 `lite` 上发布 `--kind feature` → 拒绝
- 在 `lite` 上发 minor / major → 拒绝，只允许 patch
- 不在 `main` / `lite` 上 → 拒绝
- 工作区不干净、tag 已存在、版本号没递增 → 拒绝

## 提交信息

沿用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat:` | 新功能（在 `dev` 开发） | `feat: 低电量通知` |
| `fix:` | bug 修复 | `fix: 休眠后无法恢复` |
| `feat(device):` | 新增设备支持 | `feat(device): 支持 G5M Pro` |
| `docs:` / `chore:` | 文档、脚本、杂项 | `docs: 补充协议说明` |

## 发布前自检

```powershell
python -m unittest discover -s tests -v      # 单元测试
python -m py_compile g3m_battery.py battery_tray.pyw battery_curve.py battery_history.py make_icons.py release.py
python g3m_battery.py --version
python g3m_battery.py                        # 实机读一次
pythonw battery_tray.pyw --curve             # 打开曲线窗口看一眼
python release.py <新版本> "说明" --kind <bugfix|device|feature> --dry-run
```

> 在 `lite` 分支上，`battery_curve.py` / `battery_popup.py` / `steam_watch.py` /
> `app_settings.py` / `settings_window.py` 这些文件不存在，只编译存在的文件即可。

# 贡献与分支策略

## 分支模型

| 分支 | 定位 | 允许的变更 | 版本号 |
|---|---|---|---|
| **`main`** | **轻量化稳定版** | 只收 **bug 修复** 和 **设备适配**（新增 VID/PID） | 只发 patch：`1.0.x` |
| **`dev`** | **功能分支** | 所有**新功能**、重构、体验改进 | minor / major：`1.1.0`、`2.0.0` |

`main` 的目标是**保持轻量**：代码量不膨胀、零依赖不变、不做功能加法。
任何会让工具变"重"的改动（新面板、通知系统、多设备管理、插件机制…）一律走 `dev`。

### 典型流程

**修 bug / 加设备（走 main）**

```powershell
git switch main
# ...改代码...
git commit -am "fix: 修复休眠唤醒后首次读取失败"
python release.py 1.0.1 "修复休眠唤醒后首次读取失败" --kind bugfix
```

**加新功能（走 dev）**

```powershell
git switch dev
# ...开发功能...
git commit -am "feat: 低电量 Windows 通知"
python release.py 1.1.0 "新增低电量通知" --kind feature
```

`release.py` 会**强制校验**：

- 在 `main` 上发布 `--kind feature` → 直接拒绝，并提示切到 `dev`
- 在 `main` 上发布 minor/major 版本 → 拒绝，只允许 patch
- 不在 `main` / `dev` 上 → 拒绝
- 工作区不干净、tag 已存在、版本号没递增 → 拒绝

## 提交信息

沿用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat:` | 新功能（仅 `dev`） | `feat: 低电量通知` |
| `fix:` | bug 修复 | `fix: 休眠后无法恢复` |
| `feat(device):` | 新增设备支持 | `feat(device): 支持 G5M Pro` |
| `docs:` / `chore:` | 文档、脚本、杂项 | `docs: 补充协议说明` |

## 发布前自检

```powershell
python -m py_compile g3m_battery.py battery_tray.pyw make_icons.py release.py
python g3m_battery.py --version
python g3m_battery.py            # 实机读一次
python release.py <新版本> "说明" --kind <bugfix|device|feature> --dry-run
```

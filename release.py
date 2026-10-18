"""一键发布脚本：改版本号 → 写 CHANGELOG → commit → 打 tag → push → 建 GitHub Release。

分支策略（脚本会强制执行）：
  * ``main`` 是**轻量化稳定分支**，只接受 **bug 修复** 与 **设备适配**，
    且只发 patch 版本（1.0.x）；新功能一律拒绝。
  * ``dev`` 是**功能分支**，新功能在这里开发，可发 minor / major 版本。

用法（在仓库根目录）::

    python release.py 1.0.1 "修复休眠后无法恢复" --kind bugfix      # main 上
    python release.py 1.1.0 "新增低电量通知" --kind feature          # dev 上
    python release.py 1.0.2 "支持 G5M Pro" --kind device            # main 上
    python release.py 1.1.0 "..." --dry-run                        # 只看计划
    python release.py 1.1.0 "..." --no-push                        # 只本地提交打 tag

约定：
  * `g3m_battery.py` 里的 `__version__` 是**唯一版本号来源**
  * 版本号遵循 SemVer：新增功能 = minor，修 bug / 加设备 = patch，破坏兼容 = major
  * 发布前工作区必须是干净的（先提交你的改动）
  * tag 形如 `v1.0.1`，会推到 origin 并创建 GitHub Release（需已 `gh auth login`）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT, "g3m_battery.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

REPO_URL = "https://github.com/Nefeli0721/g3m-battery"

# kind -> (CHANGELOG 小节标题, 发布说明里的中文名)
KIND_SECTION = {
    "feature": ("新增", "新功能"),
    "bugfix": ("修复", "bug 修复"),
    "device": ("设备支持", "设备适配"),
}

ALLOWED_BRANCHES = ("main", "dev")


def run(cmd: list[str], check: bool = True, capture: bool = False) -> str:
    proc = subprocess.run(
        cmd, cwd=ROOT, text=True, encoding="utf-8",
        capture_output=capture)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"命令失败: {' '.join(cmd)}\n{detail}")
    return (proc.stdout or "") if capture else ""


def git(*args: str, **kw) -> str:
    return run(["git", *args], **kw)


def read_version() -> str:
    with open(VERSION_FILE, encoding="utf-8") as f:
        m = VERSION_RE.search(f.read())
    if not m:
        raise SystemExit("在 g3m_battery.py 里找不到 __version__")
    return m.group(1)


def parse_semver(text: str) -> tuple[int, int, int]:
    m = SEMVER_RE.match(text)
    if not m:
        raise SystemExit(f"版本号必须形如 1.2.3，收到: {text}")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def write_text(path: str, text: str) -> None:
    """显式 UTF-8 + LF，避免 Windows PowerShell 的 GBK 编码坑。"""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def bump_version(old: str, new: str) -> None:
    with open(VERSION_FILE, encoding="utf-8") as f:
        text = f.read()
    text = VERSION_RE.sub(f'__version__ = "{new}"', text, count=1)
    write_text(VERSION_FILE, text)


def update_changelog(new: str, notes: list[str], kind: str) -> None:
    with open(CHANGELOG, encoding="utf-8") as f:
        text = f.read()
    if "## [Unreleased]" not in text:
        raise SystemExit("CHANGELOG.md 缺少 `## [Unreleased]` 段落")

    section_title = KIND_SECTION[kind][0]
    date = _dt.date.today().isoformat()
    bullets = "\n".join(f"- {line.strip()}" for line in notes if line.strip())
    section = f"## [{new}] - {date}\n\n### {section_title}\n\n{bullets}\n\n"

    marker = "## [Unreleased]"
    idx = text.index(marker) + len(marker)
    rest = text[idx:]
    if rest.startswith("\n\n"):
        rest = rest[2:]
    text = text[:idx] + "\n\n" + section + rest.lstrip("\n")
    write_text(CHANGELOG, text)


def check_clean() -> None:
    dirty = git("status", "--porcelain", capture=True).strip()
    if dirty:
        raise SystemExit("工作区不干净，请先提交或暂存改动：\n" + dirty)


def check_tag_free(tag: str) -> None:
    existing = git("tag", "-l", tag, capture=True).strip()
    if existing:
        raise SystemExit(f"tag {tag} 已存在")


def check_branch(kind: str) -> str:
    """校验当前分支与发布类型是否匹配，返回分支名。"""
    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True).strip()
    if branch not in ALLOWED_BRANCHES:
        raise SystemExit(
            f"当前分支是 {branch}，发布只能在 {' / '.join(ALLOWED_BRANCHES)} 上进行。\n"
            "  main = 轻量稳定版（bug 修复 / 设备适配）\n"
            "  dev  = 功能分支（新功能）")
    if branch == "main" and kind == "feature":
        raise SystemExit(
            "main 是轻量化稳定分支，只接受 bug 修复与设备适配。\n"
            "新功能请切到功能分支再发布：\n"
            "  git switch dev")
    return branch


def check_bump_on_branch(branch: str, old: str, new: str) -> None:
    old_t, new_t = parse_semver(old), parse_semver(new)
    if branch == "main" and new_t[:2] != old_t[:2]:
        raise SystemExit(
            f"main 只发 patch 版本（{old_t[0]}.{old_t[1]}.x），"
            f"{old} -> {new} 属于 {('minor' if new_t[:1] == old_t[:1] else 'major')} 升级。\n"
            "功能版本请在 dev 分支发布。")
    if new_t <= old_t:
        raise SystemExit(f"新版本 {new} 必须大于当前版本 {old}")


def has_gh() -> bool:
    try:
        run(["gh", "--version"], check=False, capture=True)
        return True
    except FileNotFoundError:
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="发布新版本（会校验分支策略）")
    ap.add_argument("version", help="新版本号，如 1.0.1")
    ap.add_argument("notes", nargs="+", help="变更说明（可多段）")
    ap.add_argument("--kind", choices=sorted(KIND_SECTION), default="feature",
                    help="变更类型：bugfix / device / feature（默认 feature）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写不改不推")
    ap.add_argument("--no-push", action="store_true", help="不执行 git push")
    args = ap.parse_args(argv)

    old = read_version()
    new = args.version
    tag = f"v{new}"
    kind_label = KIND_SECTION[args.kind][1]

    check_clean()
    check_tag_free(tag)
    branch = check_branch(args.kind)
    check_bump_on_branch(branch, old, new)

    print(f"分支: {branch}   类型: {kind_label}")
    print(f"版本: {old} -> {new}   tag: {tag}")
    print("变更:")
    for line in args.notes:
        print(f"  - {line}")

    if args.dry_run:
        print("\n[dry-run] 将要执行：")
        print(f'  1. 修改 g3m_battery.py: __version__ = "{new}"')
        print(f"  2. 向 CHANGELOG.md 插入 `## [{new}]` / `### {KIND_SECTION[args.kind][0]}`")
        print(f"  3. git commit -m 'chore(release): {tag}'")
        print(f"  4. git tag -a {tag}")
        print("  5. git push origin " + branch + " --tags" +
              ("  (已禁用)" if args.no_push else ""))
        print(f"  6. gh release create {tag} ..." +
              ("  (已禁用)" if args.no_push else ""))
        return 0

    bump_version(old, new)
    update_changelog(new, args.notes, args.kind)
    print("已更新版本号与 CHANGELOG")

    git("add", "-A")
    git("commit", "-m", f"chore(release): {tag}")
    git("tag", "-a", tag, "-m", f"Release {tag}")
    print(f"已提交并打 tag {tag}")

    if args.no_push:
        print("跳过 push（--no-push）。手动推送：")
        print(f"  git push origin {branch} --tags")
        return 0

    git("push", "origin", branch)
    git("push", "origin", tag)
    print(f"已推送到 origin/{branch}")

    if has_gh():
        body = (
            f"分支：`{branch}`　类型：{kind_label}\n\n"
            + "\n".join(f"- {line}" for line in args.notes)
        )
        run(["gh", "release", "create", tag, "--title", tag,
             "--notes", body], check=False, capture=True)
        print("GitHub Release: 已尝试创建（失败可手动创建）")
    else:
        print("未检测到 gh，跳过 GitHub Release（可手动创建）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

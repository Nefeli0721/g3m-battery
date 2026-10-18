"""一键发布脚本：改版本号 → 写 CHANGELOG → commit → 打 tag → push → 建 GitHub Release。

用法（在仓库根目录）::

    python release.py 1.1.0 "新增低电量通知"
    python release.py 1.0.1 "修复休眠后无法恢复" --dry-run
    python release.py 1.1.0 "..." --no-push      # 只本地提交和打 tag

约定：
  * `g3m_battery.py` 里的 `__version__` 是**唯一版本号来源**
  * 版本号遵循 SemVer：新增功能 = minor，修 bug = patch，破坏兼容 = major
  * 发布前工作区必须是干净的（先提交你的功能改动）
  * tag 形如 `v1.1.0`，会被推到 origin 并创建 GitHub Release（需已 `gh auth login`）
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION_FILE = os.path.join(ROOT, "g3m_battery.py")
CHANGELOG = os.path.join(ROOT, "CHANGELOG.md")
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


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


def update_changelog(old: str, new: str, notes: list[str]) -> None:
    with open(CHANGELOG, encoding="utf-8") as f:
        text = f.read()
    if "## [Unreleased]" not in text:
        raise SystemExit("CHANGELOG.md 缺少 `## [Unreleased]` 段落")

    date = _dt.date.today().isoformat()
    bullets = "\n".join(f"- {line.strip()}" for line in notes if line.strip())
    section = f"## [{new}] - {date}\n\n### 变更\n\n{bullets}\n\n"

    # 插到 Unreleased 段落之后
    marker = "## [Unreleased]"
    idx = text.index(marker) + len(marker)
    rest = text[idx:]
    # 保留 Unreleased 与下个版本之间的空行
    if rest.startswith("\n\n"):
        rest = rest[2:]
    text = text[:idx] + "\n\n" + section + rest.lstrip("\n")

    # 补齐底部的比较链接
    repo = "https://github.com/Nefeli0721/g3m-battery"
    text = text.replace(
        f"[Unreleased]: {repo}/compare/v{old}...HEAD",
        f"[Unreleased]: {repo}/compare/v{new}...HEAD")
    if f"[{new}]:" not in text:
        text = text.rstrip("\n") + (
            f"\n[{new}]: {repo}/releases/tag/v{new}\n")
    write_text(CHANGELOG, text)


def check_clean() -> None:
    dirty = git("status", "--porcelain", capture=True).strip()
    if dirty:
        raise SystemExit(
            "工作区不干净，请先提交或暂存改动：\n" + dirty)


def check_tag_free(tag: str) -> None:
    existing = git("tag", "-l", tag, capture=True).strip()
    if existing:
        raise SystemExit(f"tag {tag} 已存在")


def check_on_main() -> None:
    branch = git("rev-parse", "--abbrev-ref", "HEAD", capture=True).strip()
    if branch != "main":
        raise SystemExit(f"当前分支是 {branch}，发布请在 main 上进行")


def has_gh() -> bool:
    try:
        run(["gh", "--version"], check=False, capture=True)
        return True
    except FileNotFoundError:
        return False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="发布新版本")
    ap.add_argument("version", help="新版本号，如 1.1.0")
    ap.add_argument("notes", nargs="+", help="变更说明（可多段）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不写不改不推")
    ap.add_argument("--no-push", action="store_true", help="不执行 git push")
    args = ap.parse_args(argv)

    old = read_version()
    new = args.version
    if parse_semver(new) <= parse_semver(old):
        raise SystemExit(f"新版本 {new} 必须大于当前版本 {old}")
    tag = f"v{new}"

    print(f"版本: {old} -> {new}   tag: {tag}")
    print("变更:")
    for line in args.notes:
        print(f"  - {line}")

    if args.dry_run:
        check_clean()
        check_tag_free(tag)
        check_on_main()
        print("\n[dry-run] 将要执行：")
        print(f"  1. 修改 g3m_battery.py: __version__ = \"{new}\"")
        print("  2. 向 CHANGELOG.md 插入新版本段落")
        print(f"  3. git commit -m 'chore(release): {tag}'")
        print(f"  4. git tag -a {tag}")
        print("  5. git push origin main --tags" +
              ("" if not args.no_push else "  (已禁用)"))
        print(f"  6. gh release create {tag} ..." +
              ("" if not args.no_push else "  (已禁用)"))
        return 0

    check_clean()
    check_tag_free(tag)
    check_on_main()

    bump_version(old, new)
    update_changelog(old, new, args.notes)
    print("已更新版本号与 CHANGELOG")

    git("add", "-A")
    git("commit", "-m", f"chore(release): {tag}")
    git("tag", "-a", tag, "-m", f"Release {tag}")
    print(f"已提交并打 tag {tag}")

    if args.no_push:
        print("跳过 push（--no-push）。手动推送：")
        print("  git push origin main --tags")
        return 0

    git("push", "origin", "main")
    git("push", "origin", tag)
    print("已推送到 origin")

    if has_gh():
        body = "\n".join(f"- {line}" for line in args.notes)
        gh = run(
            ["gh", "release", "create", tag, "--title", tag,
             "--notes", body], check=False, capture=True)
        print(f"GitHub Release: {'已创建' if gh is not None else '创建失败（可手动创建）'}")
    else:
        print("未检测到 gh，跳过 GitHub Release（可手动创建）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

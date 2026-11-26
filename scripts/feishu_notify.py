"""推送「代码待你合并」飞书卡片（collab 工作流的人类终审环节）。

扫描打开中的 PR，找出其关联 Issue 已 `review:agent-passed`（即「等人终审合并」）
的 PR，给配置的飞书会话推一张交互卡片；也可用 `--pr N` 只推单个 PR。

用法：
    python3 scripts/feishu_notify.py --chat-id oc_xxx
    python3 scripts/feishu_notify.py --pr 34 --chat-id oc_xxx --dry-run

依赖：本机已登录的 `gh` 与 `lark-cli`。聊天 id 优先取 `FEISHU_CHAT_ID` 环境变量，
也可用 `--user-id` 改成私聊。卡片带幂等键 `pr-<N>-<headSHA7>`，重复运行不会刷屏。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feishu_cards  # noqa: E402


def gh_exe() -> str:
    return os.environ.get("COLLAB_GH") or shutil.which("gh") or "gh"


def _gh_json(args: list[str], cwd: Path) -> list | dict:
    proc = subprocess.run([gh_exe(), *args], cwd=str(cwd), text=True, capture_output=True, timeout=120)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"gh {' '.join(args)} 失败：\n{detail}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"gh {' '.join(args)} 返回的不是 JSON：{proc.stdout[:500]}") from exc


def parse_issue_marker(body: str) -> int | None:
    """从 PR 正文解析 `<!-- collab:issue=N -->`。"""
    m = re.search(r"<!--\s*collab:issue=(\d+)\s*-->", body or "")
    return int(m.group(1)) if m else None


def _label_names(item: dict) -> list[str]:
    return [x.get("name", "") for x in item.get("labels") or []]


def pr_stage(cwd: Path, pr: dict) -> str | None:
    """返回 PR 的待人类处理阶段：'merge'（已终审，待合并）/ 'review'（待终审）；否则 None。"""
    issue_no = parse_issue_marker(pr.get("body") or "")
    if not issue_no:
        return None
    issue = _gh_json(["issue", "view", str(issue_no), "--json", "labels"], cwd)
    names = _label_names(issue) if isinstance(issue, dict) else []
    if "status:ready-to-merge" in names:
        return "merge"
    if "review:agent-passed" in names:
        return "review"
    return None


def _short_summary(body: str, limit: int = 120) -> str:
    for line in (body or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("<!--") or line.startswith("Refs") or line.startswith("collab:"):
            continue
        return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def build_pr_card_payload(cwd: Path, pr: dict, stage: str) -> tuple[dict, str]:
    """构造单张评审卡 + 幂等键。"""
    number = int(pr["number"])
    head_sha = pr.get("headRefOid", "")
    card = feishu_cards.build_review_card(
        pr_number=number,
        title=pr.get("title", ""),
        author=(pr.get("author") or {}).get("login", "未知") if isinstance(pr.get("author"), dict) else str(pr.get("author", "未知")),
        base_branch=pr.get("baseRefName", ""),
        head_sha=head_sha,
        url=pr.get("url", ""),
        summary=_short_summary(pr.get("body") or ""),
        stage=stage,
    )
    key = f"pr-{number}-{head_sha[:7]}"
    return card, key


def collect(cwd: Path, pr_filter: int | None, limit: int) -> list[tuple[dict, str]]:
    if pr_filter is not None:
        pr = _gh_json(
            ["pr", "view", str(pr_filter), "--json", "number,title,headRefOid,baseRefName,author,url,body,state"],
            cwd,
        )
        if not isinstance(pr, dict):
            raise SystemExit(f"PR #{pr_filter} 不存在")
        if pr.get("state") != "OPEN":
            raise SystemExit(f"PR #{pr_filter} 不是打开状态（{pr.get('state')}）")
        stage = pr_stage(cwd, pr) or "merge"
        return [(pr, stage)]
    prs = _gh_json(
        ["pr", "list", "--state", "open", "--limit", str(limit),
         "--json", "number,title,headRefOid,baseRefName,author,url,body,state"],
        cwd,
    )
    if not isinstance(prs, list):
        raise SystemExit("gh pr list 返回异常")
    out: list[tuple[dict, str]] = []
    for p in prs:
        if not isinstance(p, dict):
            continue
        stage = pr_stage(cwd, p)
        if stage:
            out.append((p, stage))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feishu_notify.py", description="推送「代码待你合并」飞书卡片")
    parser.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    parser.add_argument("--pr", type=int, default=None, help="只推单个 PR 号")
    parser.add_argument("--chat-id", default=os.environ.get("FEISHU_CHAT_ID", ""), help="飞书群聊 oc_xxx")
    parser.add_argument("--user-id", default=os.environ.get("FEISHU_USER_ID", ""), help="飞书私聊对象 ou_xxx")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的卡片，不真正发送")
    args = parser.parse_args(argv)

    cwd = Path(args.repo).resolve()
    if not cwd.is_dir():
        raise SystemExit(f"仓库路径不存在：{cwd}")
    if not args.chat_id and not args.user_id:
        raise SystemExit("缺少 --chat-id / --user-id（也可用环境变量 FEISHU_CHAT_ID / FEISHU_USER_ID）")

    prs = collect(cwd, args.pr, args.limit)
    if not prs:
        print("没有处于「等人终审/合并」的 PR。")
        return 0

    for pr, stage in prs:
        card, key = build_pr_card_payload(cwd, pr, stage)
        if args.dry_run:
            print(f"--- 将发送（幂等键 {key}，阶段 {stage}）---")
            print(json.dumps(card, ensure_ascii=False, indent=2))
            continue
        try:
            proc = feishu_cards.send_card(card, chat_id=args.chat_id or None, user_id=args.user_id or None, idempotency_key=key)
        except (RuntimeError, subprocess.SubprocessError) as exc:
            print(f"✖ 发送 PR #{pr['number']} 卡片失败：{exc}", file=sys.stderr)
            return 1
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            print(f"✖ 发送 PR #{pr['number']} 卡片失败：{detail}", file=sys.stderr)
            return 1
        print(f"✓ 已推送 PR #{pr['number']} 卡片（{key}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

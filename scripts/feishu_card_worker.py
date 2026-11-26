"""飞书卡片回调 worker：点一下卡片 → 执行 GitHub 动作 → 回写结果卡。

监听 `card.action.trigger` 事件（`lark-cli event consume`），校验点击者是
配置里的授权操作者，按按钮动作执行：
- merge  先 collab accept 记录终审（尽力而为），再 `gh pr merge --merge --match-head-commit`
- accept 只 collab accept（标记 ready-to-merge，不合并）
- close  `gh pr close`

用法（常驻，建议交给 launchd / systemd 守护）：
    python3 scripts/feishu_card_worker.py --repo . --operators ou_xxx

依赖：本机已登录的 `gh` 与 `lark-cli`；Feishu 开发者后台需开启
「事件与回调 → 回调配置」，否则 `card.action.trigger` 收不到事件。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feishu_cards  # noqa: E402


def gh_exe() -> str:
    return os.environ.get("COLLAB_GH") or shutil.which("gh") or "gh"


def _run(cmd: list[str], cwd: Path, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, timeout=timeout)


def _pr_url(cwd: Path, pr: int) -> str:
    proc = _run([gh_exe(), "pr", "view", str(pr), "--json", "url"], cwd, timeout=60)
    if proc.returncode != 0:
        return ""
    try:
        return json.loads(proc.stdout).get("url", "")
    except (json.JSONDecodeError, AttributeError):
        return ""


def try_accept(cwd: Path, pr: int) -> tuple[bool, str]:
    """尽力而为地记录人类终审（collab accept）。已通过/无该阶段时不算失败。"""
    cmd = [sys.executable, str(cwd / "scripts" / "collab.py"), "accept", str(pr), "--member", "human"]
    proc = _run(cmd, cwd, timeout=180)
    if proc.returncode == 0:
        return True, (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else "已终审通过"
    detail = (proc.stderr or proc.stdout or "").strip()
    return False, detail


def run_merge(cwd: Path, pr: int, sha: str) -> tuple[bool, str]:
    cmd = [gh_exe(), "pr", "merge", str(pr), "--merge"]
    if sha:
        cmd += ["--match-head-commit", sha]
    proc = _run(cmd, cwd, timeout=300)
    if proc.returncode == 0:
        return True, "已合并"
    return False, (proc.stderr or proc.stdout or "").strip()


def run_close(cwd: Path, pr: int) -> tuple[bool, str]:
    proc = _run([gh_exe(), "pr", "close", str(pr)], cwd, timeout=120)
    if proc.returncode == 0:
        return True, "已关闭"
    return False, (proc.stderr or proc.stdout or "").strip()


def perform(cwd: Path, action: str, pr: int, sha: str) -> tuple[bool, str, str]:
    """执行动作，返回 (ok, detail, url)。"""
    url = _pr_url(cwd, pr)
    if action == "merge":
        accept_ok, accept_detail = try_accept(cwd, pr)
        merge_ok, merge_detail = run_merge(cwd, pr, sha)
        if merge_ok:
            return True, "已通过终审并合并到主分支", url
        detail = merge_detail
        if not accept_ok:
            detail = f"合并失败：{merge_detail}\n\n（终审记录也未写入：{accept_detail[:200]}）"
        return False, detail, url
    if action == "accept":
        ok, detail = try_accept(cwd, pr)
        return ok, detail, url
    if action == "close":
        ok, detail = run_close(cwd, pr)
        return ok, detail, url
    return False, f"未知动作 {action}", url


def _emit(log: dict) -> None:
    print(json.dumps(log, ensure_ascii=False), flush=True)


def handle_event(cwd: Path, event: dict, operators: set[str], dry_run: bool, seen: set[str]) -> None:
    if event.get("type") != "card.action.trigger":
        return
    event_id = str(event.get("event_id", "") or "")
    if event_id:
        if event_id in seen:
            return
        seen.add(event_id)

    operator = str(event.get("operator_id", "") or "")
    action_value = str(event.get("action_value", "") or "")
    token = str(event.get("token", "") or "")
    parsed = feishu_cards.parse_action_value(action_value)
    if parsed is None:
        _emit({"event_id": event_id, "ignored": "unrecognized_action", "operator_id": operator})
        return
    action, pr, sha = parsed

    if operator not in operators:
        _emit({"event_id": event_id, "ignored": "unauthorized", "operator_id": operator, "pr": pr})
        if token and not dry_run:
            try:
                feishu_cards.update_card(token, feishu_cards.build_result_card(pr, action, False, "无权限执行该操作"))
            except Exception as exc:  # noqa: BLE001
                _emit({"event_id": event_id, "warn": f"更新无权限卡片失败：{exc}"})
        return

    if dry_run:
        _emit({"event_id": event_id, "dry_run": True, "operator_id": operator, "action": action, "pr": pr, "sha": sha})
        return

    ok, detail, url = perform(cwd, action, pr, sha)
    _emit({"event_id": event_id, "operator_id": operator, "action": action, "pr": pr, "ok": ok, "detail": detail[:500]})

    if token:
        result = feishu_cards.build_result_card(pr, action, ok, detail[:500], url)
        try:
            proc = feishu_cards.update_card(token, result)
            if proc.returncode != 0:
                _emit({"event_id": event_id, "warn": f"更新结果卡失败：{(proc.stderr or proc.stdout or '').strip()[:300]}"})
        except Exception as exc:  # noqa: BLE001
            _emit({"event_id": event_id, "warn": f"更新结果卡失败：{exc}"})


def parse_operators(raw: str) -> set[str]:
    return {x.strip() for x in (raw or "").split(",") if x.strip()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="feishu_card_worker.py", description="消费飞书卡片回调并执行 GitHub 动作")
    parser.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    parser.add_argument("--operators", default=os.environ.get("FEISHU_OPERATORS", ""),
                        help="允许点按钮的 open_id，逗号分隔（如 ou_xxx,ou_yyy）")
    parser.add_argument("--max-events", type=int, default=0, help="处理 N 个事件后退出（0=不限，用于测试）")
    parser.add_argument("--timeout", default="", help="整体超时（如 30s / 2m；空=不限）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的动作，不真正执行")
    args = parser.parse_args(argv)

    cwd = Path(args.repo).resolve()
    if not cwd.is_dir():
        print(f"仓库路径不存在：{cwd}", file=sys.stderr)
        return 2
    operators = parse_operators(args.operators)
    if not operators and not args.dry_run:
        print("✖ 必须用 --operators / FEISHU_OPERATORS 配置至少一个授权操作者 open_id（dry-run 可省略）。", file=sys.stderr)
        return 2

    cmd = [feishu_cards.lark_cli_exe(), "event", "consume", "card.action.trigger", "--as", "bot"]
    if args.max_events:
        cmd += ["--max-events", str(args.max_events)]
    if args.timeout:
        cmd += ["--timeout", args.timeout]

    if args.dry_run:
        print("（dry-run）将监听：", " ".join(cmd), file=sys.stderr)

    seen: set[str] = set()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=None, text=True)
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                handle_event(cwd, event, operators, args.dry_run, seen)
    except KeyboardInterrupt:
        proc.terminate()
        return 130
    finally:
        proc.wait()
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())

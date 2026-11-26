"""飞书交互卡片：构造、发送与更新（Card 2.0）。

把 collab 工作流里「等人终审 / 等人合并」这一步从「跳转 GitHub」换成
「在飞书卡片上点一下」。本模块只依赖标准库，真正发消息/更新卡片时才
按需调用系统里的 `lark-cli`；构造卡片是纯函数，便于单测。

卡片三个动作（按钮回调 payload 里的 `action`）：
- merge  通过并合并：先 collab accept 记录人类终审，再 `gh pr merge`
- accept 仅通过：只做 collab accept，标记 ready-to-merge，暂不合并
- close  关闭：`gh pr close`，不合并

动作值回传形态：Feishu 把按钮 `behaviors[].value` 序列化成 JSON 字符串，
在 `card.action.trigger` 事件的 `action_value` 字段回传。worker 侧
`json.loads(action_value)` 还原成 `{"action": "...", "pr": N, "sha": "<headSHA>"}`；
`sha` 是发送卡片时的 head，合并前用它做 `--match-head-commit` 兜底，防止
点了「合并」后 PR 又更新而误合并未审代码。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

__all__ = [
    "ACTIONS",
    "build_review_card",
    "build_result_card",
    "parse_action_value",
    "send_card",
    "update_card",
    "lark_cli_exe",
]

# 按钮回调支持的三个动作
ACTIONS = ("merge", "accept", "close")

# 结果卡元信息：动作 -> (标题, header 主题色, 一句话结果)
_RESULT_META = {
    "merge": ("已合并", "green", "已合并到主分支"),
    "accept": ("已通过", "blue", "已终审通过，标记待合并"),
    "close": ("已关闭", "grey", "已关闭，未合并任何改动"),
}
_ERROR_META = ("操作失败", "red", "操作未能完成，请看下方原因")


def lark_cli_exe() -> str:
    """返回可用的 lark-cli 路径；找不到返回 'lark-cli'（调用时再报错）。"""
    return os.environ.get("FEISHU_LARK_CLI") or shutil.which("lark-cli") or "lark-cli"


def build_review_card(
    pr_number: int,
    title: str,
    author: str,
    base_branch: str,
    head_sha: str,
    url: str,
    summary: str = "",
    head_sha_len: int = 7,
    stage: str = "review",
) -> dict[str, Any]:
    """构造评审卡（Card 2.0）。

    `stage` 决定按钮组合：
    - "review"：Issue 已 `review:agent-passed`，等人终审 → 通过并合并 / 仅通过 / 关闭
    - "merge"：Issue 已 `status:ready-to-merge`，等人合并 → 合并 / 关闭

    参数里的 PR 元信息只用于展示；回调 payload 只带 `action` / `pr` / `sha`，
    避免把长文本塞进按钮 value。
    """
    short = (head_sha or "")[:head_sha_len]
    lines = [
        f"**#{pr_number} · {title}**",
        "",
        f"作者 `{author}` · 目标分支 `{base_branch}` · 基线 `{short}`",
    ]
    if summary:
        lines += ["", summary]
    body_text = "\n".join(lines)

    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": body_text},
        {"tag": "hr"},
        {
            "tag": "markdown",
            "content": f"[在 GitHub 查看详情]({url})",
            "text_size": "notation",
        },
    ]
    elements.extend(_review_buttons(stage, pr_number, head_sha))

    header_title = "代码待你合并" if stage == "merge" else "代码待你终审"
    return {
        "schema": "2.0",
        "config": {"width_mode": "default", "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "orange",
            "text_tag_list": [
                {
                    "tag": "text_tag",
                    "text": {"tag": "plain_text", "content": f"PR #{pr_number}"},
                    "color": "orange",
                }
            ],
        },
        "body": {"direction": "vertical", "padding": "12px 12px 20px 12px", "elements": elements},
    }


def _review_buttons(stage: str, pr_number: int, head_sha: str) -> list[dict[str, Any]]:
    """按 stage 生成动作按钮；第一个是主操作，danger 的是危险操作。"""
    buttons: list[dict[str, Any]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "通过并合并" if stage == "review" else "合并"},
            "type": "primary_filled",
            "width": "fill",
            "behaviors": [{"type": "callback", "value": {"action": "merge", "pr": pr_number, "sha": head_sha}}],
        },
    ]
    if stage == "review":
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "仅通过（暂不合并）"},
            "type": "default",
            "width": "fill",
            "behaviors": [{"type": "callback", "value": {"action": "accept", "pr": pr_number, "sha": head_sha}}],
        })
    buttons.append({
        "tag": "button",
        "text": {"tag": "plain_text", "content": "关闭 PR"},
        "type": "danger",
        "width": "fill",
        "confirm": {
            "title": {"tag": "plain_text", "content": "确认关闭这个 PR？"},
            "text": {"tag": "plain_text", "content": f"将关闭 PR #{pr_number}，改动不会被合并。"},
        },
        "behaviors": [{"type": "callback", "value": {"action": "close", "pr": pr_number, "sha": head_sha}}],
    })
    return buttons


def build_result_card(
    pr_number: int,
    action: str,
    ok: bool,
    detail: str = "",
    url: str = "",
) -> dict[str, Any]:
    """构造点击后的结果卡；`ok=False` 时统一渲染成「操作失败」。"""
    title, template, line = _RESULT_META.get(action) if ok and action in _RESULT_META else _ERROR_META
    lines = [f"**#{pr_number}** {line}"]
    if detail:
        lines += ["", detail]
    if url:
        lines += ["", f"[在 GitHub 查看]({url})"]
    return {
        "schema": "2.0",
        "config": {"width_mode": "default", "update_multi": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": template,
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [{"tag": "markdown", "content": "\n".join(lines)}],
        },
    }


def parse_action_value(raw: str) -> tuple[str, int, str] | None:
    """把回传的 `action_value`（JSON 字符串）解析成 `(action, pr, sha)`。

    容错：value 可能被序列化成对象或纯字符串；无法识别时返回 None。
    `sha` 可为空字符串（旧卡片或未带 sha 时）。
    """
    if not raw:
        return None
    data: Any = None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        action = str(data.get("action", "")).strip().lower()
        pr = data.get("pr")
        sha = str(data.get("sha", "") or "").strip()
    elif isinstance(data, str):
        action = data.strip().lower()
        pr = None
        sha = ""
    else:
        return None
    if action not in ACTIONS:
        return None
    try:
        pr_no = int(pr)
    except (TypeError, ValueError):
        return None
    if pr_no <= 0:
        return None
    return action, pr_no, sha


def _run(cmd: list[str], check: bool = False, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"{cmd[0]} 失败（exit {proc.returncode}）：{detail}")
    return proc


def send_card(
    card: dict[str, Any],
    chat_id: str | None = None,
    user_id: str | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    """通过 lark-cli 发送交互卡片到群聊或私聊。"""
    if not chat_id and not user_id:
        raise ValueError("send_card 需要 chat_id 或 user_id 之一")
    content = json.dumps(card, ensure_ascii=False)
    cmd = [lark_cli_exe(), "im", "+messages-send", "--msg-type", "interactive", "--content", content]
    if chat_id:
        cmd += ["--chat-id", chat_id]
    else:
        cmd += ["--user-id", user_id]  # type: ignore[list-item]
    if idempotency_key:
        cmd += ["--idempotency-key", idempotency_key]
    if dry_run:
        cmd += ["--dry-run"]
    return _run(cmd)


def update_card(
    token: str,
    card: dict[str, Any],
    dry_run: bool = False,
) -> subprocess.CompletedProcess[str]:
    """用卡片回调携带的 token 更新整卡（延迟更新，30 分钟内最多 2 次）。"""
    data = json.dumps({"token": token, "card": card}, ensure_ascii=False)
    cmd = [lark_cli_exe(), "api", "POST", "/open-apis/interactive/v1/card/update", "--as", "bot", "--data", data]
    if dry_run:
        cmd += ["--dry-run"]
    return _run(cmd)

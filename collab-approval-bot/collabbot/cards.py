"""飞书交互卡片（Card 1.0，兼容面最广）。"""
from __future__ import annotations

import hashlib
import json

# 飞书卡片序列化上限：28672 字节（28 KB），不是 28000。
MAX_CARD_BYTES = 28672

# C0 总览卡对账摘要只算业务状态载荷，严禁混入 updated_at（否则每轮必变、防抖失效）。
_OVERVIEW_COUNT_KEYS = (
    "ready", "in-progress", "review", "ready-to-merge", "rework", "draft", "blocked",
)


def overview_digest(counts: dict, pending: list) -> str:
    """C0 卡片稳定摘要：仅对 counts 与 pending 的 (number, title, headRefOid) 计算。"""
    payload = {
        "counts": {k: int(counts.get(k, 0)) for k in _OVERVIEW_COUNT_KEYS},
        "pending": [
            {
                "number": p.get("number"),
                "title": p.get("title", ""),
                "headRefOid": p.get("headRefOid") or "",
            }
            for p in (pending or [])[:10]
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _md(content: str) -> dict:
    return {"tag": "div", "text": {"tag": "lark_md", "content": content}}


def _button(text, value=None, kind="default", url=None, action_type=None, name=None, confirm=None):
    item = {
        "tag": "button",
        "text": {"tag": "plain_text", "content": text},
        "type": kind,
        "value": value,
    }
    if url:
        item["url"] = url
        item.pop("value", None)
    if action_type:
        item["action_type"] = action_type
    if name:
        item["name"] = name
    if confirm:
        item["confirm"] = confirm
    return item


def _card(title, template, elements):
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {
            "template": template,
            "title": {"tag": "plain_text", "content": title},
        },
        "elements": elements,
    }


def _card_bytes(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False).encode("utf-8"))


def _fit(card: dict) -> dict:
    """循环式收敛：整体序列化测字节，超限则逐轮截断最长 div 的 lark_md content。"""
    if _card_bytes(card) <= MAX_CARD_BYTES:
        return card
    for _ in range(20):
        if _card_bytes(card) <= MAX_CARD_BYTES:
            return card
        targets = [
            e
            for e in card.get("elements", [])
            if e.get("tag") == "div" and isinstance(e.get("text", {}).get("content"), str)
        ]
        if not targets:
            break
        longest = max(targets, key=lambda e: len(e["text"]["content"]))
        content = longest["text"]["content"]
        if len(content) <= 1:
            break
        new_len = max(1, int(len(content) * 0.8))
        longest["text"]["content"] = content[:new_len] + "\n…（内容过长已截断）"
    # 兜底：仍超限则把最后一个元素替换为提示，避免卡片无法发送。
    if _card_bytes(card) > MAX_CARD_BYTES and card.get("elements"):
        card["elements"] = card["elements"][:-1] + [
            _md("内容过长已截断，请到 GitHub 查看完整信息。")
        ]
    return card


def _review_detail_lines(review: dict) -> list:
    """把 collab:review 报告里的门禁/验收项/盲点转成卡片正文行。"""
    if not review:
        return []
    gate = review.get("gate") or ""
    acceptance = review.get("acceptance") or []
    blindspots = review.get("blindspots") or {}
    if not gate and not acceptance and not blindspots:
        return ["报告未提供门禁/盲点信息"]
    lines = []
    if gate:
        lines.append("**门禁** %s" % gate)
    if acceptance:
        lines.append("**验收项**")
        lines.extend("- %s" % item for item in acceptance)
    if blindspots:
        lines.append("**视角补充 / 需求盲点**")
        for key in ("隐含假设", "未覆盖边界", "关联影响"):
            if blindspots.get(key):
                lines.append("- %s：%s" % (key, blindspots[key]))
    return lines


def approval_card(pr: dict, issue: dict, review: dict, warning: str = "", epoch: str = "") -> dict:
    number = pr.get("number")
    head = pr.get("headRefOid") or ""
    labels = [item.get("name", "") for item in (issue.get("labels") or [])]
    high_risk = "risk:high" in labels
    hard = "tier:hard" in labels
    template = "red" if high_risk else ("orange" if hard else "blue")
    suffix = " · 高风险" if high_risk else (" · 高难" if hard else "")
    title = "待你终审 · PR #%s%s" % (number, suffix)

    lines = []
    if warning:
        lines.append("**%s**" % warning)
        lines.append("")
    lines.append(
        "**工单** #%s %s"
        % (issue.get("number", "?"), issue.get("title", ""))
    )
    author = (pr.get("author") or {}).get("login", "?")
    lines.append("**作者** %s" % author)
    if review:
        lines.append(
            "**审查** %s · %s · family=%s · `%s`"
            % (
                review.get("member", "?"),
                review.get("verdict", "?"),
                review.get("family", "?"),
                (review.get("sha", "") or "")[:7],
            )
        )
    else:
        lines.append("**审查** 未找到 collab:review 报告")
    detail_lines = _review_detail_lines(review)
    if detail_lines:
        lines.append("")
        lines.extend(detail_lines)
    lines.append(
        "**代码** %s 文件 · +%s / -%s"
        % (
            pr.get("changedFiles", "?"),
            pr.get("additions", "?"),
            pr.get("deletions", "?"),
        )
    )
    lines.append("**标签** %s" % (", ".join(labels) or "无"))
    lines.append("**SHA** `%s`" % head)
    if pr.get("title"):
        lines.append("")
        lines.append("**%s**" % pr.get("title"))
    lines.append("")
    lines.append("卡片绑定当前 SHA；若 PR 有新提交，操作会被拒绝并要求刷新。")

    elements = [_md("\n".join(lines)), {"tag": "hr"}]
    merge_value = {"a": "accept_merge", "pr": number, "sha": head, "epoch": epoch}
    merge_button = _button("通过并合并", merge_value, "primary")
    if high_risk or hard:
        merge_button = _button(
            "通过并合并",
            merge_value,
            "primary",
            confirm={
                "title": {"tag": "plain_text", "content": "确认通过并合并？"},
                "text": {
                    "tag": "plain_text",
                    "content": "该 PR 为高风险/高难变更，合并前请再次确认。",
                },
            },
        )
    actions = [
        merge_button,
        _button(
            "仅验收（暂不合并）",
            {"a": "accept_only", "pr": number, "sha": head, "epoch": epoch},
        ),
        _button("刷新", {"a": "refresh", "pr": number, "epoch": epoch}),
    ]
    elements.append({"tag": "action", "actions": actions})
    elements.append(
        {
            "tag": "form",
            "name": "rework_form",
            "elements": [
                {
                    "tag": "input",
                    "name": "note",
                    "max_length": 500,
                    "placeholder": {
                        "tag": "plain_text",
                        "content": "打回返工必须填写意见…",
                    },
                },
                _button(
                    "打回返工",
                    {"a": "rework", "pr": number, "sha": head, "epoch": epoch},
                    "danger",
                    action_type="form_submit",
                    name="rework:%s:%s:%s" % (number, head, epoch),
                ),
            ],
        }
    )
    return _fit(_card(title, template, elements))


def confirm_card(pr: dict, epoch: str = "") -> dict:
    number = pr.get("number")
    head = pr.get("headRefOid") or ""
    content = (
        "确认对 **PR #%s** 执行终审并合并？\n\n"
        "- 标题：%s\n"
        "- SHA：`%s`\n\n"
        "将依次执行 `collab.py accept` 与 `gh pr merge --squash "
        "--match-head-commit`。"
    ) % (number, pr.get("title", ""), head)
    actions = [
        _button(
            "确认通过并合并",
            {"a": "accept_merge", "pr": number, "sha": head, "epoch": epoch},
            "primary",
        ),
        _button("取消", {"a": "dismiss", "pr": number, "epoch": epoch}),
    ]
    return _fit(
        _card(
            "确认终审 · PR #%s" % number,
            "orange",
            [_md(content), {"tag": "action", "actions": actions}],
        )
    )


def result_card(
    title: str,
    detail: str,
    ok: bool,
    pr=None,
    retry_sha=None,
    warning: bool = False,
    epoch: str = "",
    retry_labels_issue=None,
) -> dict:
    template = "green" if ok else ("red" if not warning else "orange")
    body = (detail or "（无输出）").strip()
    if len(body) > 3000:
        body = body[:3000] + "\n…（已截断）"
    elements = [_md(body)]
    actions = []
    if retry_sha and pr is not None:
        actions.append(
            _button(
                "重试合并",
                {"a": "retry_merge", "pr": pr, "sha": retry_sha, "epoch": epoch},
                "primary",
            )
        )
    if retry_labels_issue is not None and pr is not None:
        actions.append(
            _button(
                "重试同步标签",
                {"a": "retry_labels", "pr": pr, "issue": retry_labels_issue, "epoch": epoch},
                "primary",
            )
        )
    if pr is not None:
        actions.append(_button("刷新卡片", {"a": "refresh", "pr": pr, "epoch": epoch}))
    if actions:
        elements += [{"tag": "hr"}, {"tag": "action", "actions": actions}]
    return _fit(_card(title, template, elements))


def blocked_card(issue: dict, kind: str) -> dict:
    title = "需要你裁决 · Issue #%s" % issue.get("number")
    reason = (
        "熔断，需要人工裁决"
        if kind == "blocked:needs-human"
        else "需求/架构存在歧义，需要拍板"
    )
    content = "**原因** %s\n\n**%s**" % (
        reason,
        issue.get("title", ""),
    )
    elements = [_md(content)]
    return _fit(_card(title, "orange", elements))


def overview_card(counts: dict, pending: list, updated_at: str = "", archived: bool = False, epoch: str = "") -> dict:
    """C0 置顶总览卡（只读）；archived=True 时首行标「已归档」且不再给任何按钮。"""
    lines = []
    if archived:
        lines.append("**已归档**（旧卡，请以最新卡为准）")
        lines.append("")
    lines.append("**协作总览**")
    if updated_at:
        lines.append("更新于 %s" % updated_at)
    lines.append("")
    lines.append(
        "待领取 %d · 开发中 %d · 待审 %d · 待合并 %d · 返工 %d · 草稿 %d · 阻塞 %d"
        % (
            counts.get("ready", 0),
            counts.get("in-progress", 0),
            counts.get("review", 0),
            counts.get("ready-to-merge", 0),
            counts.get("rework", 0),
            counts.get("draft", 0),
            counts.get("blocked", 0),
        )
    )
    if pending:
        lines.append("")
        lines.append("**待你终审（%d）**" % len(pending))
        for pr in pending[:10]:
            lines.append(
                "- PR #%s %s · `%s`"
                % (
                    pr.get("number"),
                    pr.get("title", ""),
                    (pr.get("headRefOid") or "")[:7],
                )
            )
    elements = [_md("\n".join(lines))]
    if not archived:
        elements += [
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [_button("↻ 立即刷新", {"a": "refresh_overview", "epoch": epoch})],
            },
        ]
    template = "blue" if not archived else "grey"
    return _fit(_card("协作总览", template, elements))

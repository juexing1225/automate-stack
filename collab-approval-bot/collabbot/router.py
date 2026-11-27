"""指令与卡片回调分发。人类是唯一决策者，机器人只代办已授权的协作动作。"""
from __future__ import annotations

import json
import logging
import threading
import time

from . import cards
from .executor import redact

HELP = """**Collab 审批官**

我在你的 Mac 上代为执行协作仓库的白名单动作，GitHub 仍是唯一真源。

**看状态**
`/status` 协作看板
`/prs` 打开的 PR
`/show 2` 单个 PR 详情
`/card 2` 生成审批卡
`/repo` 本地仓库状态

**做决策**
`/approve 2` 通过并合并（先出确认卡）
`/rework 2 意见` 打回返工
`/pack issue 1` 导出任务包

**其它**
`/log` 最近审计记录
`/whoami` 我的 open_id
"""


def parse_command(text: str):
    raw = (text or "").strip()
    if not raw.startswith("/"):
        return None, raw
    head, _, rest = raw[1:].partition(" ")
    return head.lower(), rest.strip()


class Router:
    def __init__(self, config, store, audit, lark, collab, logger) -> None:
        self.config = config
        self.store = store
        self.audit = audit
        self.lark = lark
        self.collab = collab
        self.logger = logger or logging.getLogger("collabbot")

    # ---------- 被动接收 ----------

    def handle_message(self, event: dict) -> None:
        try:
            self._handle_message(event)
        except Exception:  # 单条消息失败不能打断消费循环
            self.logger.exception("处理消息失败")

    def _handle_message(self, event: dict) -> None:
        if event.get("sender_type") != "user":
            return
        chat_type = event.get("chat_type")
        if chat_type != "p2p" and not self.config.allow_group:
            return

        open_id = str(event.get("sender_id") or "").strip()
        message_id = str(event.get("message_id") or "")
        if not open_id:
            return
        if message_id and self.store.seen("msg:" + message_id):
            return

        cmd, rest = parse_command(event.get("content") or "")
        if cmd is None:
            if self.store.is_owner(open_id):
                self._reply(open_id, "我只认斜杠指令。发送 `/help` 查看可用指令。")
            return

        if cmd in ("start", "help"):
            self._reply(open_id, HELP)
            return
        if cmd in ("whoami", "id"):
            self._reply(
                open_id,
                "你的 open_id：`%s`\n已绑定：%s"
                % (open_id, "是" if self.store.is_owner(open_id) else "否"),
            )
            return
        if cmd == "bind":
            ok, message = self.store.bind(open_id, rest)
            self.audit.write(open_id, "/bind", "success=%s" % ok, "ok" if ok else "deny")
            if ok:
                self._reply(
                    open_id,
                    "绑定成功。你已成为 Collab 审批官的唯一主人。\n\n" + HELP,
                )
            else:
                self._reply(open_id, message)
            return
        if cmd in ("ping", "health"):
            self._reply(open_id, "pong · %s" % time.strftime("%Y-%m-%d %H:%M:%S"))
            return

        if not self.store.has_owner():
            self._reply(
                open_id,
                "尚未绑定主人。请在 Mac 上查看 Collab 审批官启动日志里的 BIND_CODE，"
                "然后发送 `/bind 绑定码`。",
            )
            return
        if not self.store.is_owner(open_id):
            self._reply(open_id, "你不在审批官白名单里，无法操作这台电脑。")
            self.audit.write(open_id, cmd, rest[:200], "deny")
            return

        self._dispatch(open_id, cmd, rest)

    def _dispatch(self, open_id: str, cmd: str, rest: str) -> None:
        if cmd == "status":
            self.audit.write(open_id, "/status")
            try:
                markdown = self.collab.status_markdown()
            except Exception as exc:
                self._reply(open_id, "读取看板失败：%s" % exc)
                return
            self._reply(open_id, markdown)
            return

        if cmd == "prs":
            self.audit.write(open_id, "/prs")
            self._reply(open_id, self._prs_markdown())
            return

        if cmd == "repo":
            self.audit.write(open_id, "/repo")
            self._reply(open_id, self._repo_markdown())
            return

        if cmd == "log":
            lines = self.audit.tail(12)
            if not lines:
                self._reply(open_id, "暂无审计记录。")
                return
            body = "\n".join("-`%s`" % line[:300] for line in lines)
            self._reply(open_id, "**最近审计**\n\n" + body)
            return

        if cmd in ("show", "card", "approve", "rework", "pack"):
            self._handle_pr_command(open_id, cmd, rest)
            return

        self._reply(open_id, "未知指令 `/%s`。发送 `/help` 查看。" % cmd)

    # ---------- PR 指令 ----------

    def _handle_pr_command(self, open_id: str, cmd: str, rest: str) -> None:
        if cmd == "pack":
            parts = rest.split()
            if len(parts) != 2 or parts[0] not in ("issue", "pr") or not parts[1].isdigit():
                self._reply(open_id, "用法：`/pack issue 1` 或 `/pack pr 2`")
                return
            kind, number = parts[0], int(parts[1])
            self._reply(open_id, "📦 正在导出 %s #%s 的任务包…" % (kind, number))
            result = self.collab.pack(kind, number)
            self.audit.write(
                open_id, "/pack", "%s %s" % (kind, number), "ok" if result.ok else "fail"
            )
            self._reply(
                open_id,
                "%s\n\n```\n%s\n```" % (result.title, result.detail[:2500]),
            )
            return

        parts = rest.split(None, 1)
        if not parts or not parts[0].isdigit():
            self._reply(open_id, "用法：`/%s <PR号>`" % cmd)
            return
        number = int(parts[0])
        argument = parts[1].strip() if len(parts) > 1 else ""

        try:
            pr = self.collab.pr_view(number)
        except Exception as exc:
            self._reply(open_id, "读取 PR #%s 失败：%s" % (number, exc))
            return

        issue_no = self.collab.issue_number(pr)
        issue = {}
        if issue_no:
            try:
                issue = self.collab.issue_view(issue_no)
            except Exception:
                issue = {}
        review = self.collab.latest_review(pr)

        if cmd == "show":
            self.audit.write(open_id, "/show", str(number))
            labels = ", ".join(self.collab.label_names(issue)) if issue else "未知"
            text = (
                "**PR #%s %s**\n\n"
                "- 状态：%s\n- SHA：`%s`\n- 作者：%s\n"
                "- 工单：#%s\n- 工单标签：%s\n"
                "- 审查：%s %s\n\n%s"
            ) % (
                number,
                pr.get("title", ""),
                pr.get("state", "?"),
                pr.get("headRefOid", ""),
                (pr.get("author") or {}).get("login", "?"),
                issue_no or "未标记",
                labels,
                review.get("member", "?"),
                review.get("verdict", "无报告"),
                pr.get("url", ""),
            )
            self._reply(open_id, text)
            if "review:agent-passed" in self.collab.label_names(issue):
                self.lark.send_card(
                    open_id, cards.approval_card(pr, issue, review, epoch=self.store.epoch)
                )
            return

        if cmd == "card":
            self.audit.write(open_id, "/card", str(number))
            self.lark.send_card(
                open_id, cards.approval_card(pr, issue, review, epoch=self.store.epoch)
            )
            return

        if cmd == "approve":
            self.audit.write(open_id, "/approve", str(number))
            self.lark.send_card(open_id, cards.confirm_card(pr, epoch=self.store.epoch))
            return

        if cmd == "rework":
            if not argument:
                self._reply(open_id, "用法：`/rework 2 具体返工意见`")
                return
            self.audit.write(open_id, "/rework", "%s %s" % (number, redact(argument)[:200]))
            self._reply(open_id, "🔁 正在打回 PR #%s…" % number)
            result = self.collab.rework(number, argument)
            self.audit.write(
                open_id, "/rework", str(number), "ok" if result.ok else "fail"
            )
            self.lark.send_card(
                open_id,
                cards.result_card(
                    result.title,
                    result.detail,
                    result.ok,
                    pr=number,
                    warning=result.warning,
                    epoch=self.store.epoch,
                    retry_labels_issue=result.retry_labels_issue,
                ),
            )

    # ---------- 卡片回调 ----------

    def handle_card(self, event: dict) -> None:
        try:
            self._handle_card(event)
        except Exception:
            self.logger.exception("处理卡片回调失败")

    def _handle_card(self, event: dict) -> None:
        event_id = str(event.get("event_id") or "")
        if event_id and self.store.seen("card:" + event_id):
            return

        operator = str(event.get("operator_id") or "").strip()
        if not operator or not self.store.is_owner(operator):
            self.logger.warning("拒绝非主人卡片操作：%s", operator or "(空)")
            self.audit.write(operator or "(空)", "card:deny", "非白名单操作者", "deny")
            self._update(
                event,
                cards.result_card("无权操作", "你不在此审批官的白名单里。", False),
                "无权操作：你不在此审批官的白名单里。",
                operator or "",
            )
            return

        action = event.get("action")
        if not isinstance(action, dict):
            # lark-cli 的 card.action.trigger 是扁平结构；兼容原始嵌套结构。
            action = {
                "tag": event.get("action_tag"),
                "name": event.get("action_name"),
                "value": event.get("action_value"),
                "form_value": event.get("form_value"),
                "input_value": event.get("input_value"),
            }
        value = action.get("value")
        if isinstance(value, str):
            raw = value.strip()
            try:
                value = json.loads(raw) if raw.startswith("{") else {}
            except ValueError:
                value = {}
        if not isinstance(value, dict):
            value = {}

        raw_name = str(action.get("name") or "")
        encoded = raw_name.split(":") if raw_name.startswith("rework:") else []
        name = str(value.get("a") or "")
        if not name and encoded:
            # 表单提交不回传按钮 value，把 pr/sha 编码进按钮 name 兜底。
            name = "rework"
        if not name:
            name = str(action.get("tag") or "")
        try:
            number = int(value.get("pr"))
        except (TypeError, ValueError):
            number = 0
        sha = str(value.get("sha") or "")
        if number <= 0 and len(encoded) >= 3:
            try:
                number = int(encoded[1])
            except (TypeError, ValueError):
                number = 0
            sha = sha or encoded[2]

        if name == "dismiss":
            self.audit.write(operator, "card:dismiss", str(number))
            self._update(
                event,
                cards.result_card(
                    "已取消", "没有执行任何变更。", True, pr=number or None, epoch=self.store.epoch
                ),
                "已取消，没有执行任何变更。",
                operator,
            )
            return

        if name == "refresh_overview":
            # C0「↻ 立即刷新」：即时重算业务状态并原地回刷，不涉及任何 GitHub 写入。
            try:
                counts, pending = self.collab.overview_data()
            except Exception as exc:
                self.logger.warning("刷新总览失败：%s", exc)
                counts, pending = {}, []
            updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
            card = cards.overview_card(
                counts, pending, updated_at=updated_at, epoch=self.store.epoch
            )
            self.audit.write(operator, "card:refresh_overview", "", "ok")
            self._update(event, card, "已刷新总览。", operator)
            return

        if number <= 0:
            self._update(
                event,
                cards.result_card("操作无效", "卡片缺少 PR 编号，请重新生成。", False),
                "卡片缺少 PR 编号，请重新生成。",
                operator,
            )
            return

        # 实例纪元校验：缓存全丢重启后 boot_epoch 会换新，旧卡按钮必须安全拒绝（0 GitHub 写入）。
        if name in ("accept_merge", "accept_only", "rework", "retry_merge", "retry_labels"):
            card_epoch = str(value.get("epoch") or "")
            if not card_epoch and len(encoded) >= 4:
                card_epoch = encoded[3]
            if self.store.epoch and card_epoch != self.store.epoch:
                self.audit.write(operator, "card:" + name, str(number), "stale-epoch")
                self._update(
                    event,
                    cards.result_card(
                        "卡片已过期",
                        "实例已重启，本卡片已失效。请获取最新卡片后重新操作（未做任何变更）。",
                        False,
                        pr=number,
                    ),
                    "实例已重启，卡片已过期，请获取最新卡片。",
                    operator,
                )
                return

        started = time.time()
        try:
            pr = self.collab.pr_view(number)
        except Exception as exc:
            self._update(
                event,
                cards.result_card("读取 PR 失败", str(exc), False, pr=number),
                "读取 PR 失败：%s" % exc,
                operator,
            )
            return

        if pr.get("state") != "OPEN":
            self.audit.write(operator, "card:" + name, str(number), "fail")
            self._update(
                event,
                cards.result_card(
                    "PR 不是打开状态",
                    "当前状态：%s" % pr.get("state"),
                    False,
                    pr=number,
                ),
                "PR #%s 当前状态 %s，无法操作。" % (number, pr.get("state")),
                operator,
            )
            return

        current_sha = pr.get("headRefOid") or ""
        if name in ("accept_merge", "accept_only", "rework", "retry_merge", "retry_labels"):
            if not sha:
                self._update(
                    event,
                    cards.result_card(
                        "卡片缺少 SHA",
                        "无法确认操作对象，请重新发送 /card %s 生成新卡片。" % number,
                        False,
                        pr=number,
                    ),
                    "卡片缺少 SHA，请重新生成。",
                    operator,
                )
                self.audit.write(operator, "card:" + name, str(number), "no-sha")
                return
            if sha and current_sha != sha:
                issue_no = self.collab.issue_number(pr)
                issue = {}
                if issue_no:
                    try:
                        issue = self.collab.issue_view(issue_no)
                    except Exception:
                        issue = {}
                review = self.collab.latest_review(pr)
                card = cards.approval_card(
                    pr,
                    issue,
                    review,
                    warning="PR 已有新提交（卡片 %s → 当前 %s），请重新确认。"
                    % (sha[:7], current_sha[:7]),
                    epoch=self.store.epoch,
                )
                self._update(
                    event,
                    card,
                    "PR #%s 已有新提交，卡片上的 SHA 已过期，请刷新后重新确认。"
                    % number,
                    operator,
                )
                self.audit.write(operator, "card:" + name, str(number), "stale")
                return

        if name == "refresh":
            issue_no = self.collab.issue_number(pr)
            issue = {}
            if issue_no:
                try:
                    issue = self.collab.issue_view(issue_no)
                except Exception:
                    issue = {}
            review = self.collab.latest_review(pr)
            card = cards.approval_card(
                pr, issue, review, warning="已刷新为当前最新 SHA。", epoch=self.store.epoch
            )
            self._update(event, card, "已刷新，请查看新卡片。", operator)
            return

        if name == "accept_merge":
            decision_key = self._decision_key(number, sha)
            if not self.store.decision_in_progress(decision_key):
                self._conflict_update(event, operator, number)
                return
            self._update(
                event,
                cards.result_card(
                    "正在执行终审…",
                    "先跑 `collab.py accept`，再按 SHA 合并。请稍候。",
                    True,
                    pr=number,
                ),
                "正在执行终审与合并，请稍候…",
                operator,
            )
            try:
                result = self.collab.accept_and_merge(number, sha)
            finally:
                self.store.finish_decision(decision_key)
            self.audit.write(
                operator,
                "card:accept_merge",
                "%s %.1fs" % (number, time.time() - started),
                "ok" if result.ok else "fail",
            )
            self._update(
                event,
                cards.result_card(
                    result.title,
                    result.detail,
                    result.ok,
                    pr=number,
                    retry_sha=result.retry_sha,
                    warning=not result.ok,
                    epoch=self.store.epoch,
                ),
                "%s\n\n%s" % (result.title, result.detail[:2500]),
                operator,
            )
            return

        if name == "accept_only":
            decision_key = self._decision_key(number, sha)
            if not self.store.decision_in_progress(decision_key):
                self._conflict_update(event, operator, number)
                return
            try:
                result = self.collab.accept_only(number, sha)
            finally:
                self.store.finish_decision(decision_key)
            self.audit.write(
                operator, "card:accept_only", str(number), "ok" if result.ok else "fail"
            )
            self._update(
                event,
                cards.result_card(
                    result.title, result.detail, result.ok, pr=number, warning=not result.ok,
                    epoch=self.store.epoch,
                ),
                "%s\n\n%s" % (result.title, result.detail[:2500]),
                operator,
            )
            return

        if name == "retry_merge":
            decision_key = self._decision_key(number, sha)
            if not self.store.decision_in_progress(decision_key):
                self._conflict_update(event, operator, number)
                return
            try:
                result = self.collab.retry_merge(number, sha)
            finally:
                self.store.finish_decision(decision_key)
            self.audit.write(
                operator, "card:retry_merge", str(number), "ok" if result.ok else "fail"
            )
            self._update(
                event,
                cards.result_card(
                    result.title,
                    result.detail,
                    result.ok,
                    pr=number,
                    retry_sha=result.retry_sha,
                    warning=not result.ok,
                    epoch=self.store.epoch,
                ),
                "%s\n\n%s" % (result.title, result.detail[:2500]),
                operator,
            )
            return

        if name == "retry_labels":
            # 幂等补切标签：复用原返工决定，只补标签，绝不重发 REWORK 评论。
            issue_no = value.get("issue")
            try:
                issue_no = int(issue_no)
            except (TypeError, ValueError):
                issue_no = 0
            if issue_no <= 0:
                self._update(
                    event,
                    cards.result_card("操作无效", "卡片缺少工单编号，请重新生成。", False, pr=number),
                    "卡片缺少工单编号，请重新生成。",
                    operator,
                )
                return
            # 关联工单绑定：PR 的 collab:issue 若已变化，则旧卡零写入并提示刷新。
            current_issue = self.collab.issue_number(pr)
            if current_issue != issue_no:
                self._update(
                    event,
                    cards.result_card(
                        "工单关联已变化",
                        "PR #%s 的关联工单已变更（卡片 #%s → 当前 #%s），请刷新卡片后重新操作（未做任何变更）。"
                        % (number, issue_no, current_issue or "无"),
                        False,
                        pr=number,
                    ),
                    "工单关联已变化，请刷新卡片。",
                    operator,
                )
                self.audit.write(operator, "card:retry_labels", str(number), "issue-changed")
                return
            decision_key = self._decision_key(number, sha)
            if not self.store.decision_in_progress(decision_key):
                self._conflict_update(event, operator, number)
                return
            try:
                result = self.collab.sync_rework_labels(number, issue_no, sha)
            finally:
                self.store.finish_decision(decision_key)
            self.audit.write(
                operator, "card:retry_labels", "%s #%s" % (number, issue_no),
                "ok" if result.ok else "fail",
            )
            self._update(
                event,
                cards.result_card(
                    result.title,
                    result.detail,
                    result.ok,
                    pr=number,
                    warning=not result.ok,
                    epoch=self.store.epoch,
                    retry_labels_issue=issue_no if result.retry_labels_issue else None,
                    retry_labels_sha=result.retry_labels_sha,
                ),
                "%s\n\n%s" % (result.title, result.detail[:2500]),
                operator,
            )
            return

        if name == "rework":
            note = ""
            form_value = action.get("form_value")
            if isinstance(form_value, dict):
                note = str(form_value.get("note") or "")
            elif isinstance(form_value, str) and form_value.strip():
                try:
                    note = str(json.loads(form_value).get("note") or "")
                except ValueError:
                    note = ""
            if not note:
                note = str(action.get("input_value") or "")
            note = note.strip()
            if not note:
                issue_no = self.collab.issue_number(pr)
                issue = {}
                if issue_no:
                    try:
                        issue = self.collab.issue_view(issue_no)
                    except Exception:
                        issue = {}
                self._update(
                    event,
                    cards.approval_card(
                        pr,
                        issue,
                        self.collab.latest_review(pr),
                        warning="打回返工必须填写意见。也可以在聊天里发 /rework %s 意见"
                        % number,
                        epoch=self.store.epoch,
                    ),
                    "打回返工必须填写意见。",
                    operator,
                )
                return
            decision_key = self._decision_key(number, sha)
            if not self.store.decision_in_progress(decision_key):
                self._conflict_update(event, operator, number)
                return
            try:
                result = self.collab.rework(number, note, sha)
            finally:
                self.store.finish_decision(decision_key)
            self.audit.write(
                operator, "card:rework", "%s %s" % (number, redact(note)[:200]),
                "ok" if result.ok else "fail",
            )
            self._update(
                event,
                cards.result_card(
                    result.title,
                    result.detail,
                    result.ok,
                    pr=number,
                    warning=result.warning,
                    epoch=self.store.epoch,
                    retry_labels_issue=result.retry_labels_issue,
                    retry_labels_sha=result.retry_labels_sha,
                ),
                "%s\n\n%s" % (result.title, result.detail[:2500]),
                operator,
            )
            return

        self._update(
            event,
            cards.result_card("未知操作", "卡片动作 `%s` 未实现。" % name, False, pr=number),
            "未知操作：%s" % name,
            operator,
        )

    def _decision_key(self, number: int, sha: str) -> str:
        repo = ""
        try:
            repo = self.collab.repo_slug() or ""
        except Exception:
            repo = ""
        return "%s:%s:%s" % (repo, number, sha)

    def _conflict_update(self, event: dict, operator: str, number: int) -> None:
        self._update(
            event,
            cards.result_card(
                "操作已在处理中",
                "同一 PR/SHA 的操作正在处理中，请稍后刷新卡片再试。",
                False,
                pr=number,
            ),
            "操作已在处理中，请稍后刷新卡片再试。",
            operator,
        )

    def _update(self, event: dict, card: dict, fallback: str, operator: str) -> None:
        token = event.get("token")
        if token:
            try:
                self.lark.update_card(str(token), card)
                return
            except Exception as exc:
                self.logger.warning("更新卡片失败：%s", exc)
        try:
            self.lark.send_card(operator, card)
        except Exception:
            self._reply(operator, fallback)

    # ---------- 小工具 ----------

    def _reply(self, open_id: str, text: str) -> None:
        try:
            self.lark.send_markdown(open_id, text)
        except Exception as exc:
            self.logger.warning("发送消息失败：%s", exc)

    def _prs_markdown(self) -> str:
        prs = self.collab.open_prs()
        if not prs:
            return "当前没有打开的 PR。"
        lines = ["**打开的 PR（%d）**" % len(prs), ""]
        for pr in prs:
            lines.append(
                "- **#%s** %s\n  `%s` · %s · %s"
                % (
                    pr.get("number"),
                    pr.get("title", ""),
                    (pr.get("headRefOid") or "")[:7],
                    (pr.get("author") or {}).get("login", "?"),
                    pr.get("url", ""),
                )
            )
        lines += ["", "发送 `/card <PR号>` 生成审批卡。"]
        return "\n".join(lines)

    def _repo_markdown(self) -> str:
        info = self.collab.repo_info()
        rc, auth = self.collab.gh_auth_status()
        lines = [
            "**本地仓库**",
            "",
            "`%s`" % info["path"],
            "分支：`%s`" % (info["branch"] or "未知"),
            "工作区：%s"
            % ("干净" if not info["dirty"] else "%d 处改动" % len(info["dirty"])),
            "远端：%s" % (info["remote"] or "未配置"),
            "最近提交：`%s`" % (info["last_commit"] or "无"),
            "",
            "**GitHub CLI**",
            "",
            "状态：%s" % ("已登录" if rc == 0 else "未登录/异常"),
        ]
        if rc != 0:
            lines.append("```\n%s\n```" % auth[:800])
        return "\n".join(lines)

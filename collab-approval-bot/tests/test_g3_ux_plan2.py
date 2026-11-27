"""Gate 3 方案 2（卡片点击即时反馈、防误点与减半延迟）TDD 失败回归测试。"""
from __future__ import annotations

import logging
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_ROOT = os.path.dirname(_HERE)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from collabbot import cards
from collabbot.collab_actions import Collab, Result
from collabbot.router import Router
from collabbot.store import Store


def _buttons(card):
    out = []
    for element in card.get("elements", []):
        if element.get("tag") == "action":
            out.extend(element.get("actions", []))
    return out


class ImmediateProgressFeedbackTest(unittest.TestCase):
    """写操作必须在调用 gh pr view 之前就先回刷无按钮过渡态卡片。"""

    def test_write_action_sends_buttonless_progress_before_pr_view(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            call_order = []
            lark = Mock()

            def record_update(token, card):
                call_order.append(("update", card["header"]["title"]["content"], _buttons(card)))

            lark.update_card.side_effect = record_update

            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"

            def record_pr_view(num):
                call_order.append(("pr_view", num))
                return {"number": num, "state": "OPEN", "headRefOid": "sha12345", "title": "demo"}

            collab.pr_view.side_effect = record_pr_view
            collab.retry_merge.return_value = Result(True, "✅ 重试合并成功", "ok")

            router = Router(Mock(), store, Mock(), lark, collab, logging.getLogger("g3.ux"))
            router._handle_card({
                "event_id": "evt-p1",
                "token": "tok-1",
                "operator_id": "ou_owner",
                "action": {"value": {"a": "retry_merge", "pr": 14, "sha": "sha12345", "epoch": store.epoch}},
            })

            self.assertGreaterEqual(len(call_order), 2)
            self.assertEqual(
                call_order[0][0],
                "update",
                "应在调用 pr_view 之前先回刷过渡态卡片，实际顺序：%s" % (call_order,),
            )
            self.assertEqual(
                call_order[0][2],
                [],
                "过渡态卡片不应包含任何操作按钮（防连点），实际：%s" % (call_order[0][2],),
            )

    def test_rework_empty_note_does_not_flash_progress_card(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            lark = Mock()
            collab = Mock()
            collab.pr_view.return_value = {
                "number": 17, "state": "OPEN", "headRefOid": "sha12345", "title": "demo",
            }
            collab.issue_number.return_value = 16
            collab.issue_view.return_value = {"number": 16, "labels": []}
            collab.latest_review.return_value = {}

            router = Router(Mock(), store, Mock(), lark, collab, logging.getLogger("g3.ux"))
            router._handle_card({
                "event_id": "evt-empty",
                "token": "tok-2",
                "operator_id": "ou_owner",
                "action": {
                    "value": {"a": "rework", "pr": 17, "sha": "sha12345", "epoch": store.epoch},
                    "form_value": {"note": "   "},
                },
            })

            titles = [c.args[1]["header"]["title"]["content"] for c in lark.update_card.call_args_list]
            self.assertFalse(
                any("正在" in t for t in titles),
                "rework 空输入不应闪出「正在处理中」过渡态，实际：%s" % titles,
            )


class StaleShaInvalidationCardTest(unittest.TestCase):
    """SHA 漂移时应刷出醒目红色作废卡且移除「通过并合并」按钮，杜绝二次误点。"""

    def test_stale_sha_renders_invalidated_red_card_without_merge_button(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            lark = Mock()
            collab = Mock()
            collab.pr_view.return_value = {
                "number": 17,
                "state": "OPEN",
                "headRefOid": "42ffab365e72d0b0e8747fcee36f8da914bdc0b7",
                "title": "demo",
            }
            router = Router(Mock(), store, Mock(), lark, collab, logging.getLogger("g3.ux"))
            router._handle_card({
                "event_id": "evt-stale",
                "token": "tok-3",
                "operator_id": "ou_owner",
                "action": {
                    "value": {
                        "a": "accept_merge",
                        "pr": 17,
                        "sha": "b5d5a9a99a4c0aae000aa5731ec265b7cd72943a",
                        "epoch": store.epoch,
                    }
                },
            })

            card = lark.update_card.call_args.args[1]
            self.assertEqual(card["header"]["template"], "red", "旧卡作废应使用醒目红色头")
            self.assertIn("已有新提交", card["header"]["title"]["content"])
            btn_texts = [b["text"]["content"] for b in _buttons(card)]
            self.assertNotIn("通过并合并", btn_texts, "作废卡绝不能保留「通过并合并」按钮")
            self.assertEqual(btn_texts, ["刷新卡片"])


class PrViewShortCacheTest(unittest.TestCase):
    """短时复用 pr_view 减少同一次点击内的重复 gh 请求，fresh=True 强制穿透。"""

    def test_pr_view_short_cache_avoids_duplicate_gh_and_fresh_bypasses(self):
        c = Collab(Mock())
        c._gh_json = Mock(return_value={"number": 17, "state": "OPEN", "headRefOid": "aaa"})

        c.pr_view(17)
        c.pr_view(17)
        self.assertEqual(c._gh_json.call_count, 1, "短时连续 pr_view 应复用缓存避免重复调用 gh")

        c.pr_view(17, fresh=True)
        self.assertEqual(c._gh_json.call_count, 2, "fresh=True 必须穿透缓存实时查询 GitHub")


class ApprovalCardBottomWarningTest(unittest.TestCase):
    """长审批卡底部按钮上方也应显示 warning，手机不滚屏即可看到刷新结果。"""

    def test_approval_card_shows_warning_near_bottom_actions(self):
        card = cards.approval_card(
            {"number": 17, "headRefOid": "42ffab3", "title": "demo"},
            {"number": 16, "title": "demo", "labels": []},
            {},
            warning="已刷新为当前最新 SHA。",
            epoch="ep1",
        )
        md = card["elements"][0]["text"]["content"]
        last_line = [line for line in md.splitlines() if line.strip()][-1]
        self.assertIn("已刷新为当前最新 SHA。", last_line)


if __name__ == "__main__":
    unittest.main()

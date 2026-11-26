"""feishu_cards / feishu_notify / feishu_card_worker 的单元测试。

只覆盖纯函数与回调分派逻辑（用 mock 替代子进程）；不联网、不发真实消息。

运行：
    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import feishu_cards  # noqa: E402
import feishu_card_worker  # noqa: E402
import feishu_notify  # noqa: E402


class TestBuildReviewCard(unittest.TestCase):
    def setUp(self):
        self.card = feishu_cards.build_review_card(
            pr_number=34,
            title="示例变更",
            author="alice",
            base_branch="main",
            head_sha="a" * 40,
            url="https://github.com/x/y/pull/34",
            summary="一句话说明",
        )

    def test_schema_and_header(self):
        self.assertEqual(self.card["schema"], "2.0")
        self.assertEqual(self.card["header"]["template"], "orange")
        self.assertEqual(self.card["header"]["title"]["content"], "代码待你终审")

    def test_buttons_present_with_callback_values(self):
        elements = self.card["body"]["elements"]
        buttons = [e for e in elements if e.get("tag") == "button"]
        self.assertEqual(len(buttons), 3)
        # 主次层级：第一个 primary_filled，其余 default/danger
        self.assertEqual(buttons[0]["type"], "primary_filled")
        self.assertEqual(buttons[1]["type"], "default")
        self.assertEqual(buttons[2]["type"], "danger")
        for b in buttons:
            self.assertEqual(b["behaviors"][0]["type"], "callback")

    def test_callback_values_carry_action_pr_sha(self):
        buttons = [e for e in self.card["body"]["elements"] if e.get("tag") == "button"]
        got = [(b["behaviors"][0]["value"]["action"], b["behaviors"][0]["value"]["pr"]) for b in buttons]
        self.assertEqual(got, [("merge", 34), ("accept", 34), ("close", 34)])
        for b in buttons:
            self.assertEqual(b["behaviors"][0]["value"]["sha"], "a" * 40)

    def test_close_button_has_confirm(self):
        buttons = [e for e in self.card["body"]["elements"] if e.get("tag") == "button"]
        self.assertIn("confirm", buttons[2])

    def test_card_is_valid_json(self):
        json.dumps(self.card, ensure_ascii=False)

    def test_merge_stage_has_two_buttons(self):
        card = feishu_cards.build_review_card(
            pr_number=7, title="t", author="a", base_branch="main",
            head_sha="b" * 40, url="u", stage="merge",
        )
        buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
        self.assertEqual(len(buttons), 2)
        self.assertEqual(buttons[0]["text"]["content"], "合并")
        self.assertEqual(card["header"]["title"]["content"], "代码待你合并")

    def test_review_stage_header_and_three_buttons(self):
        card = feishu_cards.build_review_card(
            pr_number=7, title="t", author="a", base_branch="main",
            head_sha="b" * 40, url="u", stage="review",
        )
        buttons = [e for e in card["body"]["elements"] if e.get("tag") == "button"]
        self.assertEqual(len(buttons), 3)
        self.assertEqual(card["header"]["title"]["content"], "代码待你终审")


class TestBuildResultCard(unittest.TestCase):
    def test_merge_success(self):
        c = feishu_cards.build_result_card(34, "merge", True)
        self.assertEqual(c["header"]["template"], "green")
        self.assertEqual(c["header"]["title"]["content"], "已合并")

    def test_accept_success(self):
        c = feishu_cards.build_result_card(34, "accept", True)
        self.assertEqual(c["header"]["template"], "blue")

    def test_close_success(self):
        c = feishu_cards.build_result_card(34, "close", True)
        self.assertEqual(c["header"]["template"], "grey")

    def test_error(self):
        c = feishu_cards.build_result_card(34, "merge", False, "合并失败")
        self.assertEqual(c["header"]["template"], "red")
        self.assertEqual(c["header"]["title"]["content"], "操作失败")


class TestParseActionValue(unittest.TestCase):
    def test_full(self):
        raw = json.dumps({"action": "merge", "pr": 34, "sha": "abc"})
        self.assertEqual(feishu_cards.parse_action_value(raw), ("merge", 34, "abc"))

    def test_no_sha(self):
        raw = json.dumps({"action": "accept", "pr": 34})
        self.assertEqual(feishu_cards.parse_action_value(raw), ("accept", 34, ""))

    def test_roundtrip_from_button_value(self):
        card = feishu_cards.build_review_card(9, "t", "a", "main", "d" * 40, "u")
        btn = [e for e in card["body"]["elements"] if e.get("tag") == "button"][0]
        value = btn["behaviors"][0]["value"]
        self.assertEqual(
            feishu_cards.parse_action_value(json.dumps(value)),
            ("merge", 9, "d" * 40),
        )

    def test_bad_action(self):
        self.assertIsNone(feishu_cards.parse_action_value(json.dumps({"action": "explode", "pr": 1})))

    def test_bad_pr(self):
        self.assertIsNone(feishu_cards.parse_action_value(json.dumps({"action": "merge", "pr": "x"})))
        self.assertIsNone(feishu_cards.parse_action_value(json.dumps({"action": "merge", "pr": 0})))

    def test_empty_and_garbage(self):
        self.assertIsNone(feishu_cards.parse_action_value(""))
        self.assertIsNone(feishu_cards.parse_action_value("not-json"))
        self.assertIsNone(feishu_cards.parse_action_value(json.dumps("merge")))


class TestNotifyHelpers(unittest.TestCase):
    def test_parse_issue_marker(self):
        body = "正文\n<!-- collab:issue=12 -->\n尾注"
        self.assertEqual(feishu_notify.parse_issue_marker(body), 12)

    def test_parse_issue_marker_missing(self):
        self.assertIsNone(feishu_notify.parse_issue_marker("没有标记"))

    def test_short_summary_skips_headers(self):
        body = "# 标题\n\n<!-- collab:issue=1 -->\n\n真正的一句说明"
        self.assertEqual(feishu_notify._short_summary(body), "真正的一句说明")


class TestWorkerHelpers(unittest.TestCase):
    def test_parse_operators(self):
        self.assertEqual(feishu_card_worker.parse_operators("ou_a, ou_b ,ou_a"), {"ou_a", "ou_b"})

    def test_parse_operators_empty(self):
        self.assertEqual(feishu_card_worker.parse_operators(""), set())


class TestHandleEvent(unittest.TestCase):
    def _event(self, action="merge", pr=34, sha="abc", operator="ou_ok", token="tok1"):
        return {
            "type": "card.action.trigger",
            "event_id": "evt1",
            "operator_id": operator,
            "action_value": json.dumps({"action": action, "pr": pr, "sha": sha}),
            "token": token,
        }

    def test_unauthorized_operator_ignored(self):
        with mock.patch.object(feishu_card_worker, "perform") as perform, \
             mock.patch.object(feishu_cards, "update_card") as update:
            update.return_value = mock.Mock(returncode=0)
            feishu_card_worker.handle_event(Path("."), self._event(operator="ou_bad"), {"ou_ok"}, False, set())
            perform.assert_not_called()
            update.assert_called_once()

    def test_dry_run_does_not_perform(self):
        with mock.patch.object(feishu_card_worker, "perform") as perform, \
             mock.patch.object(feishu_cards, "update_card") as update:
            feishu_card_worker.handle_event(Path("."), self._event(), {"ou_ok"}, True, set())
            perform.assert_not_called()
            update.assert_not_called()

    def test_authorized_merge_performs_and_updates(self):
        with mock.patch.object(feishu_card_worker, "perform", return_value=(True, "已合并", "https://u")) as perform, \
             mock.patch.object(feishu_cards, "update_card") as update:
            update.return_value = mock.Mock(returncode=0)
            feishu_card_worker.handle_event(Path("."), self._event(), {"ou_ok"}, False, set())
            perform.assert_called_once_with(Path("."), "merge", 34, "abc")
            update.assert_called_once()

    def test_dedup_by_event_id(self):
        seen = {"evt1"}
        with mock.patch.object(feishu_card_worker, "perform") as perform:
            feishu_card_worker.handle_event(Path("."), self._event(), {"ou_ok"}, False, seen)
            perform.assert_not_called()

    def test_unrecognized_action_value_ignored(self):
        ev = self._event()
        ev["action_value"] = "garbage"
        with mock.patch.object(feishu_card_worker, "perform") as perform:
            feishu_card_worker.handle_event(Path("."), ev, {"ou_ok"}, False, set())
            perform.assert_not_called()


if __name__ == "__main__":
    unittest.main()

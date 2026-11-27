"""Gate 3 / G3-02 失败回归测试（2026-11-27）。

覆盖真实 PR #11 暴露的两个缺陷：
1. 合并后点「刷新」被 router 的非 OPEN 拦截，误报失败；
2. 手机内部 accept_merge 成功后未持久化闭环来源，被对账统一标为「外部闭环」，且终态卡保留操作按钮。

本文件先于修复提交，用于留下可复核的失败回显（TDD 红）。
"""
from __future__ import annotations

import json
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

from collabbot.collab_actions import Result
from collabbot.router import Router
from collabbot.service import Service
from collabbot.store import Store


def _router(store, collab, audit, lark):
    return Router(Mock(), store, audit, lark, collab, logging.getLogger("g3.tests"))


def _service(store, collab, audit, lark):
    svc = Service.__new__(Service)
    svc.store = store
    svc.collab = collab
    svc.audit = audit
    svc.lark = lark
    svc.logger = logging.getLogger("g3.tests")
    return svc


def _card_event(name, number, sha, epoch, operator="ou_owner", event_id="evt-1"):
    return {
        "event_id": event_id,
        "token": "tok-1",
        "operator_id": operator,
        "action": {"value": {"a": name, "pr": number, "sha": sha, "epoch": epoch}},
    }


def _buttons(card):
    out = []
    for element in card.get("elements", []):
        if element.get("tag") == "action":
            out.extend(element.get("actions", []))
    return out


class MergedRefreshRegressionTest(unittest.TestCase):
    """缺陷 1：合并后刷新应收敛为「已闭环」终态卡，不误报失败。"""

    def test_refresh_on_merged_pr_renders_terminal_closed_card(self):
        store = Mock()
        store.seen.return_value = False
        store.is_owner.return_value = True
        store.epoch = "ep1"
        audit = Mock()
        lark = Mock()
        collab = Mock()
        collab.pr_view.return_value = {
            "number": 11,
            "state": "MERGED",
            "headRefOid": "abc123",
            "title": "demo",
        }
        collab.issue_number.return_value = 10
        collab.issue_view.return_value = {"number": 10, "labels": []}
        collab.latest_review.return_value = {}
        router = _router(store, collab, audit, lark)

        router._handle_card(_card_event("refresh", 11, "abc123", "ep1"))

        fail = [
            c for c in audit.write.call_args_list
            if c.args[1] == "card:refresh" and (len(c.args) < 4 or c.args[3] == "fail")
        ]
        self.assertEqual(fail, [], "合并后刷新不应记为 fail")
        self.assertTrue(lark.update_card.called, "应原地更新原卡")
        card = lark.update_card.call_args.args[1]
        title = card["header"]["title"]["content"]
        self.assertIn("已闭环", title, "合并后刷新应显示「已闭环」，实际标题：%s" % title)
        self.assertEqual(_buttons(card), [], "已闭环终态卡不应保留操作按钮")


class InternalClosureSourceRegressionTest(unittest.TestCase):
    """缺陷 2：手机内部合并成功后，必须落盘内部闭环来源并收敛终态卡。"""

    def _accept_merge(self, store, collab, audit, lark):
        router = _router(store, collab, audit, lark)
        router._handle_card(
            _card_event("accept_merge", 11, "abc123", store.epoch, event_id="evt-accept")
        )

    def test_internal_merge_persists_closure_source(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            store.remember_feishu("pr", 11, "abc123", "mid-11", "C1")
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.return_value = {
                "number": 11,
                "state": "OPEN",
                "headRefOid": "abc123",
                "title": "demo",
            }
            collab.accept_and_merge.return_value = Result(True, "✅ 已通过并合并", "merged ok")
            lark = Mock()
            self._accept_merge(store, collab, Mock(), lark)

            record = [r for r in store.feishu_records() if r.get("message_id") == "mid-11"]
            self.assertTrue(record, "飞书记录应存在")
            self.assertTrue(record[0].get("closed"), "内部合并成功后应标记 closed")
            self.assertEqual(
                record[0].get("closure_source"),
                "internal",
                "应持久化内部闭环来源，实际：%s" % record[0].get("closure_source"),
            )

    def test_internal_merge_terminal_card_has_no_buttons(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.return_value = {
                "number": 11,
                "state": "OPEN",
                "headRefOid": "abc123",
                "title": "demo",
            }
            collab.accept_and_merge.return_value = Result(True, "✅ 已通过并合并", "merged ok")
            lark = Mock()
            self._accept_merge(store, collab, Mock(), lark)

            self.assertTrue(lark.update_card.called, "应回刷终态卡")
            card = lark.update_card.call_args.args[1]
            title = card["header"]["title"]["content"]
            self.assertIn("已闭环", title, "合并成功终态标题应含「已闭环」，实际：%s" % title)
            self.assertEqual(_buttons(card), [], "合并成功终态卡不应保留操作按钮")

    def test_reconcile_does_not_label_internal_as_external(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            store.remember_feishu("pr", 11, "abc123", "mid-11", "C1")
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.side_effect = [
                {"number": 11, "state": "OPEN", "headRefOid": "abc123", "title": "demo"},
                {"number": 11, "state": "MERGED", "headRefOid": "abc123", "title": "demo"},
            ]
            collab.accept_and_merge.return_value = Result(True, "✅ 已通过并合并", "merged ok")
            lark = Mock()
            self._accept_merge(store, collab, Mock(), lark)

            lark.reset_mock()
            svc = _service(store, collab, Mock(), lark)
            svc._reconcile_closures()
            for call in lark.patch_card.call_args_list:
                blob = json.dumps(call.args[1], ensure_ascii=False)
                self.assertNotIn("外部闭环", blob, "内部闭环不得被对账标为「外部闭环」")


class RetryMergeClosureRegressionTest(unittest.TestCase):
    """缺陷 2 同源：G3-06「重试合并」成功也是内部闭环，同样须落盘来源并收敛终态卡。"""

    def _retry_merge(self, store, collab, lark):
        router = _router(store, collab, Mock(), lark)
        router._handle_card(
            _card_event("retry_merge", 11, "abc123", store.epoch, event_id="evt-retry")
        )

    def test_retry_merge_persists_internal_closure(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            store.remember_feishu("pr", 11, "abc123", "mid-11", "C1")
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.return_value = {
                "number": 11,
                "state": "OPEN",
                "headRefOid": "abc123",
                "title": "demo",
            }
            collab.retry_merge.return_value = Result(True, "✅ 重试合并成功", "merged ok")
            lark = Mock()
            self._retry_merge(store, collab, lark)

            record = [r for r in store.feishu_records() if r.get("message_id") == "mid-11"]
            self.assertTrue(record, "飞书记录应存在")
            self.assertTrue(record[0].get("closed"), "重试合并成功后应标记 closed")
            self.assertEqual(
                record[0].get("closure_source"),
                "internal",
                "重试合并成功应落盘 internal 来源，实际：%s" % record[0].get("closure_source"),
            )

    def test_retry_merge_terminal_card_has_no_buttons(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.return_value = {
                "number": 11,
                "state": "OPEN",
                "headRefOid": "abc123",
                "title": "demo",
            }
            collab.retry_merge.return_value = Result(True, "✅ 重试合并成功", "merged ok")
            lark = Mock()
            self._retry_merge(store, collab, lark)

            self.assertTrue(lark.update_card.called, "应回刷终态卡")
            card = lark.update_card.call_args.args[1]
            title = card["header"]["title"]["content"]
            self.assertIn("已闭环", title, "重试合并终态标题应含「已闭环」，实际：%s" % title)
            self.assertEqual(_buttons(card), [], "重试合并终态卡不应保留操作按钮")


if __name__ == "__main__":
    unittest.main()

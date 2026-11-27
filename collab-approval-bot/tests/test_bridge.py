"""Collab 审批官桥接层单元测试（纯标准库，不真调 lark-cli / gh / git / 网络）。"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_ROOT = os.path.dirname(_HERE)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from collabbot import cards
from collabbot.collab_actions import Collab, Result
from collabbot.config import Config
from collabbot.router import Router
from collabbot.store import Store

MAX_BYTES = 28672


def _card_bytes(card: dict) -> int:
    return len(json.dumps(card, ensure_ascii=False).encode("utf-8"))


def _make_collab(member="human"):
    return Collab(
        SimpleNamespace(
            member=member,
            repo=Path("."),
            collab_py=Path("scripts/collab.py"),
        )
    )


def _make_router(store=None, collab=None, audit=None, lark=None):
    store = store or Mock()
    collab = collab or Mock()
    audit = audit or Mock()
    lark = lark or Mock()
    return Router(Mock(), store, audit, lark, collab, logging.getLogger("collabbot.tests"))


class NonOwnerDenialTest(unittest.TestCase):
    def test_non_owner_card_writes_deny_and_no_github_write(self):
        store = Mock()
        store.seen.return_value = False
        store.is_owner.return_value = False
        audit = Mock()
        lark = Mock()
        collab = Mock()
        router = _make_router(store=store, collab=collab, audit=audit, lark=lark)
        event = {
            "event_id": "evt-1",
            "operator_id": "ou_evil",
            "action": {"value": {"a": "accept_merge", "pr": 2, "sha": "abc123"}},
        }
        router._handle_card(event)

        deny_calls = [c for c in audit.write.call_args_list if c.args[1] == "card:deny"]
        self.assertTrue(deny_calls, "应写入 card:deny 审计")
        self.assertEqual(deny_calls[0].args[3], "deny")
        # 非白名单点击不得触发任何 GitHub 写/读动作
        collab.pr_view.assert_not_called()
        collab.accept_and_merge.assert_not_called()
        collab.accept_only.assert_not_called()
        collab.rework.assert_not_called()


class ShaBindingTest(unittest.TestCase):
    def test_accept_only_passes_sha(self):
        c = _make_collab()
        c.pr_view = Mock(return_value={"state": "OPEN", "headRefOid": "abc123"})
        c.run_collab = Mock(return_value=(0, "ok"))
        r = c.accept_only(5, "abc123")
        self.assertTrue(r.ok)
        c.run_collab.assert_called_once_with(
            ["accept", "5", "--member", "human", "--sha", "abc123"]
        )

    def test_accept_only_missing_sha_blocks(self):
        c = _make_collab()
        c.run_collab = Mock()
        r = c.accept_only(5, "")
        self.assertFalse(r.ok)
        self.assertIn("卡片缺少 SHA", r.title)
        c.run_collab.assert_not_called()

    def test_accept_only_sha_drift_blocks(self):
        c = _make_collab()
        c.pr_view = Mock(return_value={"state": "OPEN", "headRefOid": "newsha"})
        c.run_collab = Mock()
        r = c.accept_only(5, "oldsha")
        self.assertFalse(r.ok)
        c.run_collab.assert_not_called()

    def test_accept_and_merge_passes_sha_and_match_head(self):
        c = _make_collab()
        c.pr_view = Mock(return_value={"state": "OPEN", "headRefOid": "abc123"})
        c.run_collab = Mock(return_value=(0, "accepted"))
        c._gh = Mock(return_value=(0, "merged"))
        r = c.accept_and_merge(5, "abc123")
        self.assertTrue(r.ok)
        c.run_collab.assert_called_once_with(
            ["accept", "5", "--member", "human", "--sha", "abc123"]
        )
        c._gh.assert_called_once_with(
            ["pr", "merge", "5", "--squash", "--match-head-commit", "abc123"],
            timeout=180,
        )

    def test_accept_and_merge_missing_sha_blocks(self):
        c = _make_collab()
        c.run_collab = Mock()
        r = c.accept_and_merge(5, "")
        self.assertFalse(r.ok)
        c.run_collab.assert_not_called()

    def test_accept_and_merge_drift_during_accept_blocks_merge(self):
        c = _make_collab()
        # 第一次读（_check_expected_sha）匹配，accept 后第二次读漂移。
        c.pr_view = Mock(
            side_effect=[
                {"state": "OPEN", "headRefOid": "abc123"},
                {"state": "OPEN", "headRefOid": "xyz789"},
            ]
        )
        c.run_collab = Mock(return_value=(0, "accepted"))
        c._gh = Mock()
        r = c.accept_and_merge(5, "abc123")
        self.assertFalse(r.ok)
        self.assertIn("新提交", r.title)
        c._gh.assert_not_called()


class ConcurrencyMutexTest(unittest.TestCase):
    def test_double_click_same_sha_runs_once(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            audit = Mock()
            lark = Mock()
            collab = Mock()
            collab.repo_slug.return_value = "owner/repo"
            collab.pr_view.return_value = {
                "state": "OPEN",
                "headRefOid": "abc123",
                "number": 2,
            }
            router = _make_router(store=store, collab=collab, audit=audit, lark=lark)

            entered = threading.Event()
            release = threading.Event()
            accept_mock = Mock()

            def fake_accept_and_merge(number, sha):
                entered.set()
                release.wait(timeout=5)
                return Result(True, "ok", "merged")

            accept_mock.side_effect = fake_accept_and_merge
            collab.accept_and_merge = accept_mock

            def ev(eid):
                return {
                    "event_id": eid,
                    "operator_id": "ou_owner",
                    "action": {"value": {"a": "accept_merge", "pr": 2, "sha": "abc123"}},
                }

            t1 = threading.Thread(target=router._handle_card, args=(ev("e1"),))
            t2 = threading.Thread(target=router._handle_card, args=(ev("e2"),))
            t1.start()
            self.assertTrue(entered.wait(timeout=5), "第一个线程应进入执行")
            t2.start()
            t2.join(timeout=5)
            release.set()
            t1.join(timeout=5)

            self.assertEqual(accept_mock.call_count, 1)
            accept_audits = [
                c for c in audit.write.call_args_list if c.args[1] == "card:accept_merge"
            ]
            self.assertEqual(len(accept_audits), 1)
            # 决断标记必须释放干净
            self.assertEqual(store.data.get("decisions", {}), {})


class ReworkTest(unittest.TestCase):
    def test_rework_missing_issue_returns_partial(self):
        c = _make_collab()
        c.pr_view = Mock(
            return_value={"state": "OPEN", "headRefOid": "abc123", "body": "no issue", "comments": []}
        )
        c.repo_slug = Mock(return_value="owner/repo")
        c._gh = Mock(return_value=(0, "comment ok"))
        r = c.rework(5, "意见", "abc123")
        self.assertFalse(r.ok)
        self.assertTrue(r.warning)
        self.assertIn("未找到关联工单", r.title)
        self.assertIn("未找到关联工单", r.detail)

    def test_rework_label_failure_lists_failed(self):
        c = _make_collab()
        c.pr_view = Mock(
            return_value={
                "state": "OPEN",
                "headRefOid": "abc123",
                "body": "fix collab:issue 9",
                "comments": [],
            }
        )
        c.repo_slug = Mock(return_value="owner/repo")
        c._gh = Mock(
            side_effect=[
                (0, "comment ok"),      # pr comment
                (1, "label add failed"),  # add status:rework
                (0, ""),                # remove status:review
                (0, ""),                # remove status:ready-to-merge
                (0, ""),                # remove review:agent-passed
            ]
        )
        r = c.rework(5, "意见", "abc123")
        self.assertFalse(r.ok)
        self.assertTrue(r.warning)
        self.assertIn("工单标签未完全切换", r.title)
        self.assertIn("失败", r.detail)
        self.assertIn("status:rework", r.detail)

    def test_rework_all_labels_ok_succeeds(self):
        c = _make_collab()
        c.pr_view = Mock(
            return_value={
                "state": "OPEN",
                "headRefOid": "abc123",
                "body": "collab:issue 9",
                "comments": [],
            }
        )
        c.repo_slug = Mock(return_value="owner/repo")
        c._gh = Mock(return_value=(0, ""))
        r = c.rework(5, "意见", "abc123")
        self.assertTrue(r.ok)
        self.assertIn("已打回返工", r.title)

    def test_rework_sha_drift_writes_no_comment(self):
        c = _make_collab()
        c.pr_view = Mock(
            return_value={"state": "OPEN", "headRefOid": "newsha", "body": "collab:issue 9", "comments": []}
        )
        c._gh = Mock()
        r = c.rework(5, "意见", "oldsha")
        self.assertFalse(r.ok)
        c._gh.assert_not_called()


class RetryMergeTest(unittest.TestCase):
    def test_retry_merge_only_merges_no_accept(self):
        c = _make_collab()
        c.pr_view = Mock(return_value={"state": "OPEN", "headRefOid": "abc123"})
        c._gh = Mock(return_value=(0, "merged"))
        c.run_collab = Mock()
        r = c.retry_merge(5, "abc123")
        self.assertTrue(r.ok)
        c._gh.assert_called_once_with(
            ["pr", "merge", "5", "--squash", "--match-head-commit", "abc123"],
            timeout=180,
        )
        c.run_collab.assert_not_called()

    def test_retry_merge_sha_drift_rejects(self):
        c = _make_collab()
        c.pr_view = Mock(return_value={"state": "OPEN", "headRefOid": "newsha"})
        c._gh = Mock()
        r = c.retry_merge(5, "abc123")
        self.assertFalse(r.ok)
        c._gh.assert_not_called()


class CardSizeTest(unittest.TestCase):
    def test_result_card_long_detail_within_limit(self):
        card = cards.result_card("标题", "长" * 50000, True, pr=1)
        self.assertLessEqual(_card_bytes(card), MAX_BYTES)

    def test_approval_card_long_review_within_limit(self):
        review = {
            "member": "m",
            "verdict": "PASS",
            "family": "f",
            "sha": "a" * 40,
            "gate": "通过",
            "acceptance": ["A%d：%s" % (i, "证据" * 200) for i in range(1, 30)],
            "blindspots": {
                "隐含假设": "假" * 2000,
                "未覆盖边界": "边" * 2000,
                "关联影响": "关" * 2000,
            },
        }
        pr = {
            "number": 2,
            "headRefOid": "b" * 40,
            "title": "t",
            "changedFiles": 3,
            "additions": 10,
            "deletions": 2,
            "author": {"login": "a"},
        }
        issue = {"number": 9, "title": "i", "labels": []}
        card = cards.approval_card(pr, issue, review)
        self.assertLessEqual(_card_bytes(card), MAX_BYTES)

    def test_approval_card_no_github_jump_button(self):
        pr = {"number": 2, "headRefOid": "b" * 40, "title": "t", "url": "https://github.com/x/y/pull/2"}
        issue = {"number": 9, "title": "i", "labels": []}
        card = cards.approval_card(pr, issue, {})
        raw = json.dumps(card, ensure_ascii=False)
        self.assertNotIn("https://github.com/x/y/pull/2", raw)

    def test_blocked_card_no_github_jump_button(self):
        issue = {"number": 9, "title": "i", "url": "https://github.com/x/y/issues/9"}
        card = cards.blocked_card(issue, "blocked:needs-human")
        raw = json.dumps(card, ensure_ascii=False)
        self.assertNotIn("https://github.com/x/y/issues/9", raw)


class OverviewCardTest(unittest.TestCase):
    def test_overview_card_basic_within_limit(self):
        counts = {"ready": 1, "in-progress": 0, "review": 2, "ready-to-merge": 0,
                  "rework": 0, "draft": 0, "blocked": 1}
        pending = [{"number": 2, "title": "t", "headRefOid": "c" * 7}]
        card = cards.overview_card(counts, pending, updated_at="2026-11-27")
        raw = json.dumps(card, ensure_ascii=False)
        self.assertIn("协作总览", raw)
        self.assertLessEqual(_card_bytes(card), MAX_BYTES)

    def test_overview_card_archived_marks_first_line(self):
        card = cards.overview_card({}, [], archived=True)
        raw = json.dumps(card, ensure_ascii=False)
        self.assertIn("已归档", raw)


class ChildEnvTest(unittest.TestCase):
    def test_child_env_strips_secrets_keeps_path_home(self):
        saved = {}
        for key in ("COLLAB_BOT_HOME", "FEISHU_APP_SECRET", "COLLAB_BOT_OWNER_IDS", "PATH", "HOME"):
            saved[key] = os.environ.get(key)
        with TemporaryDirectory() as tmp:
            os.environ["COLLAB_BOT_HOME"] = tmp
            os.environ["FEISHU_APP_SECRET"] = "s3cret"
            os.environ["COLLAB_BOT_OWNER_IDS"] = "ou_x"
            os.environ["PATH"] = "/usr/bin:/bin"
            os.environ["HOME"] = os.path.expanduser("~")
            try:
                cfg = Config()
                env = cfg.child_env()
            finally:
                for key, value in saved.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
        self.assertNotIn("FEISHU_APP_SECRET", env)
        self.assertNotIn("COLLAB_BOT_OWNER_IDS", env)
        self.assertNotIn("COLLAB_BOT_HOME", env)
        self.assertIn("PATH", env)
        self.assertIn("HOME", env)


if __name__ == "__main__":
    unittest.main()

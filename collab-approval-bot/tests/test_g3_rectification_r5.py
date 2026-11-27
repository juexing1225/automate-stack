"""Gate 3 第 5 轮独立验收检出缺陷的 TDD 失败回归测试（2026-11-27）。

覆盖范围：
1. B-01 尾巴：service._reconcile_closures() 外部闭环归档卡应移除操作按钮（terminal=True）。
2. B-03：聊天指令 /rework 标签同步失败时，「重试同步标签」按钮必须携带 retry_labels_sha。
3. B-04a：preflight() 关键依赖（如 GH_TOKEN / gh auth）失败但飞书连通时，退出前向 owners 发告警。
4. B-04b：Config.child_env() 默认剥离 LARKSUITE_CLI_CONFIG_DIR（保护 collab.py 门禁子进程），仅 lark-cli 显式注入。
5. B-04c：多 owner 推送同一 PR 的 C1 卡时，remember_feishu 不互相覆盖，外部闭环时全部卡片均被刷灰。
"""
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

from collabbot.collab_actions import Result
from collabbot.config import Config
from collabbot.router import Router
from collabbot.service import Service
from collabbot.store import Store


def _buttons(card):
    out = []
    for element in card.get("elements", []):
        if element.get("tag") == "action":
            out.extend(element.get("actions", []))
    return out


class ExternalClosureTerminalCardTest(unittest.TestCase):
    """B-01 尾巴：外部闭环归档卡不应保留刷新按钮。"""

    def test_external_closure_card_has_no_buttons(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.remember_feishu("pr", 21, "sha21", "mid-21", "C1")
            collab = Mock()
            collab.pr_view.return_value = {
                "number": 21,
                "state": "MERGED",
                "headRefOid": "sha21",
            }
            lark = Mock()
            svc = Service.__new__(Service)
            svc.store = store
            svc.collab = collab
            svc.lark = lark
            svc.audit = Mock()
            svc.logger = logging.getLogger("g3.r5")

            svc._reconcile_closures()

            self.assertEqual(lark.patch_card.call_count, 1)
            card = lark.patch_card.call_args.args[1]
            self.assertEqual(_buttons(card), [], "外部闭环归档卡不应保留任何操作按钮")


class ReworkCommandRetryShaTest(unittest.TestCase):
    """B-03：聊天指令 /rework 返回的部分失败卡，重试同步标签按钮须携带 sha。"""

    def test_rework_command_retry_labels_button_carries_sha(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            sha = "1234567890abcdef1234567890abcdef12345678"
            collab = Mock()
            collab.pr_view.return_value = {
                "number": 13,
                "state": "OPEN",
                "headRefOid": sha,
                "title": "demo",
                "body": "collab:issue=13",
            }
            collab.issue_number.return_value = 13
            collab.issue_view.return_value = {"number": 13, "labels": []}
            collab.latest_review.return_value = {}
            collab.rework.return_value = Result(
                False,
                "⚠️ 评论已写，但读取工单标签失败",
                "fail",
                warning=True,
                retry_labels_issue=13,
                retry_labels_sha=sha,
            )
            lark = Mock()
            router = Router(Mock(), store, Mock(), lark, collab, logging.getLogger("g3.r5"))

            router._handle_pr_command("ou_owner", "rework", "13 请补单测")

            self.assertTrue(lark.send_card.called)
            card = lark.send_card.call_args.args[1]
            retry_btns = [
                b for b in _buttons(card)
                if b.get("text", {}).get("content") == "重试同步标签"
            ]
            self.assertEqual(len(retry_btns), 1)
            self.assertEqual(
                retry_btns[0]["value"].get("sha"),
                sha,
                "/rework 指令生成的重试同步标签按钮必须携带 retry_labels_sha",
            )


class PreflightAlertTest(unittest.TestCase):
    """B-04a：preflight 关键依赖失败但飞书连通时，退出前应向 owners 发告警。"""

    def test_preflight_failure_alerts_owners_when_lark_ok(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner1")
            svc = Service.__new__(Service)
            svc.config = Mock()
            svc.config.lock_path = Path(tmp) / "bot.lock"
            svc.store = store
            svc.lark = Mock()
            svc.logger = logging.getLogger("g3.r5")
            svc.acquire_lock = Mock(return_value=True)
            svc.preflight = Mock(
                return_value=(
                    ["gh 未登录或不可用：Bad credentials"],
                    ["飞书接口已连通：{\"app_name\": \"Collab\"}"],
                )
            )

            rc = svc.run()

            self.assertEqual(rc, 2)
            self.assertTrue(
                svc.lark.send_markdown.called,
                "preflight 失败且飞书已连通时，退出前应向 owner 发送告警消息",
            )
            sent_to, sent_body = svc.lark.send_markdown.call_args.args
            self.assertEqual(sent_to, "ou_owner1")
            self.assertIn("gh 未登录或不可用", sent_body)


class ChildEnvIsolationTest(unittest.TestCase):
    """B-04b：门禁子进程默认不透传 LARKSUITE_CLI_CONFIG_DIR，仅 lark-cli 显式注入。"""

    def test_child_env_strips_lark_config_for_collab_keeps_for_lark(self):
        with TemporaryDirectory() as tmp:
            old_home = os.environ.get("COLLAB_BOT_HOME")
            os.environ["COLLAB_BOT_HOME"] = tmp
            try:
                cfg = Config()
                collab_env = cfg.child_env()
                self.assertNotIn(
                    "LARKSUITE_CLI_CONFIG_DIR",
                    collab_env,
                    "默认 child_env（给 collab.py/gh/git）不应透传 LARKSUITE_CLI_CONFIG_DIR",
                )
                lark_env = cfg.child_env(include_lark=True)
                self.assertEqual(
                    lark_env.get("LARKSUITE_CLI_CONFIG_DIR"),
                    cfg.lark_config_dir,
                )
            finally:
                if old_home is None:
                    os.environ.pop("COLLAB_BOT_HOME", None)
                else:
                    os.environ["COLLAB_BOT_HOME"] = old_home


class MultiOwnerFeishuRecordTest(unittest.TestCase):
    """B-04c：多 owner 同 PR 发卡不互相覆盖，外部闭环全部刷灰。"""

    def test_multi_owner_feishu_records_all_patched_on_closure(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.remember_feishu("pr", 30, "sha30", "mid-owner1", "C1")
            store.remember_feishu("pr", 30, "sha30", "mid-owner2", "C1")

            collab = Mock()
            collab.pr_view.return_value = {
                "number": 30,
                "state": "MERGED",
                "headRefOid": "sha30",
            }
            lark = Mock()
            svc = Service.__new__(Service)
            svc.store = store
            svc.collab = collab
            svc.lark = lark
            svc.audit = Mock()
            svc.logger = logging.getLogger("g3.r5")

            svc._reconcile_closures()

            patched_mids = [call.args[0] for call in lark.patch_card.call_args_list]
            self.assertEqual(
                sorted(patched_mids),
                ["mid-owner1", "mid-owner2"],
                "多 owner 的全部 C1 卡都应被外部闭环刷灰，实际：%s" % patched_mids,
            )


if __name__ == "__main__":
    unittest.main()

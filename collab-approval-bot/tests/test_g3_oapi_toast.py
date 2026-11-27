"""方案 A（lark-oapi 官方长连接 + 同步原生 Toast）TDD 失败回归测试。"""
from __future__ import annotations

import json
import logging
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock

_HERE = os.path.dirname(os.path.abspath(__file__))
_BOT_ROOT = os.path.dirname(_HERE)
if _BOT_ROOT not in sys.path:
    sys.path.insert(0, _BOT_ROOT)

from collabbot.collab_actions import Result
from collabbot.config import Config
from collabbot.router import Router
from collabbot.service import Service, normalize_oapi_card, normalize_oapi_message
from collabbot.store import Store


class PreviewCardToastTest(unittest.TestCase):
    """同步回调必须在 <1ms 内纯内存返回精准的 Toast 类型与文案。"""

    def test_preview_card_toast_returns_instant_feedback_for_all_states(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            router = Router(Mock(), store, Mock(), Mock(), Mock(), logging.getLogger("g3.oapi"))

            # 非白名单
            t, msg = router.preview_card_toast({
                "operator_id": "ou_stranger",
                "action": {"value": {"a": "accept_merge", "pr": 17, "sha": "abc", "epoch": store.epoch}},
            })
            self.assertEqual(t, "error")
            self.assertIn("白名单", msg)

            # 纪元过期
            t, msg = router.preview_card_toast({
                "operator_id": "ou_owner",
                "action": {"value": {"a": "accept_merge", "pr": 17, "sha": "abc", "epoch": "old-ep"}},
            })
            self.assertEqual(t, "warning")
            self.assertIn("过期", msg)

            # rework 空意见
            t, msg = router.preview_card_toast({
                "operator_id": "ou_owner",
                "action": {
                    "value": {"a": "rework", "pr": 17, "sha": "abc", "epoch": store.epoch},
                    "form_value": {"note": "  "},
                },
            })
            self.assertEqual(t, "warning")
            self.assertIn("意见", msg)

            # 合法 accept_merge
            t, msg = router.preview_card_toast({
                "operator_id": "ou_owner",
                "action": {"value": {"a": "accept_merge", "pr": 17, "sha": "abc", "epoch": store.epoch}},
            })
            self.assertEqual(t, "info")
            self.assertIn("终审", msg)

            # 合法 retry_merge
            t, msg = router.preview_card_toast({
                "operator_id": "ou_owner",
                "action": {"value": {"a": "retry_merge", "pr": 17, "sha": "abc", "epoch": store.epoch}},
            })
            self.assertEqual(t, "info")
            self.assertIn("重试合并", msg)


class ToastSkipsShrinkingProgressTest(unittest.TestCase):
    """已发送原生 Toast 时，不再把长审批卡缩成 2 行过渡态跳屏，直接一步更新终态。"""

    def test_toast_sent_skips_shrinking_progress_card_keeps_original_until_final(self):
        with TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "state.json")
            store.add_owner("ou_owner")
            lark = Mock()
            collab = Mock()
            collab.repo_slug.return_value = "juexing1225/collab-mvp-demo"
            collab.pr_view.return_value = {
                "number": 17, "state": "OPEN", "headRefOid": "sha17", "title": "demo",
            }
            collab.retry_merge.return_value = Result(True, "✅ 重试合并成功", "ok")

            router = Router(Mock(), store, Mock(), lark, collab, logging.getLogger("g3.oapi"))
            router._handle_card({
                "event_id": "evt-toast-1",
                "token": "tok-1",
                "operator_id": "ou_owner",
                "_toast_sent": True,
                "action": {"value": {"a": "retry_merge", "pr": 17, "sha": "sha17", "epoch": store.epoch}},
            })

            self.assertEqual(
                lark.update_card.call_count,
                1,
                "已发原生 Toast 时不应先刷过渡态缩卡，应只更新 1 次终态卡",
            )
            title = lark.update_card.call_args.args[1]["header"]["title"]["content"]
            self.assertIn("已闭环", title)


class OapiConfigAndPreflightTest(unittest.TestCase):
    """验证 Config.use_oapi、敏感环境变量剥离与 SuperAgent App 拦截。"""

    def test_config_use_oapi_and_child_env_strips_feishu_secrets(self):
        with TemporaryDirectory() as tmp:
            backup = {k: os.environ.get(k) for k in ("COLLAB_BOT_HOME", "FEISHU_APP_ID", "FEISHU_APP_SECRET")}
            os.environ["COLLAB_BOT_HOME"] = tmp
            os.environ["FEISHU_APP_ID"] = "cli_ab82d1e59db8dce0"
            os.environ["FEISHU_APP_SECRET"] = "sec_fake_test_value"
            try:
                cfg = Config()
                self.assertTrue(cfg.use_oapi)
                env = cfg.child_env()
                self.assertNotIn("FEISHU_APP_ID", env)
                self.assertNotIn("FEISHU_APP_SECRET", env)
            finally:
                for k, v in backup.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v

    def test_preflight_oapi_blocks_forbidden_superagent_app_id(self):
        with TemporaryDirectory() as tmp:
            svc = Service.__new__(Service)
            svc.config = Mock()
            svc.config.use_oapi = True
            svc.config.feishu_app_id = "cli_aa60277cb9f85ce1"
            svc.config.feishu_app_secret = "sec_fake"
            svc.config.repo = Path(tmp)
            svc.config.collab_py = Path(tmp) / "collab.py"
            svc.config.collab_py.write_text("# stub", "utf-8")
            svc.collab = Mock()
            svc.collab.repo_info.return_value = {"is_repo": True, "remote": "https://github.com/a/b", "dirty": []}
            svc.collab.gh_auth_status.return_value = (0, "ok")
            svc.lark = Mock()
            svc.lark.bot_info.return_value = {"app_name": "bad"}

            fatal, _ = svc.preflight()
            self.assertTrue(
                any("SuperAgent" in f or "cli_aa60277cb9f85ce1" in f for f in fatal),
                "use_oapi 模式也必须硬拦截 SuperAgent App ID，实际 fatal：%s" % fatal,
            )


class OapiEventNormalizationTest(unittest.TestCase):
    """验证 lark-oapi 事件对象向 Router 标准字典的转换。"""

    def test_oapi_event_normalization_parses_message_and_card_trigger(self):
        msg_obj = SimpleNamespace(
            event=SimpleNamespace(
                sender=SimpleNamespace(
                    sender_type="user",
                    sender_id=SimpleNamespace(open_id="ou_u1"),
                ),
                message=SimpleNamespace(
                    message_id="om_m1",
                    chat_type="p2p",
                    message_type="text",
                    content=json.dumps({"text": "/card 17"}),
                ),
            )
        )
        m = normalize_oapi_message(msg_obj)
        self.assertEqual(m["sender_type"], "user")
        self.assertEqual(m["sender_id"], "ou_u1")
        self.assertEqual(m["message_id"], "om_m1")
        self.assertEqual(m["chat_type"], "p2p")
        self.assertEqual(m["content"], "/card 17")

        card_obj = SimpleNamespace(
            header=SimpleNamespace(event_id="ev_c1"),
            event=SimpleNamespace(
                operator=SimpleNamespace(open_id="ou_u1"),
                token="tok_xyz",
                action=SimpleNamespace(
                    tag="button",
                    name="rework:17:abc:ep1",
                    value={"a": "accept_merge", "pr": 17, "sha": "abc", "epoch": "ep1"},
                    form_value={"note": "hi"},
                    input_value="",
                ),
            ),
        )
        c = normalize_oapi_card(card_obj)
        self.assertEqual(c["event_id"], "ev_c1")
        self.assertEqual(c["operator_id"], "ou_u1")
        self.assertEqual(c["token"], "tok_xyz")
        self.assertEqual(c["action"]["value"]["pr"], 17)
        self.assertEqual(c["action"]["form_value"]["note"], "hi")


if __name__ == "__main__":
    unittest.main()

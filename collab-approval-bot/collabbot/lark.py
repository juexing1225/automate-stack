"""飞书传输层：统一通过本机 lark-cli 调用，凭据留在 lark-cli 的配置目录。"""
from __future__ import annotations

import json
import subprocess
from typing import Optional


class LarkError(RuntimeError):
    pass


class Lark:
    def __init__(self, config) -> None:
        self.config = config

    def _run(self, args, stdin_text: Optional[str] = None, timeout: int = 60) -> dict:
        command = [self.config.lark_cli] + list(args)
        try:
            proc = subprocess.run(
                command,
                input=stdin_text,
                text=True,
                capture_output=True,
                timeout=timeout,
                env=self.config.child_env(include_lark=True),
            )
        except FileNotFoundError as exc:
            raise LarkError(
                "找不到 lark-cli：%s。请先安装或设置 COLLAB_BOT_LARK_CLI。"
                % self.config.lark_cli
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise LarkError("lark-cli 调用超时（%ss）" % timeout) from exc

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        payload = None
        if stdout:
            try:
                payload = json.loads(stdout)
            except ValueError:
                payload = None

        if proc.returncode == 0 and isinstance(payload, dict) and payload.get("ok") is True:
            return payload

        message = ""
        hint = ""
        if isinstance(payload, dict):
            error = payload.get("error") or {}
            message = error.get("message") or payload.get("msg") or ""
            hint = error.get("hint") or ""
        if not message and stderr:
            try:
                error = json.loads(stderr).get("error") or {}
                message = error.get("message") or ""
                hint = error.get("hint") or ""
            except ValueError:
                lines = [line for line in stderr.splitlines() if line.strip()]
                message = lines[-1] if lines else stderr
        if not message:
            message = "lark-cli 退出码 %s" % proc.returncode
        raise LarkError(message + (("；" + hint) if hint else ""))

    def api(self, method: str, path: str, params=None, data=None, timeout: int = 60) -> dict:
        args = ["api", method, path]
        if params:
            args += ["--params", json.dumps(params, ensure_ascii=False)]
        if data is not None:
            args += ["--data", "-"]
        payload = self._run(
            args,
            stdin_text=json.dumps(data, ensure_ascii=False) if data is not None else None,
            timeout=timeout,
        )
        return payload.get("data") or {}

    def send_text(self, open_id: str, text: str) -> dict:
        self._run(
            ["im", "+messages-send", "--as", "bot", "--user-id", open_id, "--text", "-"],
            stdin_text=text,
            timeout=30,
        )
        return {"ok": True}

    def send_markdown(self, open_id: str, markdown: str) -> dict:
        self._run(
            [
                "im", "+messages-send", "--as", "bot",
                "--user-id", open_id, "--markdown", "-",
            ],
            stdin_text=markdown,
            timeout=30,
        )
        return {"ok": True}

    def send_card(self, open_id: str, card: dict) -> str:
        data = {
            "receive_id": open_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
        }
        result = self.api(
            "POST",
            "/open-apis/im/v1/messages",
            params={"receive_id_type": "open_id"},
            data=data,
        )
        return str(result.get("message_id") or "")

    def update_card(self, token: str, card: dict) -> None:
        # 卡片是 update_multi=true 的共享卡片，不能再传 open_ids。
        self.api(
            "POST",
            "/open-apis/interactive/v1/card/update",
            data={"token": token, "card": card},
        )

    def patch_card(self, message_id: str, card: dict) -> None:
        """按 message_id 回刷（PATCH）整条消息的卡片内容。

        走飞书开放平台「更新应用发送的消息」接口：
        PATCH /open-apis/im/v1/messages/:message_id，body 为 {"content": "<card JSON>"}。
        通过 lark-cli 的 `api` 子命令透传；若 lark-cli 版本不支持该子命令，
        可换成对应的 messages 子命令，语义不变。
        """
        self.api(
            "PATCH",
            "/open-apis/im/v1/messages/" + str(message_id),
            data={"content": json.dumps(card, ensure_ascii=False)},
        )

    def bot_info(self) -> dict:
        return self.api("GET", "/open-apis/bot/v3/info")

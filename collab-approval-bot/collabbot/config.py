"""运行时配置。敏感信息只从环境变量或 lark-cli 的本地凭据读取，不写入仓库。"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_MIRROR_ROOT = os.path.expanduser("~/.collab-bridge/repos")
DEFAULT_REPO = os.path.join(DEFAULT_MIRROR_ROOT, "collab-mvp-demo")


def load_env_file(path: str) -> None:
    """加载简单的 KEY=VALUE 文件；已存在的环境变量优先。"""
    file_path = Path(os.path.expanduser(os.path.expandvars(path)))
    if not file_path.is_file():
        return
    try:
        lines = file_path.read_text("utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def _env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


load_env_file(_env("COLLAB_BOT_ENV_FILE", "~/.config/collab/feishu.env"))


def _flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(value: str) -> str:
    return os.path.abspath(os.path.expanduser(os.path.expandvars(value)))


class Config:
    def __init__(self) -> None:
        self.home = Path(_path(_env("COLLAB_BOT_HOME", "~/.collab-approval-bot")))
        self.mirror_root = _path(_env("COLLAB_BRIDGE_MIRROR_ROOT", DEFAULT_MIRROR_ROOT))
        self.repo = Path(
            _path(
                _env(
                    "COLLAB_REPO",
                    os.path.join(self.mirror_root, "collab-mvp-demo"),
                )
            )
        )
        self.member = _env("COLLAB_BOT_MEMBER", "human")
        self.owner_ids = {
            item.strip()
            for item in _env("COLLAB_BOT_OWNER_IDS", "").split(",")
            if item.strip()
        }
        self.allow_group = _flag("COLLAB_BOT_ALLOW_GROUP", False)
        self.safe_mode = _flag("COLLAB_BOT_SAFE_MODE", True)
        self.cmd_timeout = int(_env("COLLAB_BOT_CMD_TIMEOUT", "120"))
        self.max_output = int(_env("COLLAB_BOT_MAX_OUTPUT", "3800"))
        self.poll_seconds = int(_env("COLLAB_BOT_POLL_SECONDS", "120"))
        self.lark_cli = _path(_env("COLLAB_BOT_LARK_CLI", "~/.local/bin/lark-cli"))
        self.lark_config_dir = _path(
            _env("LARKSUITE_CLI_CONFIG_DIR", "~/.lark-cli-collab")
        )
        self.app_name = _env("COLLAB_BOT_APP_NAME", "Collab")
        self.log_level = _env("COLLAB_BOT_LOG_LEVEL", "INFO").upper()

        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "logs").mkdir(parents=True, exist_ok=True)
        for path in (self.home, self.home / "logs"):
            try:
                os.chmod(path, 0o700)
            except OSError:
                pass
        self.state_path = self.home / "state.json"
        self.audit_path = self.home / "audit.jsonl"
        self.lock_path = self.home / "bot.lock"
        self.log_path = self.home / "logs" / "bot.log"

    @property
    def collab_py(self) -> Path:
        return self.repo / "scripts" / "collab.py"

    def child_env(self) -> dict:
        # 白名单最小环境：只透传运行 collab.py / gh / git / lark-cli 所需的变量，
        # 剥离 FEISHU_APP_SECRET、COLLAB_BOT_*、LARKSUITE_CLI_CONFIG_DIR 等桥接敏感变量。
        keep = {
            "PATH",
            "HOME",
            "LANG",
            "LC_ALL",
            "PYTHONIOENCODING",
            "GITHUB_TOKEN",
            "GH_TOKEN",
            "SSH_AUTH_SOCK",
        }
        env = {k: v for k, v in os.environ.items() if k in keep and v}
        env["LARKSUITE_CLI_CONFIG_DIR"] = self.lark_config_dir
        base = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
        current = env.get("PATH", "")
        env["PATH"] = base + (":" + current if current else "")
        env.setdefault("LANG", "zh_CN.UTF-8")
        env.setdefault("LC_ALL", "zh_CN.UTF-8")
        env.setdefault("HOME", str(Path.home()))
        env["PYTHONIOENCODING"] = "utf-8"
        return env

#!/usr/bin/env python3
"""Collab 审批官入口。"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collabbot.config import Config
from collabbot.service import Service


def setup_logging(config: Config) -> logging.Logger:
    logger = logging.getLogger("collabbot")
    logger.setLevel(getattr(logging, config.log_level, logging.INFO))
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s")
    file_handler = logging.FileHandler(config.log_path, encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    try:
        os.chmod(config.log_path, 0o600)
    except OSError:
        pass
    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    logger.propagate = False
    return logger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Collab 审批官 · 飞书审批遥控器")
    parser.add_argument("--check", action="store_true", help="只做启动预检，不启动服务")
    parser.add_argument("--bind-code", action="store_true", help="打印当前绑定码")
    args = parser.parse_args(argv)

    config = Config()
    logger = setup_logging(config)
    service = Service(config)

    if args.bind_code:
        if service.store.owners:
            print("已绑定主人：" + ", ".join(service.store.owners))
            print("绑定码已失效；如需增加主人，请设置 COLLAB_BOT_OWNER_IDS 后重启。")
        else:
            print("绑定码 BIND_CODE: " + service.store.bind_code)
            print("尚未绑定主人。")
        return 0

    if args.check:
        fatal, notes = service.preflight()
        for line in notes:
            print("✓ " + line)
        for line in fatal:
            print("✖ " + line)
        return 0 if not fatal else 1

    def stop(signum, frame):
        logger.info("收到信号 %s，正在退出", signum)
        service.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    return service.run()


if __name__ == "__main__":
    sys.exit(main())

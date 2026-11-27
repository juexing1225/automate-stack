"""本地派生状态：绑定码、主人白名单、事件幂等、待确认命令、已通知记录。"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _new_bind_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(6))


def _new_epoch() -> str:
    return secrets.token_hex(8)


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        existed = self.path.exists()
        self.data = self._load()
        self._ensure_defaults()
        if not existed:
            # 首次生成的绑定码必须落盘，否则重启会换码，用户来不及绑定。
            self._save()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text("utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                pass
        return {
            "version": 1,
            "bind_code": _new_bind_code(),
            "boot_epoch": _new_epoch(),
            "owners": [],
            "handled": {},
            "pending": {},
            "notified": {},
            "decisions": {},
            "feishu": {},
            "overview": {},
        }

    def _ensure_defaults(self) -> None:
        if not isinstance(self.data.get("bind_code"), str) or not self.data["bind_code"]:
            self.data["bind_code"] = _new_bind_code()
        if not isinstance(self.data.get("boot_epoch"), str) or not self.data["boot_epoch"]:
            self.data["boot_epoch"] = _new_epoch()
        for key in ("owners", "handled", "pending", "notified", "decisions", "feishu", "overview"):
            if not isinstance(self.data.get(key), type({} if key != "owners" else [])):
                self.data[key] = {} if key != "owners" else []

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2), "utf-8"
        )
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    @property
    def bind_code(self) -> str:
        with self._lock:
            return str(self.data["bind_code"])

    @property
    def epoch(self) -> str:
        """实例纪元：state.json 新建时生成，缓存全丢重建时自动换新，用于拒绝重启前的旧卡按钮。"""
        with self._lock:
            return str(self.data["boot_epoch"])

    @property
    def owners(self) -> list:
        with self._lock:
            return list(self.data.get("owners", []))

    def has_owner(self) -> bool:
        return bool(self.owners)

    def is_owner(self, open_id: str) -> bool:
        return open_id in self.owners

    def add_owner(self, open_id: str) -> bool:
        with self._lock:
            owners = self.data.setdefault("owners", [])
            if open_id in owners:
                return False
            owners.append(open_id)
            self._save()
            return True

    def bind(self, open_id: str, code: str):
        with self._lock:
            if open_id in self.data.setdefault("owners", []):
                return True, "你已绑定，无需重复操作。"
            if code.strip().upper() != self.data["bind_code"]:
                return False, "绑定码不正确。请在 Mac 上查看启动日志里的 BIND_CODE。"
            if self.data["owners"]:
                return False, "已有主人，绑定码已失效。"
            self.data["owners"].append(open_id)
            # 一次性绑定码：绑定成功后立即轮换，旧码不能再拉人进白名单。
            self.data["bind_code"] = _new_bind_code()
            self._save()
            return True, "绑定成功"

    def seen(self, key: str, ttl_seconds: int = 7 * 86400) -> bool:
        """记录并判断是否已处理；True 表示重复。"""
        with self._lock:
            handled = self.data.setdefault("handled", {})
            now = time.time()
            if key in handled:
                return True
            handled[key] = now
            cutoff = now - ttl_seconds
            for old_key in [k for k, ts in handled.items() if ts < cutoff]:
                handled.pop(old_key, None)
            if len(handled) > 5000:
                for old_key in sorted(handled, key=handled.get)[:1000]:
                    handled.pop(old_key, None)
            self._save()
            return False

    def add_pending(self, actor: str, payload: dict, ttl_seconds: int = 300) -> str:
        with self._lock:
            pending = self.data.setdefault("pending", {})
            pid = secrets.token_hex(3).upper()
            pending[pid] = {
                "actor": actor,
                "payload": payload,
                "created": time.time(),
                "expires": time.time() + ttl_seconds,
            }
            self._save()
            return pid

    def pop_pending(self, pid: str, actor: str):
        with self._lock:
            pending = self.data.setdefault("pending", {})
            item = pending.get(pid.upper())
            if not item:
                return None, "没有这个待确认操作（可能已执行或已过期）。"
            if item["actor"] != actor:
                return None, "这个待确认操作不属于你。"
            if time.time() > item["expires"]:
                pending.pop(pid.upper(), None)
                self._save()
                return None, "待确认操作已过期，请重新发起。"
            pending.pop(pid.upper(), None)
            self._save()
            return item["payload"], ""

    def once(self, key: str, ttl_seconds: int = 14 * 86400) -> bool:
        """通知去重；True 表示第一次。"""
        with self._lock:
            notified = self.data.setdefault("notified", {})
            now = time.time()
            if key in notified:
                return False
            notified[key] = now
            cutoff = now - ttl_seconds
            for old_key in [k for k, ts in notified.items() if ts < cutoff]:
                notified.pop(old_key, None)
            if len(notified) > 5000:
                for old_key in sorted(notified, key=notified.get)[:1000]:
                    notified.pop(old_key, None)
            self._save()
            return True

    def is_notified(self, key: str) -> bool:
        with self._lock:
            return key in self.data.setdefault("notified", {})

    def decision_in_progress(self, key: str, ttl_seconds: int = 600) -> bool:
        """同轮互斥决断。返回 True 表示本调用者取得执行权，False 表示已有并发/重放在进行。

        进程内由 threading 锁串行化「查-占」，落盘 decisions 记录防重启后重放；
        过期记录会被回收，避免崩溃后永久卡死。
        """
        with self._lock:
            decisions = self.data.setdefault("decisions", {})
            now = time.time()
            for old_key in [k for k, ts in decisions.items() if ts < now - ttl_seconds]:
                decisions.pop(old_key, None)
            if key in decisions:
                return False
            decisions[key] = now
            self._save()
            return True

    def finish_decision(self, key: str) -> None:
        with self._lock:
            decisions = self.data.setdefault("decisions", {})
            decisions.pop(key, None)
            self._save()

    def remember_feishu(self, target: str, number: int, sha: str, message_id: str, kind: str) -> None:
        with self._lock:
            feishu = self.data.setdefault("feishu", {})
            key = "%s:%s:%s" % (target, number, sha)
            feishu[key] = {
                "target": target,
                "number": number,
                "sha": sha,
                "message_id": message_id,
                "kind": kind,
                "closed": False,
            }
            self._save()

    def mark_feishu_closed(self, target: str, number: int, sha: str) -> None:
        """把已刷灰（外部闭环）的卡片记录标记为 closed，后续对账跳过，避免无限重复 PATCH。"""
        with self._lock:
            feishu = self.data.setdefault("feishu", {})
            key = "%s:%s:%s" % (target, number, sha)
            record = feishu.get(key)
            if record is not None:
                record["closed"] = True
                self._save()

    def feishu_records(self) -> list:
        with self._lock:
            return list(self.data.setdefault("feishu", {}).values())

    def overview_state(self) -> dict:
        with self._lock:
            return dict(self.data.setdefault("overview", {}))

    def save_overview_state(self, state: dict) -> None:
        with self._lock:
            self.data["overview"] = dict(state)
            self._save()


class Audit:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def write(self, actor: str, action: str, detail: str = "", result: str = "ok") -> None:
        record = {
            "ts": _now_iso(),
            "actor": actor,
            "action": action,
            "detail": detail[:2000],
            "result": result,
        }
        line = json.dumps(record, ensure_ascii=False)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            if self.path.stat().st_size > 5 * 1024 * 1024:
                self.path.rename(self.path.with_suffix(".1"))
        except OSError:
            pass

    def tail(self, count: int = 10) -> list:
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text("utf-8").splitlines()
        except OSError:
            return []
        return lines[-count:]

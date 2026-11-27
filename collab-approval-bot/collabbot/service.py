"""常驻服务：双事件流消费、启动预检、待办对账与单实例锁。"""
from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import cards
from .collab_actions import Collab
from .config import Config
from .lark import Lark, LarkError
from .router import Router
from .store import Audit, Store

EVENT_KEYS = ("im.message.receive_v1", "card.action.trigger")
FORBIDDEN_APP_IDS = {"cli_aa60277cb9f85ce1"}  # 已连 SuperAgent 的机器人，不能复用


class Service:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.logger = logging.getLogger("collabbot")
        self.store = Store(config.state_path)
        for owner in config.owner_ids:
            self.store.add_owner(owner)
        self.audit = Audit(config.audit_path)
        self.lark = Lark(config)
        self.collab = Collab(config)
        self.router = Router(
            config, self.store, self.audit, self.lark, self.collab, self.logger,
        )
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="event")
        self._procs = []
        self._proc_lock = threading.Lock()
        self._lock_handle = None

    # ---------- 启动 ----------

    def acquire_lock(self) -> bool:
        self._lock_handle = open(self.config.lock_path, "w")
        try:
            fcntl.flock(self._lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self._lock_handle.write(str(os.getpid()))
        self._lock_handle.flush()
        return True

    def preflight(self):
        fatal = []
        notes = []

        if not self.config.repo.is_dir():
            fatal.append("镜像仓不存在：%s" % self.config.repo)
        elif not self.config.collab_py.is_file():
            fatal.append("镜像仓里没有 scripts/collab.py：%s" % self.config.repo)
        else:
            notes.append("镜像仓：%s" % self.config.repo)
            info = self.collab.repo_info()
            if not info.get("is_repo", True):
                fatal.append("镜像仓不是 git 仓库：%s" % self.config.repo)
            if not info.get("remote"):
                fatal.append("镜像仓未配置 origin 远端（git remote get-url origin 为空）：%s" % self.config.repo)
            if info.get("dirty"):
                fatal.append(
                    "镜像仓工作区不干净（%d 处未提交改动），禁止在脏工作区跑审批：%s"
                    % (len(info["dirty"]), self.config.repo)
                )

        if not Path(self.config.lark_cli).is_file():
            fatal.append("找不到 lark-cli：%s" % self.config.lark_cli)

        cfg_path = Path(self.config.lark_config_dir) / "config.json"
        has_lark_config = False
        if not cfg_path.is_file():
            fatal.append(
                "飞书应用尚未初始化：%s 不存在。请先运行 "
                "LARKSUITE_CLI_CONFIG_DIR=%s %s config init --new"
                % (cfg_path, self.config.lark_config_dir, self.config.lark_cli)
            )
        else:
            try:
                data = json.loads(cfg_path.read_text("utf-8"))
                apps = data.get("apps") or []
                first = apps[0] if isinstance(apps, list) and apps else {}
                if not isinstance(first, dict):
                    first = {}
                app_obj = data.get("app")
                if not isinstance(app_obj, dict):
                    app_obj = {}
                app_id = str(
                    first.get("appId")
                    or first.get("app_id")
                    or data.get("appId")
                    or data.get("app_id")
                    or app_obj.get("appId", "")
                )
                if not app_id:
                    fatal.append("飞书配置里没有 appId：%s" % cfg_path)
                elif app_id in FORBIDDEN_APP_IDS:
                    fatal.append(
                        "飞书配置指向已连 SuperAgent 的机器人（%s），会抢事件、串身份；"
                        "必须用独立目录新建应用。" % app_id
                    )
                else:
                    notes.append("飞书应用：%s…" % app_id[:12])
                    has_lark_config = True
            except (OSError, ValueError) as exc:
                fatal.append("飞书配置无法解析：%s" % exc)

        rc, output = self.collab.gh_auth_status()
        if rc != 0:
            fatal.append("gh 未登录或不可用：%s" % output[:300])
        else:
            notes.append("GitHub CLI 已登录")

        if has_lark_config:
            try:
                info = self.lark.bot_info()
                notes.append(
                    "飞书接口已连通：%s" % json.dumps(info, ensure_ascii=False)[:160]
                )
            except LarkError as exc:
                fatal.append("飞书接口不可用：%s" % exc)

        return fatal, notes

    def start_consumers(self) -> None:
        for key in EVENT_KEYS:
            handler = (
                self.router.handle_message
                if key == "im.message.receive_v1"
                else self.router.handle_card
            )
            thread = threading.Thread(
                target=self._consume,
                args=(key, handler),
                name="consume-" + key,
                daemon=True,
            )
            thread.start()
        thread = threading.Thread(
            target=self._reconcile_loop, name="reconcile", daemon=True
        )
        thread.start()

    # ---------- 事件消费 ----------

    def _consume(self, key: str, handler) -> None:
        args = [
            self.config.lark_cli,
            "event", "consume", key,
            "--as", "bot",
            "--max-events", "0",
            "--timeout", "0",
            "--quiet",
        ]
        while not self.stop.is_set():
            try:
                proc = subprocess.Popen(
                    args,
                    # lark-cli 把 stdin EOF 当作退出信号；后台线程启动时
                    # stdin 往往已关闭，必须显式保留一个不关闭的管道。
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    bufsize=1,
                    env=self.config.child_env(),
                )
            except OSError as exc:
                self.logger.error("启动事件消费失败（%s）：%s", key, exc)
                self.stop.wait(5)
                continue

            with self._proc_lock:
                self._procs.append(proc)
            self.logger.info("开始消费事件：%s", key)
            try:
                for line in proc.stdout:
                    if self.stop.is_set():
                        break
                    line = line.strip()
                    if not line or not line.startswith("{"):
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    event = payload.get("event")
                    if not isinstance(event, dict):
                        event = payload
                    if not isinstance(event, dict):
                        continue
                    if key == "im.message.receive_v1" and not event.get("message_id"):
                        continue
                    if key == "card.action.trigger" and not event.get("event_id"):
                        continue
                    try:
                        self.pool.submit(handler, event)
                    except RuntimeError:
                        return
            finally:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                with self._proc_lock:
                    if proc in self._procs:
                        self._procs.remove(proc)

            if not self.stop.is_set():
                self.logger.warning("事件流 %s 已断开，3 秒后重连", key)
                self.stop.wait(3)

    # ---------- 对账 ----------

    def _reconcile_loop(self) -> None:
        if self.stop.wait(15):
            return
        while not self.stop.is_set():
            try:
                self.reconcile_once()
            except Exception:
                self.logger.exception("对账失败")
            self.stop.wait(max(60, self.config.poll_seconds))

    def reconcile_once(self) -> None:
        owners = self.store.owners
        if not owners:
            return

        self._rebuild_feishu_from_github()
        self._reconcile_approvals(owners)
        self._reconcile_blocked(owners)
        self._reconcile_closures()
        self._reconcile_overview(owners)

    def _rebuild_feishu_from_github(self) -> None:
        """本地 state.json 丢失时，从 GitHub 注释重建已发卡映射，防止重发。"""
        if self.store.feishu_records():
            return
        for item in self.collab.approval_items():
            pr = item.get("pr") or {}
            number = pr.get("number")
            for kv in self.collab.read_feishu_msg("pr", number):
                mid = kv.get("message_id") or ""
                if mid:
                    self.store.remember_feishu("pr", number, kv.get("sha") or "", mid, kv.get("kind") or "C1")
        for item in self.collab.blocked_issues():
            issue = item.get("issue") or {}
            number = issue.get("number")
            for kv in self.collab.read_feishu_msg("issue", number):
                mid = kv.get("message_id") or ""
                if mid:
                    self.store.remember_feishu("issue", number, "", mid, kv.get("kind") or "C2")

    def _reconcile_approvals(self, owners) -> None:
        for item in self.collab.approval_items():
            pr = item.get("pr") or {}
            number = pr.get("number")
            key = "pr:%s:%s" % (number, pr.get("headRefOid") or "")
            if self.store.is_notified(key):
                continue
            try:
                full = self.collab.pr_view(number)
            except Exception:
                full = pr
            head = full.get("headRefOid") or ""
            review = self.collab.latest_review(full)
            if not review:
                continue
            if (review.get("verdict") or "").upper() != "PASS":
                continue
            if (review.get("sha") or "").lower() != head.lower():
                continue
            card = cards.approval_card(
                full,
                item.get("issue") or {},
                review,
                warning="检测到待你终审的 PR。",
            )
            sent = 0
            for owner in owners:
                try:
                    message_id = self.lark.send_card(owner, card)
                    if message_id:
                        self.collab.write_feishu_msg("C1", "pr", number, head, message_id)
                        self.store.remember_feishu("pr", number, head, message_id, "C1")
                        sent += 1
                except Exception as exc:
                    self.logger.warning("推送审批卡失败：%s", exc)
            if sent:
                self.store.once(key)
                self.audit.write("system", "notify:approval", "PR #%s" % number)

    def _reconcile_blocked(self, owners) -> None:
        for item in self.collab.blocked_issues():
            issue = item.get("issue") or {}
            number = issue.get("number")
            kind = item.get("kind") or "blocked:needs-human"
            key = "issue:%s:%s" % (number, kind)
            if self.store.is_notified(key):
                continue
            card = cards.blocked_card(issue, kind)
            sent = 0
            for owner in owners:
                try:
                    message_id = self.lark.send_card(owner, card)
                    if message_id:
                        self.collab.write_feishu_msg("C2", "issue", number, "", message_id)
                        self.store.remember_feishu("issue", number, "", message_id, "C2")
                        sent += 1
                except Exception as exc:
                    self.logger.warning("推送裁决卡失败：%s", exc)
            if sent:
                self.store.once(key)
                self.audit.write("system", "notify:blocked", "Issue #%s" % number)

    def _reconcile_closures(self) -> None:
        """PR/Issue 已合并/关闭或 headRefOid 变更时，把旧卡刷灰，绝不写入人类批准结论。"""
        for record in self.store.feishu_records():
            message_id = record.get("message_id") or ""
            if not message_id:
                continue
            target = record.get("target") or "pr"
            number = record.get("number")
            sha = record.get("sha") or ""
            try:
                if target == "pr":
                    obj = self.collab.pr_view(number)
                    state = obj.get("state") or ""
                    head = obj.get("headRefOid") or ""
                    if state != "OPEN":
                        patch = cards.result_card(
                            "✅ 外部闭环（GitHub/CLI）",
                            "PR #%s 当前状态 %s，本卡已归档。请以 GitHub 为准。"
                            % (number, state),
                            True,
                            pr=number,
                        )
                    elif sha and head and sha.lower() != head.lower():
                        patch = cards.result_card(
                            "⚠️ PR 已有新提交",
                            "旧卡绑定 SHA %s，当前为 %s，本卡已作废，请刷新。"
                            % (sha[:7], head[:7]),
                            False,
                            pr=number,
                        )
                    else:
                        continue
                else:
                    obj = self.collab.issue_view(number)
                    state = obj.get("state") or ""
                    if state == "OPEN":
                        continue
                    patch = cards.result_card(
                        "✅ 外部闭环（GitHub/CLI）",
                        "Issue #%s 当前状态 %s，本卡已归档。" % (number, state),
                        True,
                    )
                self.lark.patch_card(message_id, patch)
                self.audit.write("system", "patch:closed", "%s #%s" % (target, number))
            except Exception as exc:
                self.logger.warning("对账刷灰失败（%s #%s）：%s", target, number, exc)

    def _overview_data(self):
        counts = {
            "ready": 0,
            "in-progress": 0,
            "review": 0,
            "ready-to-merge": 0,
            "rework": 0,
            "draft": 0,
            "blocked": 0,
        }
        for issue in self.collab.open_issues():
            labels = self.collab.label_names(issue)
            for key in ("ready", "in-progress", "review", "ready-to-merge", "rework", "draft"):
                if ("status:" + key) in labels:
                    counts[key] += 1
            if "blocked:needs-human" in labels or "blocked:needs-design" in labels:
                counts["blocked"] += 1
        pending = [item.get("pr") or {} for item in self.collab.approval_items()]
        return counts, pending

    def _reconcile_overview(self, owners) -> None:
        counts, pending = self._overview_data()
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S")
        card = cards.overview_card(counts, pending, updated_at=updated_at)
        digest = hashlib.sha256(
            json.dumps(card, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        state = self.store.overview_state()
        message_id = state.get("message_id") or ""
        first_sent = state.get("first_sent") or 0
        if state.get("hash") == digest and message_id:
            return  # 内容无变化，不调用 PATCH

        now = time.time()
        if not message_id or now - first_sent >= 13 * 86400:
            if message_id:
                try:
                    self.lark.patch_card(
                        message_id,
                        cards.overview_card(counts, pending, updated_at=updated_at, archived=True),
                    )
                except Exception as exc:
                    self.logger.warning("归档旧总览卡失败：%s", exc)
            for owner in owners:
                try:
                    new_mid = self.lark.send_card(owner, card)
                    if new_mid:
                        message_id = new_mid
                        first_sent = now
                        break
                except Exception as exc:
                    self.logger.warning("发送总览卡失败：%s", exc)
        else:
            try:
                self.lark.patch_card(message_id, card)
            except Exception as exc:
                self.logger.warning("更新总览卡失败：%s", exc)
        self.store.save_overview_state(
            {"hash": digest, "message_id": message_id, "first_sent": first_sent}
        )

    # ---------- 生命周期 ----------

    def run(self) -> int:
        if not self.acquire_lock():
            self.logger.error("已有实例在运行（锁：%s），拒绝重复启动。", self.config.lock_path)
            print("已有实例在运行，拒绝重复启动。")
            return 3

        fatal, notes = self.preflight()
        for line in notes:
            self.logger.info("%s", line)
        if fatal:
            for line in fatal:
                self.logger.error("%s", line)
                print("✖ " + line)
            return 2

        print("=" * 64)
        print("Collab 审批官已通过预检")
        print("仓库：%s" % self.config.repo)
        print("飞书配置：%s" % self.config.lark_config_dir)
        print("")
        if self.store.owners:
            print("已绑定主人：%s" % ", ".join(self.store.owners))
        else:
            code = self.store.bind_code
            print("绑定码 BIND_CODE: %s" % code)
            print("尚未绑定主人：在飞书私聊机器人发送 /bind %s" % code)
            self.logger.info("BIND_CODE=%s", code)
        print("=" * 64)
        if self.store.owners:
            self.logger.info("owners=%s", ",".join(self.store.owners))

        self.start_consumers()
        try:
            while not self.stop.wait(1):
                pass
        finally:
            self.shutdown()
        return 0

    def shutdown(self) -> None:
        self.stop.set()
        with self._proc_lock:
            procs = list(self._procs)
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.pool.shutdown(wait=False)

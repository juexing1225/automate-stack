"""与 collab.py / gh / git 的对接。业务校验尽量复用仓库里的唯一内核。"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from .executor import redact, strip_ansi

REVIEW_RE = re.compile(r"<!--\s*collab:review\s+(.*?)-->", re.S)
FEISHU_MSG_RE = re.compile(r"<!--\s*collab:feishu-msg\s+(.*?)-->", re.S)
ISSUE_RE = re.compile(r"collab:issue\s*[=:]?\s*(\d+)")


def _kv(text: str) -> dict:
    result = {}
    for token in text.split():
        if "=" in token:
            key, value = token.split("=", 1)
            result[key] = value
    return result


def _section(text: str, title: str) -> str:
    """提取 Markdown 报告的某个 `## 标题` 小节原文。"""
    match = re.search(
        r"^##\s*" + re.escape(title) + r"\s*\n(.*?)(?=^##\s|\Z)",
        text,
        re.M | re.S,
    )
    return match.group(1).strip() if match else ""


def parse_review_report(body: str) -> dict:
    """从 collab:review 报告正文提取门禁结果、逐项验收（A1..An）、视角补充三小项。"""
    result = {"gate": "", "acceptance": [], "blindspots": {}}
    gate_section = _section(body, "门禁复核")
    match = re.search(r"[-*]\s*结果\s*[:：]\s*(\S+)", gate_section)
    if match:
        result["gate"] = match.group(1).strip()
    for line in (_section(body, "逐项证据") or "").splitlines():
        line = line.strip()
        if line.startswith("-"):
            item = line.lstrip("-").strip()
            if item:
                result["acceptance"].append(item)
    perspective = _section(body, "视角补充 / 需求盲点") or _section(body, "视角补充")
    for key in ("隐含假设", "未覆盖边界", "关联影响"):
        match = re.search(re.escape(key) + r"\s*[:：]\s*(\S.*)", perspective)
        if match and match.group(1).strip():
            result["blindspots"][key] = match.group(1).strip()
    return result


@dataclass
class Result:
    ok: bool
    title: str
    detail: str = ""
    retry_sha: Optional[str] = None
    warning: bool = False


class Collab:
    def __init__(self, config) -> None:
        self.config = config

    def _run(self, args, cwd=None, timeout: int = 180, redact_output: bool = True):
        try:
            proc = subprocess.run(
                list(args),
                cwd=str(cwd or self.config.repo),
                text=True,
                capture_output=True,
                timeout=timeout,
                env=self.config.child_env(),
            )
        except FileNotFoundError:
            return 127, "找不到命令：%s" % args[0]
        except subprocess.TimeoutExpired:
            return 124, "命令超时：%s" % " ".join(args)
        output = strip_ansi((proc.stdout or "") + (proc.stderr or ""))
        if redact_output:
            output = redact(output)
        return proc.returncode, output.strip()

    def _gh(self, args, timeout: int = 90, redact_output: bool = True):
        return self._run(
            ["gh"] + list(args), timeout=timeout, redact_output=redact_output
        )

    def _gh_json(self, args, timeout: int = 90):
        # 先解析原始 JSON，再做展示层脱敏；避免脱敏破坏 JSON 结构。
        rc, output = self._gh(args, timeout=timeout, redact_output=False)
        if rc != 0:
            raise RuntimeError(output or "gh 命令失败")
        try:
            return json.loads(output)
        except ValueError as exc:
            raise RuntimeError("gh 返回的不是 JSON：%s" % output[:300]) from exc

    def run_collab(self, args, timeout: int = 240):
        if not self.config.collab_py.exists():
            return 127, "仓库里没有 scripts/collab.py：%s" % self.config.repo
        return self._run(
            [sys.executable, str(self.config.collab_py)] + list(args),
            timeout=timeout,
        )

    def gh_auth_status(self):
        return self._run(["gh", "auth", "status"], timeout=30)

    # ---------- 查询 ----------

    def repo_info(self) -> dict:
        rc, output = self._run(["git", "status", "--porcelain=v1", "-b"], timeout=30)
        branch_line = ""
        dirty = []
        if rc == 0:
            lines = output.splitlines()
            if lines:
                branch_line = lines[0]
                dirty = lines[1:]
        rc2, remote = self._run(["git", "remote", "get-url", "origin"], timeout=30)
        rc3, last = self._run(["git", "log", "-1", "--oneline"], timeout=30)
        return {
            "path": str(self.config.repo),
            "is_repo": rc == 0,
            "branch": branch_line,
            "dirty": dirty,
            "remote": remote if rc2 == 0 else "",
            "last_commit": last if rc3 == 0 else "",
        }

    def open_prs(self) -> list:
        fields = (
            "number,title,state,headRefOid,isDraft,labels,author,updatedAt,url,body"
        )
        try:
            return self._gh_json(
                ["pr", "list", "--state", "open", "--limit", "30", "--json", fields]
            )
        except RuntimeError:
            return []

    def open_issues(self) -> list:
        fields = "number,title,labels,updatedAt,url,state"
        try:
            return self._gh_json(
                ["issue", "list", "--state", "open", "--limit", "50", "--json", fields]
            )
        except RuntimeError:
            return []

    def pr_view(self, number: int) -> dict:
        fields = (
            "number,title,state,headRefOid,url,labels,author,body,mergeable,"
            "mergeStateStatus,reviewDecision,changedFiles,additions,deletions,comments"
        )
        return self._gh_json(["pr", "view", str(number), "--json", fields])

    def issue_view(self, number: int) -> dict:
        return self._gh_json(
            [
                "issue", "view", str(number),
                "--json", "number,title,state,labels,url,body,comments",
            ]
        )

    @staticmethod
    def issue_number(pr: dict) -> Optional[int]:
        match = ISSUE_RE.search(pr.get("body") or "")
        return int(match.group(1)) if match else None

    @staticmethod
    def latest_review(pr: dict) -> dict:
        best = {}
        last_body = ""
        for comment in pr.get("comments") or []:
            body = comment.get("body") or ""
            for match in REVIEW_RE.finditer(body):
                best = _kv(match.group(1))
                last_body = body
        if best:
            report = parse_review_report(last_body)
            best["gate"] = report["gate"]
            best["acceptance"] = report["acceptance"]
            best["blindspots"] = report["blindspots"]
        return best

    @staticmethod
    def label_names(obj: dict) -> list:
        return [item.get("name", "") for item in (obj.get("labels") or [])]

    def repo_slug(self) -> str:
        rc, output = self._run(["git", "remote", "get-url", "origin"], timeout=15)
        if rc != 0:
            return ""
        match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", output.strip())
        return match.group(1) if match else ""

    @staticmethod
    def rework_round(pr: dict) -> int:
        return len(
            [
                comment
                for comment in (pr.get("comments") or [])
                if (
                    (match := REVIEW_RE.search(comment.get("body") or ""))
                    and (_kv(match.group(1)).get("verdict") or "").upper() == "REWORK"
                )
            ]
        ) + 1

    def approval_items(self) -> list:
        items = []
        for pr in self.open_prs():
            issue_no = self.issue_number(pr)
            issue = {}
            if issue_no:
                try:
                    issue = self.issue_view(issue_no)
                except RuntimeError:
                    issue = {}
            labels = self.label_names(issue) if issue else []
            if "review:agent-passed" in labels:
                items.append({"pr": pr, "issue": issue, "labels": labels})
        return items

    def blocked_issues(self) -> list:
        items = []
        for issue in self.open_issues():
            labels = self.label_names(issue)
            for name in ("blocked:needs-human", "blocked:needs-design"):
                if name in labels:
                    items.append({"issue": issue, "kind": name})
                    break
        return items

    # ---------- 人类动作 ----------

    def _check_expected_sha(self, number: int, expected_sha: str):
        pr = self.pr_view(number)
        if pr.get("state") != "OPEN":
            return pr, Result(False, "PR 不是打开状态", "当前状态：%s" % pr.get("state"))
        current = pr.get("headRefOid") or ""
        if expected_sha and current != expected_sha:
            return pr, Result(
                False,
                "PR 已有新提交",
                "卡片绑定的 SHA 是 %s，当前是 %s。请刷新卡片后重新确认。"
                % (expected_sha[:7], current[:7]),
            )
        return pr, None

    def accept_only(self, number: int, expected_sha: str = "") -> Result:
        if not expected_sha:
            return Result(
                False,
                "卡片缺少 SHA",
                "卡片没有绑定 head SHA，无法强绑定终审对象；请重新发送 /card %s。"
                % number,
            )
        _, error = self._check_expected_sha(number, expected_sha)
        if error:
            return error
        rc, output = self.run_collab(
            ["accept", str(number), "--member", self.config.member, "--sha", expected_sha]
        )
        if rc != 0:
            return Result(False, "终审验收未通过", output)
        return Result(True, "✅ 已验收（暂未合并）", output)

    def accept_and_merge(self, number: int, expected_sha: str = "") -> Result:
        if not expected_sha:
            return Result(
                False,
                "卡片缺少 SHA",
                "卡片没有绑定 head SHA，无法强绑定终审与合并对象；请重新发送 /card %s。"
                % number,
            )
        pr, error = self._check_expected_sha(number, expected_sha)
        if error:
            return error
        head = expected_sha

        rc, output = self.run_collab(
            ["accept", str(number), "--member", self.config.member, "--sha", expected_sha]
        )
        if rc != 0:
            return Result(False, "终审验收未通过", output)

        # accept 期间仍可能进新提交；合并前再读一次，避免把未确认的 SHA 合进去。
        latest = self.pr_view(number)
        latest_head = latest.get("headRefOid") or ""
        if latest_head != expected_sha:
            return Result(
                False,
                "已验收，但 PR 又有新提交，未合并",
                "验收时 SHA 是 %s，当前是 %s。请刷新卡片重新确认。"
                % (expected_sha[:7], latest_head[:7]),
            )

        rc2, output2 = self._gh(
            ["pr", "merge", str(number), "--squash", "--match-head-commit", expected_sha],
            timeout=180,
        )
        if rc2 != 0:
            detail = (output + "\n\n" + output2).strip()
            return Result(
                False,
                "✅ 已验收，⚠️ 合并未完成",
                detail,
                retry_sha=head,
            )
        detail = (output + "\n\n" + output2).strip()
        return Result(True, "✅ 已通过并合并", detail)

    def retry_merge(self, number: int, sha: str) -> Result:
        pr = self.pr_view(number)
        if pr.get("state") != "OPEN":
            return Result(
                False, "PR 不是打开状态，无法重试合并", "当前状态：%s" % pr.get("state")
            )
        if (pr.get("headRefOid") or "") != sha:
            return Result(
                False,
                "PR 已有新提交，不能按旧 SHA 合并",
                "当前 SHA：%s" % pr.get("headRefOid"),
            )
        rc, output = self._gh(
            ["pr", "merge", str(number), "--squash", "--match-head-commit", sha],
            timeout=180,
        )
        if rc != 0:
            return Result(False, "⚠️ 合并仍未完成", output, retry_sha=sha)
        return Result(True, "✅ 重试合并成功", output)

    def rework(self, number: int, reason: str, expected_sha: str = "") -> Result:
        pr, error = self._check_expected_sha(number, expected_sha)
        if error:
            return error
        head = pr.get("headRefOid") or ""
        issue_no = self.issue_number(pr)
        repo = self.repo_slug()
        decision_id = "feishu-%s-%s-%s" % (
            number,
            int(time.time()),
            uuid.uuid4().hex[:6],
        )
        comment = (
            "<!-- collab:review pr=%s issue=%s repo=%s sha=%s round=%s "
            "member=human family=human verdict=REWORK via=feishu "
            "decision_id=%s -->\n"
            "## 人工终审：打回返工\n\n%s\n\n— Collab 审批官（飞书）\n"
        ) % (
            number,
            issue_no or "",
            repo,
            head,
            self.rework_round(pr),
            decision_id,
            reason.strip(),
        )
        rc, output = self._gh(["pr", "comment", str(number), "--body", comment])
        if rc != 0:
            return Result(False, "写入返工评论失败", output)

        if not issue_no:
            detail = (
                output
                + "\n\n未找到关联工单（PR 缺少 collab:issue 标记），"
                "工单未切到 status:rework，需要人工跟进。"
            )
            return Result(False, "已写返工评论，但未找到关联工单", detail, warning=True)

        done = []
        failed = []
        rc2, out2 = self._gh(
            ["issue", "edit", str(issue_no), "--add-label", "status:rework"]
        )
        target = done if rc2 == 0 else failed
        target.append(
            "工单 #%s 加 status:rework：%s"
            % (issue_no, "成功" if rc2 == 0 else "失败（%s）" % out2)
        )
        for label in ("status:review", "status:ready-to-merge", "review:agent-passed"):
            rc3, out3 = self._gh(
                ["issue", "edit", str(issue_no), "--remove-label", label]
            )
            bucket = done if rc3 == 0 else failed
            bucket.append(
                "移除 %s：%s" % (label, "成功" if rc3 == 0 else "失败（%s）" % out3)
            )

        detail_lines = [output, ""]
        if done:
            detail_lines.append("已完成：")
            detail_lines.extend("- " + item for item in done)
        if failed:
            detail_lines.append("失败：")
            detail_lines.extend("- " + item for item in failed)
        detail = "\n".join(detail_lines)

        if failed:
            return Result(
                False, "⚠️ 评论已写，但工单标签未完全切换", detail, warning=True
            )
        return Result(True, "🔁 已打回返工", detail)

    def pack(self, kind: str, number: int) -> Result:
        rc, output = self.run_collab(["pack", kind, str(number)])
        if rc != 0:
            return Result(False, "导出任务包失败", output)
        return Result(True, "📦 任务包已导出", output)

    # ---------- 飞书消息追踪（不可见注释，跨重启重建发卡映射） ----------

    def write_feishu_msg(self, kind: str, target: str, number: int, sha: str, message_id: str) -> bool:
        """在 PR / Issue 写一条不可见的 collab:feishu-msg 注释，记录已发出的卡片。"""
        repo = self.repo_slug()
        marker = (
            "<!-- collab:feishu-msg kind=%s repo=%s target=%s number=%s sha=%s "
            "message_id=%s -->"
            % (kind, repo, target, number, sha, message_id)
        )
        sub = "pr" if target == "pr" else "issue"
        rc, _ = self._gh([sub, "comment", str(number), "--body", marker])
        return rc == 0

    def read_feishu_msg(self, target: str, number: int) -> list:
        """读取某 PR / Issue 上所有 collab:feishu-msg 注释，返回键值对列表。"""
        try:
            if target == "pr":
                obj = self.pr_view(number)
            else:
                obj = self.issue_view(number)
        except RuntimeError:
            return []
        found = []
        for comment in obj.get("comments") or []:
            body = comment.get("body") or ""
            for match in FEISHU_MSG_RE.finditer(body):
                found.append(_kv(match.group(1)))
        return found

    # ---------- 看板 ----------

    def status_markdown(self) -> str:
        repo = self.repo_info()
        prs = self.open_prs()
        issues = self.open_issues()

        counts = {
            "ready": 0,
            "in-progress": 0,
            "review": 0,
            "ready-to-merge": 0,
            "rework": 0,
            "draft": 0,
            "blocked": 0,
            "human": 0,
        }
        for issue in issues:
            labels = self.label_names(issue)
            for key in (
                "ready", "in-progress", "review",
                "ready-to-merge", "rework", "draft",
            ):
                if ("status:" + key) in labels:
                    counts[key] += 1
            if (
                "review:agent-passed" in labels
                or "blocked:needs-human" in labels
                or "blocked:needs-design" in labels
            ):
                counts["human"] += 1
            if (
                "blocked:needs-human" in labels
                or "blocked:needs-design" in labels
            ):
                counts["blocked"] += 1

        lines = []
        lines.append("**Collab 审批官 · 协作看板**")
        lines.append("")
        lines.append("仓库：`%s`" % (repo["remote"] or repo["path"]))
        lines.append(
            "本地：`%s` %s"
            % (
                repo["branch"] or "未知分支",
                "工作区干净"
                if not repo["dirty"]
                else "有 %d 处未提交改动" % len(repo["dirty"]),
            )
        )
        if repo["last_commit"]:
            lines.append("最近提交：`%s`" % repo["last_commit"])
        lines.append("")
        lines.append(
            "待领取 %d · 开发中 %d · 待审 %d · 待合并 %d · 返工 %d · 草稿 %d · 阻塞 %d"
            % (
                counts["ready"],
                counts["in-progress"],
                counts["review"],
                counts["ready-to-merge"],
                counts["rework"],
                counts["draft"],
                counts["blocked"],
            )
        )
        lines.append("")

        if prs:
            lines.append("**打开的 PR（%d）**" % len(prs))
            for pr in prs[:12]:
                issue_no = self.issue_number(pr)
                issue_labels = []
                if issue_no:
                    try:
                        issue_labels = self.label_names(self.issue_view(issue_no))
                    except RuntimeError:
                        issue_labels = []
                flag = (
                    " 🟠待你终审"
                    if "review:agent-passed" in issue_labels
                    else ""
                )
                lines.append(
                    "- PR #%s %s · `%s`%s\n  %s"
                    % (
                        pr.get("number"),
                        pr.get("title", ""),
                        (pr.get("headRefOid") or "")[:7],
                        flag,
                        pr.get("url", ""),
                    )
                )
            lines.append("")

        if counts["human"]:
            lines.append(
                "**需要你拍板**：%d 项。发送 `/card <PR号>` 生成审批卡。"
                % counts["human"]
            )
        else:
            lines.append("当前没有需要你拍板的条目。")
        lines.append("")
        lines.append(
            "可用：`/status` `/prs` `/card 2` `/approve 2` `/help`"
        )
        return "\n".join(lines)

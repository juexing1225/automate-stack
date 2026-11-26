"""collab.py 的测试：纯函数 + 真实临时 Git 仓库 + 假 gh。

运行：
    cd templates/github && python3 -m unittest discover -s tests -v

说明：
- 这里验证的是工具机械行为，不代表真实 GitHub 仓库已跑通。
- `gh` 用本地假脚本替代，只验证调用顺序、参数与正文内容；不联网。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "scripts" / "collab.py"
sys.path.insert(0, str(ROOT / "scripts"))
import collab  # noqa: E402


def _mkdir(path: Path):
    """mkdir -p，容忍某些宿主 Python 沙盒 shim 对 exist_ok 的破坏。"""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        pass


def git(repo, *args, check=True):
    p = subprocess.run(["git", *args], cwd=str(repo), text=True, capture_output=True)
    if check and p.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败：{p.stderr}\n{p.stdout}")
    return p.stdout.strip()


def run_tool(repo, *args, env=None, timeout=120):
    real_env = os.environ.copy()
    real_env.update(env or {})
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        cwd=str(repo),
        text=True,
        capture_output=True,
        env=real_env,
        timeout=timeout,
    )


FAKE_GH = r'''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path

args = sys.argv[1:]
state_path = Path(os.environ["FAKE_GH_STATE"])
state = json.loads(state_path.read_text())
log_path = Path(os.environ["FAKE_GH_LOG"])

def log(stdin=""):
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"args": args, "stdin": stdin}, ensure_ascii=False) + "\n")

def need_stdin():
    return (args[:2] in (["issue", "comment"], ["issue", "edit"], ["pr", "create"], ["pr", "edit"], ["pr", "comment"]))

stdin = sys.stdin.read() if need_stdin() and not sys.stdin.isatty() else ""
log(stdin)

if args[:2] == ["api", "user"]:
    print("fake-gh-user")
    raise SystemExit(0)

if args[:2] == ["label", "list"]:
    print(json.dumps([{"name": n} for n, _, _ in [
        ("status:ready", "", ""), ("status:in-progress", "", ""), ("status:review", "", ""),
        ("status:rework", "", ""), ("review:agent-passed", "", ""), ("status:ready-to-merge", "", ""),
        ("blocked:needs-design", "", ""), ("blocked:external", "", ""), ("risk:high", "", ""), ("canceled", "", ""),
    ]]))
    raise SystemExit(0)

if args[:2] == ["issue", "list"]:
    label = None
    if "--label" in args:
        label = args[args.index("--label") + 1]
    out = []
    for n, issue in state.get("issues", {}).items():
        if issue.get("state") != "OPEN":
            continue
        names = [l.get("name") for l in (issue.get("labels") or [])]
        if label and label not in names:
            continue
        out.append(issue)
    print(json.dumps(out))
    raise SystemExit(0)

if args[:2] == ["pr", "list"]:
    print(json.dumps(state.get("prs", [])))
    raise SystemExit(0)

if args[:2] == ["issue", "view"]:
    n = args[2]
    issue = state.get("issues", {}).get(n)
    if not issue:
        print(f"issue #{n} not found", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(issue))
    raise SystemExit(0)

if args[:2] == ["issue", "edit"]:
    raise SystemExit(0)

if args[:2] == ["issue", "comment"]:
    n = args[2]
    issue = state.get("issues", {}).get(n)
    if issue is not None:
        issue.setdefault("comments", []).append({"body": stdin})
        state_path.write_text(json.dumps(state, ensure_ascii=False))
    raise SystemExit(0)

if args[:2] == ["pr", "view"]:
    pr = state.get("pr")
    if not pr:
        print("no pull requests found for branch", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps(pr))
    raise SystemExit(0)

if args[:2] == ["pr", "create"]:
    pr = dict(state.get("pr") or {})
    pr.update({"number": 1, "url": "https://example.test/pull/1", "state": "OPEN", "body": stdin})
    state["pr"] = pr
    state_path.write_text(json.dumps(state, ensure_ascii=False))
    print(pr["url"])
    raise SystemExit(0)

if args[:2] == ["pr", "edit"]:
    raise SystemExit(0)

if args[:2] == ["pr", "comment"]:
    n = args[2]
    pr = state.get("pr")
    if pr is not None and pr.get("number") == int(n):
        pr.setdefault("comments", []).append({"body": stdin})
        state_path.write_text(json.dumps(state, ensure_ascii=False))
    raise SystemExit(0)

print(f"fake gh: unhandled {args}", file=sys.stderr)
raise SystemExit(2)
'''


class RepoFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="collab-test-"))
        self.repo = self.tmp / "repo"
        _mkdir(self.repo)
        shutil.copytree(ROOT / "scripts", self.repo / "scripts")
        _mkdir(self.repo / ".collab")
        _mkdir(self.repo / "docs")
        (self.repo / "docs" / "ARCHITECTURE.md").write_text("# Arch\n\nstable\n", encoding="utf-8")
        (self.repo / "check.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
        config = {
            "schema": 2,
            "default_branch": "main",
            "worktree_root": ".collab/worktrees",
            "require_cross_family_review": True,
            "trusted_github_logins": ["fake-gh-user"],
            "max_wip_per_member": 1,
            "max_rework_rounds": 3,
            "max_attempts_per_target": 2,
            "review_lease_minutes": 30,
            "active_session_minutes": 30,
            "families": {
                "antigravity": "gemini",
                "gemini": "gemini",
                "dsh": "deepseek",
                "deepseek": "deepseek",
                "dsh-01": "deepseek",
                "dsh-02": "deepseek",
                "baizhi": "baizhi",
                "ohmyagent": "baizhi",
                "workbuddy": "workbuddy",
                "gpt": "openai",
                "human": "human",
                "alice": "alice",
                "bob": "bob",
                "charlie": "charlie",
            },
            "protected_files": ["docs/ARCHITECTURE.md", "scripts/collab.py"],
            "review_highlight_globs": ["src/core/**"],
            "secret_globs": [".env", "*.env", "**/*.pem"],
            "secret_exclude": ["**/fixtures/**"],
            "gate": {
                "fast": ["python3 check.py"],
                "full": ["python3 check.py"],
                "timeout_seconds": 60,
                "submit_profile": "fast",
                "review_profile": "fast",
            },
        }
        (self.repo / ".collab" / "config.json").write_text(json.dumps(config), encoding="utf-8")
        git(self.repo, "init", "-b", "main", "-q")
        git(self.repo, "config", "user.name", "Test User")
        git(self.repo, "config", "user.email", "test@example.com")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

        self.gh = self.tmp / "fake-gh"
        self.gh.write_text(FAKE_GH, encoding="utf-8")
        self.gh.chmod(0o755)
        self.gh_state = self.tmp / "gh-state.json"
        self.gh_log = self.tmp / "gh-log.jsonl"
        self.gh_log.write_text("", encoding="utf-8")
        self.env = {
            "COLLAB_GH": str(self.gh),
            "FAKE_GH_STATE": str(self.gh_state),
            "FAKE_GH_LOG": str(self.gh_log),
        }
        self.write_state({"issues": {}, "pr": None})

    def tearDown(self):
        subprocess.run(["git", "worktree", "prune"], cwd=str(self.repo), capture_output=True)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_state(self, data):
        self.gh_state.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def read_log(self):
        lines = self.gh_log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    def issue(self, number=1, body="## 目标\n\n做点事\n\n## 依赖\n无\n\n## 验收项\n- A1：可用\n- A2：有证据\n", labels=None, state="OPEN"):
        return {
            "number": number,
            "title": f"Test issue {number}",
            "body": body,
            "state": state,
            "url": f"https://example.test/issues/{number}",
            "labels": [{"name": name} for name in (labels if labels is not None else ["status:ready"])],
        }

    def head(self):
        return git(self.repo, "rev-parse", "HEAD")

    def make_origin(self):
        bare = self.tmp / "origin.git"
        git(self.tmp, "init", "--bare", "-q", str(bare))
        # B1：裸库默认 HEAD 指向 master，clone 后无 main 分支；显式把 HEAD 指到 main
        git(bare, "symbolic-ref", "HEAD", "refs/heads/main")
        git(self.repo, "remote", "add", "origin", str(bare))
        git(self.repo, "push", "-u", "origin", "main", "-q")
        return bare

    def submitted_pr_state(self, head, authors="alice", families="alice", issue_labels=None,
                           comments=None, author_login="fake-gh-user", is_cross=False, pr_number=1):
        if issue_labels is None:
            issue_labels = ["status:review"]
        body = f"<!-- collab:authors={authors} -->\n<!-- collab:families={families} -->\n<!-- collab:issue=1 -->"
        pr = {
            "number": pr_number,
            "url": f"https://example.test/pull/{pr_number}",
            "headRefOid": head,
            "headRefName": "work/issue-1",
            "baseRefName": "main",
            "state": "OPEN",
            "body": body,
            "author": {"login": author_login},
            "isCrossRepository": is_cross,
        }
        if comments is not None:
            pr["comments"] = comments
        self.write_state({"issues": {"1": self.issue(labels=issue_labels)}, "pr": pr, "prs": [pr]})
        return pr

    def owned_issue(self, number, label, member, body=None, extra_labels=None):
        labels = [label] + (extra_labels or [])
        issue = self.issue(number=number, body=body or "## 目标\nx\n\n## 依赖\n无\n\n## 验收项\n- A1：可用\n", labels=labels)
        issue["comments"] = [
            {"body": f"<!-- collab:claim issue={number} member={member} family=x nonce=abc -->\n"}
        ]
        return issue

    def _prepare_branch(self):
        self.make_origin()
        git(self.repo, "checkout", "-q", "-b", "work/issue-1")
        _mkdir(self.repo / "src")
        (self.repo / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat: app")
        run_tool(self.repo, "doctor", "--fix")
        base = git(self.repo, "rev-parse", "main")
        _mkdir(self.repo / ".collab")
        (self.repo / ".collab" / "task.md").write_text(
            f"# Issue #1: Test issue 1\n\n<!-- collab:issue=1 -->\n<!-- collab:base={base} -->\n",
            encoding="utf-8",
        )
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        return self.head()


class TestPureFunctions(unittest.TestCase):
    def test_parse_deps(self):
        self.assertEqual(collab.parse_deps("## 依赖\n无\n"), [])
        self.assertEqual(collab.parse_deps("## 依赖\n#12, #13\n"), [12, 13])
        self.assertEqual(collab.parse_deps("## 依赖\n<!-- #9 -->\n#12\n"), [12])
        self.assertIsNone(collab.parse_deps("## 输入\n#12\n"))
        self.assertEqual(collab.parse_deps("## 依赖\n```\n#12\n```\n## 验收项\nA1"), [12])

    def test_parse_acceptance_and_authors(self):
        body = "## 验收项\n- A1：x\n- A2：y\n- A1：重复\n"
        self.assertEqual(collab.parse_acceptance(body), ["A1", "A2"])
        pr = "<!-- collab:authors=alice,bob -->"
        self.assertEqual(collab.parse_authors(pr), ["alice", "bob"])
        fallback = "## 成果作者\n- member：alice\n- member: bob\n"
        self.assertEqual(collab.parse_authors(fallback), ["alice", "bob"])

    def test_glob_and_receipt(self):
        self.assertTrue(collab.match_any("src/core/a.py", ["src/core/**"]))
        self.assertTrue(collab.match_any("src/core", ["src/core/**"]))
        self.assertFalse(collab.match_any("src/other/a.py", ["src/core/**"]))
        good = {"head_sha": "a" * 40, "ok": True, "dirty": False, "protected_ok": True, "secrets_ok": True}
        self.assertTrue(collab.receipt_ok(good))
        self.assertFalse(collab.receipt_ok({**good, "dirty": True}))
        self.assertFalse(collab.receipt_ok({**good, "protected_ok": False}))

    def test_report_conclusion(self):
        cases = {
            "## 结论\n\nPASS\n\n> 说明\n": (True, "PASS"),
            "## 结论\n\n结论：REWORK\n": (True, "REWORK"),
            "## 结论\n\n- 结论：pass\n": (True, "PASS"),
            "## 结论\n\nPASS / REWORK\n": (True, "PASS / REWORK"),
            "## 验收项\nA1": (False, ""),
        }
        for text, expected in cases.items():
            self.assertEqual(collab.parse_report_conclusion(text), expected, text)


class TestGate(RepoFixture):
    def test_gate_passes_and_writes_receipt(self):
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        receipt_path = self.repo / ".git" / "collab" / "receipts" / f"{self.head()}.fast.author.json"
        self.assertTrue(receipt_path.exists(), p.stdout)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["head_sha"], self.head())
        self.assertFalse(receipt["dirty"])
        self.assertEqual(receipt["steps"][0]["exit"], 0)

    def test_gate_blocks_config_self_unprotect(self):
        cfg_path = self.repo / ".collab" / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["protected_files"] = []
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "tamper config protection")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("受保护文件", p.stdout)
        self.assertIn(".collab/config.json", p.stdout)

    def test_gate_blocks_protected_file(self):
        with (self.repo / "docs" / "ARCHITECTURE.md").open("a", encoding="utf-8") as f:
            f.write("\nagent changed this\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "touch protected")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 1)
        self.assertIn("受保护文件", p.stdout)

    def test_gate_blocks_secret_by_name(self):
        (self.repo / ".env").write_text("TOKEN=not-a-real-secret\n", encoding="utf-8")
        p = run_tool(self.repo, "gate", "--profile", "fast", "--dirty")
        self.assertEqual(p.returncode, 1)
        self.assertIn("疑似密钥", p.stdout)
        self.assertIn(".env", p.stdout)

    def test_gate_blocks_secret_by_content(self):
        (self.repo / "leak.txt").write_text("ghp_" + "a" * 36 + "\n", encoding="utf-8")
        p = run_tool(self.repo, "gate", "--profile", "fast", "--dirty")
        self.assertEqual(p.returncode, 1)
        self.assertIn("GitHub token", p.stdout)

    def test_gate_allows_fixture_secret_outside_scan(self):
        fixture = self.repo / "tests" / "fixtures"
        _mkdir(fixture)
        (fixture / "fake.pem").write_text("-----BEGIN PRIVATE KEY-----\nnot real\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "fixture")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_gate_requires_clean_tree(self):
        (self.repo / "notes.txt").write_text("draft\n", encoding="utf-8")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 1)
        self.assertIn("工作区不干净", p.stdout)

    def test_gate_marks_risk_files(self):
        _mkdir(self.repo / "src" / "core")
        (self.repo / "src" / "core" / "a.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "core change")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr)
        receipt = json.loads(
            (self.repo / ".git" / "collab" / "receipts" / f"{self.head()}.fast.author.json").read_text(encoding="utf-8")
        )
        self.assertIn("src/core/a.py", receipt["risk_files"])


class TestClaim(RepoFixture):
    def test_claim_creates_worktree_snapshot_and_labels(self):
        self.write_state({"issues": {"1": self.issue()}, "pr": None})
        p = run_tool(self.repo, "claim", "1", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        wt = self.repo / ".collab" / "worktrees" / "issue-1"
        self.assertTrue(wt.exists(), p.stdout)
        self.assertTrue((wt / ".collab" / "task.md").exists())
        snapshot = (wt / ".collab" / "task.md").read_text(encoding="utf-8")
        self.assertIn("collab:issue=1", snapshot)
        self.assertIn("collab:member=alice", snapshot)
        self.assertIn("## Issue 快照", snapshot)
        branches = git(self.repo, "branch", "--list", "work/issue-1")
        self.assertIn("work/issue-1", branches)
        calls = self.read_log()
        edits = [c for c in calls if c["args"][:2] == ["issue", "edit"]]
        self.assertTrue(edits)
        self.assertIn("status:in-progress", edits[0]["args"])
        comments = [c for c in calls if c["args"][:2] == ["issue", "comment"]]
        self.assertTrue(comments)

    def test_claim_blocks_open_dependency(self):
        body = "## 目标\nx\n\n## 依赖\n#2\n"
        self.write_state(
            {
                "issues": {
                    "1": self.issue(body=body),
                    "2": self.issue(number=2, body="## 目标\ny\n", labels=[], state="OPEN"),
                },
                "pr": None,
            }
        )
        p = run_tool(self.repo, "claim", "1", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("依赖未关闭", p.stderr)
        self.assertFalse((self.repo / ".collab" / "worktrees" / "issue-1").exists())

    def test_claim_rejects_self_review_marker(self):
        self.write_state({"issues": {"1": self.issue(labels=["status:ready", "blocked:needs-design"])}, "pr": None})
        p = run_tool(self.repo, "claim", "1", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("blocked:needs-design", p.stderr)


class TestMisc(RepoFixture):
    def test_doctor_fixes_exclude(self):
        p = run_tool(self.repo, "doctor", "--fix", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        exclude = self.repo / ".git" / "info" / "exclude"
        text = exclude.read_text(encoding="utf-8")
        for item in (".collab/worktrees/", ".collab/reviews/", ".collab/packs/", ".collab/task.md", ".collab/rework-latest.md"):
            self.assertIn(item, text.split(), text)
        # B0：绝不忽略 .collab/ 整目录，否则未跟踪的 config.json 会被隐藏漏提交
        self.assertNotIn(".collab/", text.split(), text)

    def test_pack_issue_exports_single_file(self):
        self.write_state({"issues": {"1": self.issue()}, "pr": None})
        p = run_tool(self.repo, "pack", "issue", "1", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        out = self.repo / ".collab" / "packs" / "collab-pack-issue-1.md"
        self.assertTrue(out.exists())
        text = out.read_text(encoding="utf-8")
        self.assertIn("Test issue 1", text)
        self.assertIn("不修改 `docs/ARCHITECTURE.md`", text)


class TestFlow(RepoFixture):
    def test_submit_then_independent_review(self):
        head = self._prepare_branch()
        self.write_state({"issues": {"1": self.issue(labels=["status:in-progress"])}, "pr": None})

        p = run_tool(self.repo, "submit", "--member", "alice", "--summary", "add app", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

        calls = self.read_log()
        create = [c for c in calls if c["args"][:2] == ["pr", "create"]]
        self.assertEqual(len(create), 1, calls)
        body = create[0]["stdin"]
        self.assertIn("Refs #1", body)
        self.assertIn("collab:authors=alice", body)
        self.assertIn(head, body)
        self.assertIn("--head", create[0]["args"])
        self.assertEqual(git(self.repo, "ls-remote", "origin", "refs/heads/work/issue-1").count("work/issue-1"), 1)
        stage_edits = [c for c in calls if c["args"][:2] == ["issue", "edit"] and "status:review" in c["args"]]
        self.assertTrue(stage_edits, calls)

        # 把 PR 快照写回假 gh，供 review 读取
        pr_body = body
        self.write_state(
            {
                "issues": {"1": self.issue(labels=["status:review"])},
                "pr": {
                    "number": 1,
                    "url": "https://example.test/pull/1",
                    "headRefOid": head,
                    "headRefName": "work/issue-1",
                    "baseRefName": "main",
                    "state": "OPEN",
                    "body": pr_body,
                    "author": {"login": "fake-gh-user"},
                },
            }
        )

        # 验收必须在默认分支的干净检出里跑
        git(self.repo, "checkout", "-q", "main")

        # 作者自审被拒
        p = run_tool(self.repo, "review", "1", "--member", "alice", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("不能验收自己", p.stderr)

        # 过期 SHA 被拒
        p = run_tool(self.repo, "review", "1", "--member", "bob", "--sha", "0" * 40, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("过期验收", p.stderr)

        # 独立验收准备
        p = run_tool(self.repo, "review", "1", "--member", "bob", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        report = self.repo / ".collab" / "reviews" / f"pr-1-{head[:7]}-draft.md"
        self.assertTrue(report.exists(), p.stdout)
        text = report.read_text(encoding="utf-8")
        self.assertIn("A1", text)
        self.assertIn(head, text)
        self.assertIn("PASS / REWORK", text)

        # 未填完被拒
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "bob", "--sha", head,
            "--file", str(report), "--verdict", "pass", env=self.env,
        )
        self.assertEqual(p.returncode, 1)
        self.assertIn("TODO", p.stderr)

        # 少写一条验收项被拒
        partial = text.replace("TODO（检查方法、实际结果、证据位置）", "已检查：运行 check.py 通过")
        partial = partial.replace("人工复核：TODO（填写后删除）", "人工复核：未参与创作")
        partial = partial.replace("TODO（填写后删除；确无盲点写：无新增盲点）", "无新增盲点")
        partial = partial.replace("PASS / REWORK", "PASS")
        partial = partial.replace("- A2：已检查：运行 check.py 通过\n", "")
        report.write_text(partial, encoding="utf-8")
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "bob", "--sha", head,
            "--file", str(report), "--verdict", "pass", env=self.env,
        )
        self.assertEqual(p.returncode, 1)
        self.assertIn("缺少验收项", p.stderr)

        # 填写完整报告
        text = text.replace("TODO（检查方法、实际结果、证据位置）", "已检查：运行 check.py 通过")
        text = text.replace("人工复核：TODO（填写后删除）", "人工复核：未参与创作")
        text = text.replace("TODO（填写后删除；确无盲点写：无新增盲点）", "无新增盲点")
        text = text.replace("PASS / REWORK", "PASS")
        report.write_text(text, encoding="utf-8")

        p = run_tool(
            self.repo, "review-submit", "1", "--member", "bob", "--sha", head,
            "--file", str(report), "--verdict", "pass", env=self.env,
        )
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        comments = [c for c in calls if c["args"][:2] == ["pr", "comment"]]
        self.assertTrue(comments, calls)
        self.assertIn("verdict=PASS", comments[-1]["stdin"])
        stage = [c for c in calls if c["args"][:2] == ["issue", "edit"] and "review:agent-passed" in c["args"]]
        self.assertTrue(stage, calls)
        for c in calls:
            if c["args"][:2] == ["issue", "edit"]:
                args_list = c["args"]
                for i, tok in enumerate(args_list[:-1]):
                    if tok == "--add-label":
                        self.assertNotEqual(args_list[i + 1], "status:ready-to-merge")

    def test_submit_refuses_stale_receipt(self):
        self.make_origin()
        git(self.repo, "checkout", "-q", "-b", "work/issue-1")
        (self.repo / "a.txt").write_text("one\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "one")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr)

        (self.repo / "a.txt").write_text("two\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "two")
        self.write_state({"issues": {"1": self.issue()}, "pr": None})
        p = run_tool(self.repo, "submit", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("没有找到", p.stderr)

    def test_gate_dynamic_merge_base_after_main_merge(self):
        self.make_origin()
        old_base = git(self.repo, "rev-parse", "main")
        git(self.repo, "checkout", "-q", "-b", "work/issue-1")
        _mkdir(self.repo / ".collab")
        (self.repo / ".collab" / "task.md").write_text(
            f"# Issue #1: Test\n\n<!-- collab:issue=1 -->\n<!-- collab:base={old_base} -->\n",
            encoding="utf-8",
        )
        (self.repo / "feature.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat")

        git(self.repo, "checkout", "-q", "main")
        with (self.repo / "docs" / "ARCHITECTURE.md").open("a", encoding="utf-8") as f:
            f.write("\nupstream approved change\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "upstream arch update")
        git(self.repo, "push", "-q", "origin", "main")

        git(self.repo, "checkout", "-q", "work/issue-1")
        git(self.repo, "merge", "-q", "--no-edit", "origin/main")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_review_rejects_stale_local_main(self):
        bare = self.make_origin()
        other = self.tmp / "other"
        git(self.tmp, "clone", "-q", str(bare), str(other))
        git(other, "config", "user.name", "Other")
        git(other, "config", "user.email", "other@example.com")
        (other / "upstream.txt").write_text("new\n", encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "upstream")
        git(other, "push", "-q", "origin", "main")

        head = self.head()
        self.write_state(
            {
                "issues": {"1": self.issue(labels=["status:review"])},
                "pr": {
                    "number": 1,
                    "url": "https://example.test/pull/1",
                    "headRefOid": head,
                    "headRefName": "work/issue-1",
                    "baseRefName": "main",
                    "state": "OPEN",
                    "body": "<!-- collab:authors=alice -->\n<!-- collab:issue=1 -->",
                    "author": {"login": "fake-gh-user"},
                },
            }
        )
        p = run_tool(self.repo, "review", "1", "--member", "bob", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("落后或偏离", p.stderr)

    def test_submit_preserves_historical_authors_and_clears_agent_passed(self):
        self._prepare_branch()
        self.write_state(
            {
                "issues": {"1": self.issue(labels=["status:in-progress", "review:agent-passed"])},
                "pr": {
                    "number": 1,
                    "url": "https://example.test/pull/1",
                    "state": "OPEN",
                    "body": "<!-- collab:authors=alice -->\n<!-- collab:issue=1 -->",
                },
            }
        )
        p = run_tool(self.repo, "submit", "--member", "charlie", "--summary", "rework fix", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        edits = [c for c in calls if c["args"][:2] == ["pr", "edit"]]
        self.assertTrue(edits, calls)
        self.assertIn("collab:authors=alice,charlie", edits[-1]["stdin"])
        label_edits = [c for c in calls if c["args"][:2] == ["issue", "edit"]]
        self.assertTrue(any("review:agent-passed" in c["args"] and "--remove-label" in c["args"] for c in label_edits))

    def test_claim_concurrent_conflict_rolls_back(self):
        issue_obj = self.issue()
        issue_obj["comments"] = [
            {"body": "**领取**：`bob`\n\n<!-- collab:claim-nonce=earlier1 -->\n<!-- collab:claim-member=bob -->\n"}
        ]
        self.write_state({"issues": {"1": issue_obj}, "pr": None})
        p = run_tool(self.repo, "claim", "1", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("并发领取冲突", p.stderr)
        self.assertFalse((self.repo / ".collab" / "worktrees" / "issue-1").exists())
        self.assertEqual(git(self.repo, "branch", "--list", "work/issue-1"), "")

    def test_review_submit_proxy_and_missing_perspective(self):
        head = self._prepare_branch()
        self.write_state(
            {
                "issues": {"1": self.issue(labels=["status:review"])},
                "pr": {
                    "number": 1,
                    "url": "https://example.test/pull/1",
                    "headRefOid": head,
                    "headRefName": "work/issue-1",
                    "baseRefName": "main",
                    "state": "OPEN",
                    "body": "<!-- collab:authors=alice -->\n<!-- collab:issue=1 -->",
                    "author": {"login": "fake-gh-user"},
                },
            }
        )
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "gpt", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        report = self.repo / ".collab" / "reviews" / f"pr-1-{head[:7]}-draft.md"
        text = report.read_text(encoding="utf-8")
        text = text.replace("TODO（检查方法、实际结果、证据位置）", "已检查：通过")
        text = text.replace("人工复核：TODO（填写后删除）", "人工复核：无参与")
        text = text.replace("PASS / REWORK", "PASS")

        no_persp = text.replace(
            "## 视角补充 / 需求盲点\n\n"
            "- 隐含假设：TODO（填写后删除；确无盲点写：无新增盲点）\n"
            "- 未覆盖边界：TODO（填写后删除；确无盲点写：无新增盲点）\n"
            "- 关联影响：TODO（填写后删除；确无盲点写：无新增盲点）\n\n",
            "",
        )
        report.write_text(no_persp, encoding="utf-8")
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "gpt", "--sha", head,
            "--file", str(report), "--verdict", "pass", "--proxy", env=self.env,
        )
        self.assertEqual(p.returncode, 1)
        self.assertIn("视角补充", p.stderr)

        filled = text.replace("TODO（填写后删除；确无盲点写：无新增盲点）", "无新增盲点")
        report.write_text(filled, encoding="utf-8")
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "gpt", "--sha", head,
            "--file", str(report), "--verdict", "pass", "--proxy", env=self.env,
        )
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        comments = [c for c in calls if c["args"][:2] == ["pr", "comment"]]
        self.assertIn("proxy=true", comments[-1]["stdin"])
        self.assertIn("代录声明", comments[-1]["stdin"])


class TestV23(RepoFixture):
    def test_review_rejects_same_family(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="dsh-01", families="deepseek")
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "dsh-02", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("同族审查", p.stderr)

    def test_review_cross_family_passes(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="dsh-01", families="deepseek")
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "antigravity", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertTrue((self.repo / ".collab" / "reviews" / f"pr-1-{head[:7]}-draft.md").exists())

    def test_review_rejects_unknown_member(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="alice", families="alice")
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "stranger", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("families", p.stderr)

    def test_review_rejects_cross_repo_pr(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="alice", families="alice", is_cross=True)
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "antigravity", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("外部 Fork", p.stderr)

    def test_accept_rejects_without_agent_passed(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="alice", families="alice", issue_labels=["status:review"])
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "accept", "1", "--member", "human", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("review:agent-passed", p.stderr)

    def test_accept_flow(self):
        head = self._prepare_branch()
        pass_comment = (
            f"<!-- collab:review pr=1 issue=1 sha={head} member=antigravity "
            f"family=gemini verdict=PASS proxy=false -->\n"
        )
        self.submitted_pr_state(
            head, authors="alice", families="alice",
            issue_labels=["status:review", "review:agent-passed"],
            comments=[{"body": pass_comment}],
        )
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "accept", "1", "--member", "human", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        edits = [c for c in calls if c["args"][:2] == ["issue", "edit"]]
        self.assertTrue(edits, calls)
        add_labels = [tok for c in edits for i, tok in enumerate(c["args"]) if c["args"][i - 1] == "--add-label"]
        self.assertIn("status:ready-to-merge", add_labels)
        remove_labels = [tok for c in edits for i, tok in enumerate(c["args"]) if c["args"][i - 1] == "--remove-label"]
        self.assertIn("status:review", remove_labels)
        self.assertIn("review:agent-passed", remove_labels)

    def test_release_returns_to_ready(self):
        issue = self.owned_issue(2, "status:in-progress", "alice")
        self.write_state({"issues": {"2": issue}, "pr": None, "prs": []})
        p = run_tool(self.repo, "release", "2", "--member", "alice", "--reason", "需求变了", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        edits = [c for c in calls if c["args"][:2] == ["issue", "edit"]]
        self.assertTrue(edits, calls)
        self.assertIn("status:ready", edits[-1]["args"])

    def test_next_fix_rework_priority_over_claim(self):
        rework = self.owned_issue(2, "status:rework", "alice")
        ready = self.issue(number=3, labels=["status:ready"])
        self.write_state({"issues": {"2": rework, "3": ready}, "pr": None, "prs": []})
        p = run_tool(self.repo, "next", "--member", "alice", "--json", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        data = json.loads(p.stdout)
        self.assertEqual(data["action"], "fix_rework")
        self.assertEqual(data["issue"], 2)

    def test_next_wip_blocks_claim(self):
        doing = self.owned_issue(2, "status:in-progress", "alice")
        ready = self.issue(number=3, labels=["status:ready"])
        self.write_state({"issues": {"2": doing, "3": ready}, "pr": None, "prs": []})
        p = run_tool(self.repo, "next", "--member", "alice", "--json", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        data = json.loads(p.stdout)
        self.assertEqual(data["action"], "resume_in_progress")
        self.assertEqual(data["issue"], 2)

    def test_next_idle_when_empty(self):
        self.write_state({"issues": {}, "pr": None, "prs": []})
        p = run_tool(self.repo, "next", "--member", "alice", "--json", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(json.loads(p.stdout)["action"], "idle")

    def test_next_skips_cross_repo_pr(self):
        head = self._prepare_branch()
        pr = self.submitted_pr_state(head, authors="alice", families="alice", issue_labels=["status:review"], is_cross=True)
        self.write_state({"issues": {"1": self.issue(labels=["status:review"])}, "pr": pr, "prs": [pr]})
        p = run_tool(self.repo, "next", "--member", "antigravity", "--json", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(json.loads(p.stdout)["action"], "idle")

    def test_rework_three_rounds_fuses(self):
        head = self._prepare_branch()
        rework_comment = lambda: {"body": f"<!-- collab:review pr=1 issue=1 sha={head} member=antigravity family=gemini verdict=REWORK proxy=false -->"}
        self.submitted_pr_state(
            head, authors="alice", families="alice", issue_labels=["status:review"],
            comments=[rework_comment(), rework_comment()],
        )
        git(self.repo, "checkout", "-q", "main")
        report = self.repo / ".collab" / "reviews" / f"pr-1-{head[:7]}-draft.md"
        p = run_tool(self.repo, "review", "1", "--member", "antigravity", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        text = report.read_text(encoding="utf-8")
        text = text.replace("TODO（检查方法、实际结果、证据位置）", "已检查：通过")
        text = text.replace("人工复核：TODO（填写后删除）", "人工复核：无参与")
        text = text.replace("TODO（填写后删除；确无盲点写：无新增盲点）", "无新增盲点")
        text = text.replace("PASS / REWORK", "REWORK")
        report.write_text(text, encoding="utf-8")
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "antigravity", "--sha", head,
            "--file", str(report), "--verdict", "rework", env=self.env,
        )
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        calls = self.read_log()
        edits = [c for c in calls if c["args"][:2] == ["issue", "edit"]]
        self.assertTrue(any("blocked:needs-human" in c["args"] for c in edits), calls)

    def test_b7_todo_in_defect_accepted(self):
        head = self._prepare_branch()
        self.submitted_pr_state(head, authors="alice", families="alice", issue_labels=["status:review"])
        git(self.repo, "checkout", "-q", "main")
        p = run_tool(self.repo, "review", "1", "--member", "antigravity", "--sha", head, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        report = self.repo / ".collab" / "reviews" / f"pr-1-{head[:7]}-draft.md"
        text = report.read_text(encoding="utf-8")
        text = text.replace("TODO（检查方法、实际结果、证据位置）", "已检查：通过")
        text = text.replace("人工复核：TODO（填写后删除）", "人工复核：无参与")
        text = text.replace("TODO（填写后删除；确无盲点写：无新增盲点）", "无新增盲点")
        text = text.replace("PASS / REWORK", "REWORK")
        # 缺陷描述里出现合法 "TODO" 字样（非占位符 TODO（）
        text = text.replace("## 缺陷\n\n- 无\n", "## 缺陷\n\n- R1：第 12 行残留 TODO 注释需清理\n")
        report.write_text(text, encoding="utf-8")
        p = run_tool(
            self.repo, "review-submit", "1", "--member", "antigravity", "--sha", head,
            "--file", str(report), "--verdict", "rework", env=self.env,
        )
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)

    def test_submit_fails_close_when_existing_pr_loses_authors(self):
        self.make_origin()
        git(self.repo, "checkout", "-q", "-b", "work/issue-1")
        _mkdir(self.repo / "src")
        (self.repo / "src" / "app.py").write_text("print(1)\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "feat")
        _mkdir(self.repo / ".collab")
        (self.repo / ".collab" / "task.md").write_text("# Issue #1\n\n<!-- collab:issue=1 -->\n", encoding="utf-8")
        p = run_tool(self.repo, "gate", "--profile", "fast")
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        # 已有 PR 但作者标记被删空
        self.write_state({
            "issues": {"1": self.issue(labels=["status:in-progress"])},
            "pr": {"number": 1, "url": "https://example.test/pull/1", "state": "OPEN",
                   "body": "<!-- collab:issue=1 -->"},
            "prs": [],
        })
        p = run_tool(self.repo, "submit", "--member", "alice", env=self.env)
        self.assertEqual(p.returncode, 1)
        self.assertIn("历史作者标记", p.stderr)


V26_MEMBERS = {
    "baizhi": {"family": "baizhi", "pools": ["free"]},
    "qianwen": {"family": "qwen", "pools": ["free"]},
    "workbuddy": {"family": "workbuddy", "pools": ["free"]},
    "dsh": {"family": "deepseek", "pools": ["abundant"]},
    "gemini": {"family": "gemini", "pools": ["abundant", "elite"]},
    "antigravity": {"family": "gemini", "pools": ["elite"]},
    "gpt": {"family": "openai", "pools": ["elite"]},
    "human": {"family": "human", "pools": ["human"]},
}

V26_ROUTING = {
    "default_tier": "standard",
    "tiers": {
        "basic": {
            "stages": [
                {"after_minutes": 0, "allow": ["@free"]},
                {"after_minutes": 15, "allow": ["@abundant"]},
            ],
            "review_stages": [
                {"after_minutes": 0, "allow": ["@free", "@abundant"]},
                {"after_minutes": 30, "allow": ["@elite"]},
            ],
        },
        "standard": {
            "stages": [
                {"after_minutes": 0, "allow": ["@free"]},
                {"after_minutes": 15, "allow": ["@abundant"]},
                {"after_minutes": 45, "allow": ["@elite"]},
            ],
            "review_stages": [
                {"after_minutes": 0, "allow": ["@abundant", "@free", "@elite"]},
            ],
        },
        "hard": {
            "stages": [
                {"after_minutes": 0, "allow": ["@elite"]},
            ],
            "review_stages": [
                {"after_minutes": 0, "allow": ["@elite"]},
                {"after_minutes": 15, "allow": ["@abundant"]},
            ],
        },
    },
}


def v26_cfg():
    return {"members": V26_MEMBERS, "routing": V26_ROUTING, "families": {}}


class TestV26(unittest.TestCase):
    def test_resolve_family_members_and_prefix(self):
        cfg = v26_cfg()
        self.assertEqual(collab.resolve_family("qianwen", cfg), "qwen")
        self.assertEqual(collab.resolve_family("qianwen-01", cfg), "qwen")
        self.assertEqual(collab.resolve_family("gemini", cfg), "gemini")
        with self.assertRaises(collab.Fail):
            collab.resolve_family("stranger", cfg)

    def test_pool_eligibility_basic_ladder(self):
        cfg = v26_cfg()
        now = collab.datetime(2026, 11, 26, 17, 0, 0, tzinfo=collab.timezone.utc)
        basic = {"labels": [{"name": "tier:basic"}], "createdAt": now.isoformat()}
        # 0 分钟：仅 @free 可领；@abundant(gemini) 未解锁
        self.assertTrue(collab.check_stage_eligibility(basic, "qianwen", cfg, now=now, role="dev"))
        self.assertFalse(collab.check_stage_eligibility(basic, "gemini", cfg, now=now, role="dev"))
        # 满 15 分钟：@abundant 自动补位
        later = now + collab.timedelta(minutes=20)
        self.assertTrue(collab.check_stage_eligibility(basic, "gemini", cfg, now=later, role="dev"))
        # tier:hard 仅 @elite；@free 被拒之门外
        hard = {"labels": [{"name": "tier:hard"}], "createdAt": now.isoformat()}
        self.assertTrue(collab.check_stage_eligibility(hard, "gpt", cfg, now=now, role="dev"))
        self.assertFalse(collab.check_stage_eligibility(hard, "qianwen", cfg, now=now, role="dev"))

    def test_prefer_override(self):
        cfg = v26_cfg()
        now = collab.datetime(2026, 11, 26, 17, 0, 0, tzinfo=collab.timezone.utc)
        hard = {"labels": [{"name": "tier:hard"}, {"name": "prefer:qianwen"}], "createdAt": now.isoformat()}
        self.assertTrue(collab.check_stage_eligibility(hard, "qianwen", cfg, now=now, role="dev"))

    def test_review_free_triangle(self):
        cfg = v26_cfg()
        now = collab.datetime(2026, 11, 26, 17, 0, 0, tzinfo=collab.timezone.utc)
        basic = {"labels": [{"name": "tier:basic"}], "createdAt": now.isoformat(), "body": ""}
        # basic 单 review 0 分钟开放 @free，异族三角互审放行
        self.assertTrue(collab.check_stage_eligibility(basic, "baizhi", cfg, now=now, role="review"))
        self.assertTrue(collab.check_stage_eligibility(basic, "qianwen", cfg, now=now, role="review"))


class TestV26Proxy(RepoFixture):
    def setUp(self):
        super().setUp()
        cfg = json.loads((self.repo / ".collab" / "config.json").read_text(encoding="utf-8"))
        cfg["members"] = V26_MEMBERS
        cfg["routing"] = V26_ROUTING
        cfg["families"] = {}
        (self.repo / ".collab" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "v26 config")

    def test_submit_proxy_keeps_family(self):
        head = self._prepare_branch()
        self.write_state({"issues": {"1": self.issue(labels=["status:in-progress"])}, "pr": None})
        p = run_tool(self.repo, "submit", "--member", "qianwen", "--proxy", "--summary", "x", env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        create = [c for c in self.read_log() if c["args"][:2] == ["pr", "create"]]
        self.assertTrue(create, self.read_log())
        body = create[0]["stdin"]
        self.assertIn("collab:authors=qianwen", body)
        self.assertIn("collab:families=qwen", body)
        self.assertIn("submit-proxy=true", body)


if __name__ == "__main__":
    unittest.main()

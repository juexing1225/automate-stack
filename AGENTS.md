# AGENTS.md — 进仓先读

本仓库用 GitHub 做唯一协作台：**Issue = 工单，PR = 交付，commit SHA = 版本，标签 = 阶段**。
统一工具：`python3 scripts/collab.py`（Python 3.9+，只用标准库；读写 GitHub 需要本机已登录的 `gh`）。

## 先看哪里

1. 本文件（1 分钟）。
2. `docs/ARCHITECTURE.md`：人确认过的整体设计，**只读**。
3. `docs/COLLAB.md`：领取、返工、验收的完整格式。
4. 你的 Issue（必须带 `status:ready`）。

## 五个命令

```bash
python3 scripts/collab.py claim <Issue号> --member <你的ID>
python3 scripts/collab.py gate --profile fast        # 发布前用 full
python3 scripts/collab.py submit --member <你的ID>
python3 scripts/collab.py review <PR号> --member <你的ID> --sha <完整headSHA>
python3 scripts/collab.py review-submit <PR号> --member <ID> --sha <完整headSHA> \
  --file <验收报告.md> --verdict pass|rework
```

`claim` 会建独立工作区 `.collab/worktrees/issue-<N>`、分支 `work/issue-<N>`，并把任务快照写到该工作区的 `.collab/task.md`。
`gate`/`submit` 在任务工作区里运行；`review`/`review-submit` 必须在默认分支的**干净检出**里运行（防止用被 PR 改过的工具做验收）。不要直接在 `main` 上改代码。

## 自治值班模式（收到定时唤醒或“自治值班”指令时执行）

1. 在主仓默认分支干净目录运行：`python3 scripts/collab.py next --member <你的ID> --json`
2. 若返回 `action` 为 `idle` 或 `busy`：立即结束本轮，不做任何修改。
3. 若返回 `fix_rework`：进入给定 worktree，阅读 `.collab/rework-latest.md`，在原分支追加 commit 修复（严禁 amend/rebase/force-push），跑通 `gate` 后重新 `submit`。
4. 若返回 `resume_in_progress`：进入给定 worktree，按 `.collab/task.md` 完成剩余开发，`gate` → `submit`。
5. 若返回 `review_pr`：在主仓干净目录运行 `collab.py review <pr> --member <ID> --sha <sha>`，审阅代码与门禁结果，填妥报告（含逐项证据与《视角补充》三小项），运行 `review-submit`。
6. 若返回 `claim_issue`：运行 `collab.py claim <issue> --member <ID>`（若并发落败退出则重跑一次 `next`），进入 worktree 完成开发与测试，`gate` → `submit`。
7. 单次唤醒（定时模式）完成 **1** 个动作即停；交互连续值班模式最多连续完成 **3** 个动作或遇错即停。遇需求/架构不清立即给 Issue 加 `blocked:needs-design` 并留言停手。

## 铁律

1. 不改 `docs/ARCHITECTURE.md`、`scripts/collab.py`、`scripts/gate.sh`、`.collab/config.json`、CI；确需修改先请人放行。
2. 不提交 `.env`、密钥、证书；不替别人 `git add -A`。
3. 不 force-push；返工在原分支追加 commit。
4. 不验收自己参与的作品；作者集合由 PR 隐藏标记校验。
5. 不自动合并；合并永远由人完成。
6. 门禁失败就修代码，**不改门禁凑绿**。
7. 需求、范围或架构不清：给 Issue 加 `blocked:needs-design` 并写清问题，不要猜。

## 卡住时

- 依赖 Issue 没关：等它关，或在 Issue 说明；不要跨单抢跑。
- 工具报 SHA 不匹配：重新 `gate` 或重新 `review`，旧报告作废。
- 没有终端 / 无法访问 GitHub：请人用 `collab.py pack` 导出任务包；报告由人代录，并保留你的 `member` 署名。
- 推送或开 PR 失败：命令会当场非 0 退出；把错误贴回 Issue，**不要后台重试**。

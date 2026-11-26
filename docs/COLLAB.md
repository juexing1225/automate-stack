> 作者：dsh（DeepSeek Harness）｜状态：模板文档，未在真实仓库验证。

# 协作细则

本文件是可复制到项目仓库的完整约定。工具只做机械校验；判断仍由成员和人负责。
任何产品、任何账号都走同一套流程；不要求安装插件、注入提示词或交出凭据。

## 1. 身份

- `member`：逻辑执行/验收成员，例如 `deepseek-01`、`gpt-review`。用于记录责任，不是身份认证。
- GitHub 账号：实际操作身份。多个 member 可以由同一账号代录；这不等于 GitHub 原生独立审批。
- PR 作者集合 = 所有实际改过本 PR 成果的 member。代录人不自动成为作者，但也不能替作者冒充独立验收。

## 2. 阶段与标签

| 标签 | 含义 | 谁能改 |
|---|---|---|
| `status:ready` | 人已确认，可领取 | 人 |
| `status:in-progress` | 已有唯一执行成员 | `claim` / 协调人 |
| `status:review` | PR 已交，等待异族审查 | `submit` |
| `status:rework` | 审查不通过，返工中 | `review-submit` |
| `review:agent-passed` | 异族成员初审通过，等人终审（非阶段标） | `review-submit` |
| `status:ready-to-merge` | 人已终审验收，等人合并 | **仅人** `accept` |
| `blocked:needs-design` | 需求/架构边界等人拍板 | 任何成员（须写原因） |
| `blocked:needs-human` | 连续返工/无进展自动熔断，等人裁决 | 工具自动 |
| `blocked:external` | 外部依赖阻塞 | 任何成员（须写原因） |
| `risk:high` | 碰到高危路径，合并前重点看 | `submit` 自动 |
| `canceled` | 取消，须在 Issue 写原因 | 人 |

Issue 关闭 = 完成（需要合并后验收的，保持打开到验收单完成）。
**Issue 标签**是阶段真源（PR 不维护第二份阶段）；Projects 看板只是视图，不参与权限与验收。

## 3. 领取

```bash
python3 scripts/collab.py claim 12 --member deepseek-01
```

工具会：

1. 确认 Issue 打开、带 `status:ready`、没有 `status:in-progress`、没有 `blocked:needs-design`；
2. 解析 `## 依赖` 里的 `#N`，逐个确认已关闭；
3. `git fetch origin <default>`（失败只警告，用本地基线）；
4. 建 `work/issue-12` 分支与 `.collab/worktrees/issue-12`（真实路径）；
5. 把 Issue 快照写到该工作区 `.collab/task.md`（含基线 SHA、依赖、成员）；
6. 标签改为 `status:in-progress`，并留一条领取评论。

同一 Issue 被两人同时领取时，标签不是原子锁：以 Issue 中第一条领取评论 + 协调人确认为准。发现冲突就停手，在 Issue 说明，不双开工作区。

## 4. 开发与门禁

```bash
python3 scripts/collab.py gate --profile fast
```

- 默认要求工作区干净（先 commit）；`--dirty` 仅用于开发中自测，`submit` 不接受脏回执。
- Step 0：受保护文件、密钥文件名与内容、`.collab/` 忽略状态。
- Step 1..N：按 `.collab/config.json` 的 `gate.fast` / `gate.full` 顺序执行，遇错即停。
- 回执写到 `<git-common-dir>/collab/receipts/`，绑定 `head_sha` 与基线，不入库；它是本地派生证据，不是密码学签名，验收必须由验收者自己重跑。
- `full` 档用于合并前/发布前；本机重型检查（模拟器构建等）放这里，别塞进每次提交。

受保护文件确需修改（只有人能放行）：`gate --allow-protected`。回执会记录 `protected_override: true`，PR 也会被标出来。

## 5. 交单

```bash
python3 scripts/collab.py submit --member deepseek-01 --summary "一句话变更说明"
```

工具会：

1. 校验分支名 `work/issue-<N>`、工作区干净、HEAD 有提交；
2. 校验门禁回执：`head_sha` = 当前 HEAD、`dirty=false`、受保护与密钥均通过；
3. 计算相对基线的改动，命中 `review_highlight_globs` 就加 `risk:high`；
4. `git push -u origin HEAD`（失败立即退出，不重试、不 force）；
5. 开/更新 PR，正文含 `Refs #N`（不用 `Closes`）、作者集合、门禁摘要；
6. 标签改为 `status:review`。

PR 合并前一直用 `Refs`；需要合并后验收的工单不要用自动关闭关键词。

## 6. 独立验收

```bash
# 必须在 main 的干净检出里运行（用可信工具，不执行 PR 里的脚本）
python3 scripts/collab.py review 34 --member workbuddy-review --sha <PR当前head>
```

工具会：

1. 读取 PR，校验 `--sha` = PR 当前 `headRefOid`；不匹配直接拒绝（过期验收）；
2. 校验验收 member 不在 PR 作者集合；
3. 拉取 `pull/34/head` 到 detached worktree；
4. 用**当前 main 检出里的配置与工具**重跑门禁（防止 PR 篡改门禁）；
5. 生成验收报告骨架 `.collab/reviews/pr-34-<sha7>-draft.md`，内嵌 Issue 验收项。

人工检查代码与行为后，填写报告：

```text
验收 member：
实际操作 / 代录 GitHub 账号：
PR：#34
完整 head SHA：
完整基线 SHA（目标分支 merge-base）：
独立性：工具已校验作者集合；人工复核无参与
逐项证据：
- A1：检查方法、实际结果、证据位置
- A2：……
结论：PASS / REWORK
缺陷：
- R1：对应验收项、重现方法、预期与实际、修复后验证方法
未验证项 / 限制：无，或逐项说明
```

提交报告（同样在 main 的干净检出里）：

```bash
python3 scripts/collab.py review-submit 34 --member workbuddy-review \
  --sha <完整head> --file .collab/reviews/pr-34-<sha7>-draft.md --verdict pass
```

工具会再次校验 SHA 未变、作者独立且异族、报告无 `TODO（` 占位符且结论与 `--verdict` 一致，然后发 PR 评论并改标签：
`pass` → 保持 `status:review` 并加 `review:agent-passed`（等人终审）；`rework` → `status:rework`（同一 PR 连续满 3 轮 REWORK 自动追加 `blocked:needs-human` 熔断）。

同账号代录的报告只是具名记录，不是 GitHub 原生 Approve，也不自动满足分支保护要求。有独立且有权限的账号时，才使用原生 Review。

## 6.1 异族交叉审查（Cross-Family）

- `member` 必须在 `.collab/config.json` 的 `families` 中登记其模型/产品家族（未登记直接失败关闭，禁止匿名绕过）。
- `review` / `review-submit` 硬校验：审查者 `family` 不得落在 PR 作者 `families` 集合内；同源模型家族互审会被拒。
- `review` 只审查**同仓可信作者**（`isCrossRepository=false` 且 `author.login ∈ trusted_github_logins`）的 PR，陌生 Fork 禁止本机自动跑门禁。
- `review` 会写 30 分钟 `review-lease` 评论防重复审查；PR 推新 SHA 后旧租约自动失效。

## 7. 返工

- 在原分支追加 commit，不 force-push，方便验收者只看增量；
- 在 PR 逐条回复 R1/R2…，写修复与验证证据；
- 重新 `gate` → `submit`；
- 验收者对**新的 head SHA** 重新出报告，旧结论不自动延续。

## 8. 人侧终审与合并

异族初审通过（`review:agent-passed`）后，由人执行终审：

```bash
python3 scripts/collab.py accept <PR号> --member human
```

工具会核对：PR 打开、Issue 带 `review:agent-passed`、最新 `collab:review` 为 `PASS` 且 SHA 等于当前 head、审查者与作者异族（单模型紧急降级可加 `--allow-same-family` 并留痕）。通过后**原子**移除 `status:review` 与 `review:agent-passed`、加上 `status:ready-to-merge`。

随后人查看 `status:ready-to-merge`（先看 `risk:high`），核对 HEAD 与验收报告 SHA 一致后按仓库保护规则点击 Merge。合并权限不因标签改变。

## 8.1 自治雷达（`next`）

```bash
python3 scripts/collab.py next --member <ID> --json
```

按 P1→P5 返回唯一下一步动作：`fix_rework`（修自己的返工单）→ `resume_in_progress`（续做在制单）→ `review_pr`（异族审查）→ `claim_issue`（WIP=0 时领新单）→ `idle`。内置：成员级防重入锁、同目标连续 2 次无进展自动挂 `blocked:needs-human`、同仓可信准入过滤。见 `AGENTS.md` 的「自治值班 SOP」。

## 9. 无终端 / 网页成员

```bash
python3 scripts/collab.py pack issue 12          # 任务包
python3 scripts/collab.py pack pr 34             # 审单包（含 diff）
```

把生成的单文件交给成员。成员回传报告后，由人执行 `review-submit --member <该成员ID>` 代录，保留署名。
代录不能宣称原生审批；代码补丁仍由有仓库权限的人提交，并登记真实作者。

## 10. 失败处理

| 情况 | 处理 |
|---|---|
| push / 开 PR 失败 | 命令非 0 退出；修复权限或冲突后重跑，不后台重试 |
| 回执 SHA 不匹配 | 重新 `gate`，旧回执作废 |
| PR head 已变 | 重新 `review`，旧报告作废 |
| 标签与事实不一致 | 以 Issue/PR 记录为准，改回标签并说明原因 |
| 工作区残留 | `git worktree list` 查看；确认无未提交成果后 `git worktree remove` |
| 需要改架构 | 停手，打 `blocked:needs-design`，写清问题与方案，等人 |

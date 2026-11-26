# 飞书交互卡片：在飞书里完成合并/审批

把 collab 工作流里「等人终审 / 等人合并」这一步，从「跳转 GitHub 点按钮」换成
「在飞书卡片上点一下」。人不用再到处跳转，合并、通过、关闭都直接在飞书完成。

## 这个系统怎么访问

| 入口 | 地址 / 方式 | 用途 |
|---|---|---|
| 飞书机器人 | 与「黄斌的飞书 CLI」会话（群聊 ID 见本机 `FEISHU_CHAT_ID`） | 收卡片、点按钮完成合并/审批（主入口） |
| GitHub 仓库 | `juexing1225/automate-stack` | Issue=工单、PR=交付、标签=阶段（真源） |
| 本机终端 | `python3 scripts/collab.py <command>` | 底层协作工具（领单/门禁/交单/验收/终审） |
| 常驻进程 | `feishu_notify.py` / `feishu_card_worker.py` | 定时推卡片 + 监听按钮回调执行动作 |

一句话：**日常只在飞书里点卡片**；要查工单/交付的原始记录看 GitHub；调试用终端跑 collab 命令。

## 工作流

1. 某 PR 的关联 Issue 出现 `review:agent-passed`（异族初审通过，等人终审）或
   `status:ready-to-merge`（人已终审，等人合并）时，`feishu_notify.py` 推一张卡片。
2. 人点按钮：
   - **通过并合并** / **合并** → 先 collab `accept` 记录终审（尽力而为），再 `gh pr merge --merge`。
   - **仅通过** → 只 `accept`，标记 `ready-to-merge`，暂不合并。
   - **关闭 PR** → `gh pr close`（有二次确认弹窗）。
3. `feishu_card_worker.py` 收到 `card.action.trigger` 回调，校验点击者是授权操作者后执行，
   并把卡片原地更新成结果卡（绿=已合并 / 蓝=已通过 / 灰=已关闭 / 红=失败+原因）。

## 部署

三个脚本都在 `scripts/` 下，只依赖标准库 + 本机 `gh` + `lark-cli`，不新增后台状态。

### 1. 推送卡片（在 PR 进入待人类处理阶段时运行）

```bash
# 推所有待终审/待合并的 PR
python3 scripts/feishu_notify.py --repo . --chat-id <你的群聊 oc_xxx>

# 只推单个 PR，或先预览
python3 scripts/feishu_notify.py --repo . --pr 7 --chat-id <你的群聊 oc_xxx> --dry-run
```

`--chat-id` 也可用环境变量 `FEISHU_CHAT_ID` 提供；`--user-id` 改成私聊。
卡片带幂等键 `pr-<N>-<headSHA7>`，重复运行不会刷屏。建议并入定时巡检一起跑。

### 2. 监听按钮回调（常驻进程）

```bash
python3 scripts/feishu_card_worker.py --repo . --operators <你的 open_id ou_xxx>
```

`--operators` 是允许点按钮的人的 open_id（逗号分隔，也可用 `FEISHU_OPERATORS` 环境变量）；
**没配就不执行任何动作**。建议交给 launchd / systemd 守护，进程退出后自动重启。

### 3. 前置条件

- Feishu 开发者后台「事件与回调 → 回调配置」需开启 `card.action.trigger`（本机已开，
  可用 `lark-cli event consume card.action.trigger --as bot --dry-run` 复查）。
- `gh` 已登录且对仓库有合并权限；`lark-cli` 已登录为机器人身份。

## 定时巡检（自治值班）

巡检与卡片推送解耦：巡检用 collab 自带的雷达 `next`，卡片推送/回调用上面的两个脚本。

```bash
# 每个智能体成员定时跑雷达（cron 示例，每 5 分钟）
*/5 * * * * cd /path/to/automate-stack && python3 scripts/collab.py next --member <ID> --json
```

当雷达发现 PR 进入待人类处理阶段时，调用 `feishu_notify.py` 推卡片。巡检的完整值班
SOP 见仓库 `AGENTS.md` 的「自治值班模式」。

## 安全设计

- **操作者白名单**：只有 `--operators` 里的 open_id 点按钮才会执行动作，其他人点只收到「无权限」。
- **head SHA 兜底**：按钮回调里带卡片发送时的 head SHA，合并用 `gh pr merge --match-head-commit`，
  PR 在点按钮之后又有新提交时不会误合并未审代码。
- **危险操作二次确认**：关闭 PR 有飞书原生确认弹窗。
- **事件去重**：按 `event_id` 去重，避免同一次点击被重放执行两次。

## 限制

- 卡片更新 token 30 分钟内最多用 2 次，超时/超次后结果卡不再原地更新（动作本身已执行）。
- 结果卡里的失败原因是最长 500 字符的截断，完整日志在 worker 的 stdout。
- 真实合并需要 `gh` 账号对仓库有写权限；无权限时卡片会如实显示失败原因。

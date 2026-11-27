# Collab 审批官（飞书）

人类专用的飞书“审批遥控器”。你在飞书里点按钮，机器人在你的 Mac 上执行
`collab.py` / `gh` / `git` 等已授权动作。GitHub Issue / PR / SHA 仍是唯一真源，
它不调度智能体、不包裹智能体、不注入提示词。

## 它做什么

- 推送待终审 PR 卡片：通过并合并、仅验收、打回返工、刷新
- 推送阻塞工单裁决卡（`blocked:needs-human` / `blocked:needs-design`）
- 推送 C0 置顶协作总览卡（内容哈希防抖，13 天自动换新卡、旧卡归档）
- 聊天指令：看板、PR 列表、单 PR 详情、导出任务包、审计日志
- 对账闭环：PR 合并/关闭或新提交后，把旧卡刷灰为“外部闭环 / 已作废”

## 它不做什么

- 不提供任意本机 shell 执行入口（无 `/run` / `/confirm`）
- 不替代 `scripts/collab.py` 的业务校验，不维护第二套状态
- 不自动合并未经 `collab.py accept` 的 PR
- 不处理群聊（默认只收私聊；`COLLAB_BOT_ALLOW_GROUP=true` 才放开）
- 不把 App Secret、GitHub Token 写进仓库或日志

## 一次性准备

### 1. 新建独立飞书自建应用

必须新应用，不要复用已连其他机器人的 App，避免事件被抢消费。

在**普通终端**（不要在 Agent 工作区里）执行：

```bash
export LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-collab"
mkdir -p "$LARKSUITE_CLI_CONFIG_DIR"
~/.local/bin/lark-cli config init --new --force-init
```

终端会打印 `verification_url`，用飞书扫码完成创建。命令会阻塞到创建完成。

已有 App ID / Secret 时：

```bash
export LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-collab"
read -r -s -p "App Secret: " FEISHU_APP_SECRET; echo
printf '%s' "$FEISHU_APP_SECRET" | \
  ~/.local/bin/lark-cli config init \
  --app-id cli_xxxxxxxxxxxxxxxx \
  --app-secret-stdin --brand feishu --force-init
unset FEISHU_APP_SECRET
```

验证隔离是否正确：

```bash
LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-collab" ~/.local/bin/lark-cli config show
```

### 2. 在开发者后台打开能力

进入该应用的开发者后台：

1. **添加应用能力 → 机器人**
2. **权限管理**申请并开通：
   - `im:message:send_as_bot`（发消息）
   - `im:message.p2p_msg:readonly`（收私聊）
   - `im:message:readonly`（卡片回调所需）
3. **事件与回调 → 事件配置**选择**长连接**，添加事件：
   - `im.message.receive_v1`
4. **事件与回调 → 回调配置**选择**长连接**，添加回调：
   - `card.action.trigger`
   > 事件和回调是两个独立开关；只加事件不加回调，卡片按钮点了没有反应。
5. **版本管理与发布**创建版本并发布；管理员审核通过后生效
6. **可用范围**包含你自己

> 不需要公网回调地址：lark-cli 用长连接收事件。

### 3. 准备独立镜像仓

桥接层只在独立镜像仓上操作，不碰你日常开发的主仓。克隆一份主仓到镜像目录：

```bash
mkdir -p ~/.collab-bridge/repos
git clone <你的主仓地址> ~/.collab-bridge/repos/collab-mvp-demo
```

默认镜像仓路径为 `~/.collab-bridge/repos/collab-mvp-demo`，可用
`COLLAB_BRIDGE_MIRROR_ROOT` 覆盖根目录，或用 `COLLAB_REPO` 直接指定完整路径。
启动预检会校验镜像仓存在、是 git 仓库、工作区干净、`origin` 远端已配置。

### 4. 写本地环境文件

```bash
mkdir -p ~/.config/collab
cat > ~/.config/collab/feishu.env <<'EOF'
COLLAB_REPO=/Users/juexing/.collab-bridge/repos/collab-mvp-demo
COLLAB_BOT_MEMBER=human
COLLAB_BOT_CMD_TIMEOUT=120
COLLAB_BOT_POLL_SECONDS=120
LARKSUITE_CLI_CONFIG_DIR=/Users/juexing/.lark-cli-collab
EOF
chmod 600 ~/.config/collab/feishu.env
```

该文件由程序启动时读取，**已存在的环境变量优先**。App Secret 存在 lark-cli
自己的配置目录，不写这里。

可选变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `COLLAB_BOT_HOME` | `~/.collab-approval-bot` | 运行状态、日志、审计目录 |
| `COLLAB_BRIDGE_MIRROR_ROOT` | `~/.collab-bridge/repos` | 镜像仓根目录 |
| `COLLAB_REPO` | `$MIRROR_ROOT/collab-mvp-demo` | 镜像仓完整路径 |
| `COLLAB_BOT_OWNER_IDS` | 空 | 预置主人 open_id，逗号分隔 |
| `COLLAB_BOT_ALLOW_GROUP` | `false` | 是否响应群聊 |
| `COLLAB_BOT_LARK_CLI` | `~/.local/bin/lark-cli` | lark-cli 路径 |

## 启动与绑定

```bash
cd "/Users/juexing/Desktop/开发项目/多智能体协作/collab-approval-bot"
python3 run.py --check     # 预检
python3 run.py             # 前台启动
```

首次启动会打印：

```
绑定码 BIND_CODE: ABC123
尚未绑定主人：在飞书私聊机器人发送 /bind ABC123
```

在飞书里私聊这个机器人，发送 `/bind ABC123`。绑定码是一次性的：绑定成功后
立即轮换，旧码作废，其他人再发旧码也无法进入白名单。后续需要增加主人时，
设置 `COLLAB_BOT_OWNER_IDS`（逗号分隔）后重启。

## 指令

| 指令 | 作用 |
| --- | --- |
| `/status` | 协作看板（本地仓库 + PR + 标签统计） |
| `/prs` | 打开的 PR 列表 |
| `/show 2` | PR 详情；已通过审查时附带审批卡 |
| `/card 2` | 生成审批卡 |
| `/approve 2` | 生成“通过并合并”确认卡 |
| `/rework 2 意见` | 打回返工（写 `collab:review verdict=REWORK` 评论） |
| `/pack issue 1` | 导出任务包 |
| `/log` | 最近审计记录 |
| `/repo` | 本地仓库与 gh 登录状态 |
| `/whoami` | 我的 open_id |
| `/help` | 帮助 |

## 安全边界

- **主人白名单**：只有绑定成功的 open_id 能操作；其他人发指令只收到拒绝
- **SHA 强绑定**：卡片按钮携带生成时的 `head_sha`；`accept`/`accept_and_merge`
  会把 `--sha` 传给内核，执行前重读 `headRefOid`，不一致直接拒绝并要求刷新
- **合并门禁**：合并固定带 `--match-head-commit <SHA>`，新提交无法被误合
- **业务门禁**：先跑 `collab.py accept`，它自己校验标签、最新 PASS、SHA、作者独立性
- **同轮互斥**：同一 `(repo, pr, sha)` 的并发点击只放行第一个，其余返回“处理中”，
  并有落盘决断记录防重启后重放
- **幂等**：消息按 `message_id`、卡片按 `event_id` 去重
- **单实例**：`~/.collab-approval-bot/bot.lock` 文件锁，重复启动会被拒绝
- **子进程环境清洗**：给 `collab.py`/`gh`/`git`/`lark-cli` 的只传白名单最小环境，
  剥离 `FEISHU_APP_SECRET`、`COLLAB_BOT_*` 等敏感变量
- **零外跳边界**：卡片不含“打开 GitHub”等外部跳转按钮
- **脱敏**：输出中的 `ghp_`、`github_pat_`、`sk-`、`app_secret=`、
  Bearer Token、私钥块会被替换

## 开机自启（launchd · LaunchDaemon）

桥接器装成**系统级 LaunchDaemon**（`/Library/LaunchDaemons`），这样 Mac 重启后
停在锁屏页、尚未登录桌面时也会拉起，手机飞书能照常收到卡片（LaunchAgents
只能在用户登录后才启动，做不到免登录自启）。

安装（需要管理员密码）：

```bash
./launchd/install.sh
```

卸载：

```bash
./launchd/uninstall.sh
```

验证开机自启：

1. 安装后先看一次日志确认进程正常：`tail -f ~/.collab-approval-bot/logs/bot.log`
2. `sudo launchctl list | grep collab` 应能看到 `com.collab.approval-bot`
3. 重启 Mac，**停在锁屏页、不登录桌面**，用手机飞书私聊机器人发 `/status`，
   能收到看板即说明免登录自启生效

日志：

```bash
tail -f ~/.collab-approval-bot/logs/bot.log
tail -f ~/.collab-approval-bot/logs/launchd.out.log
```

## 故障排查

**收不到消息**

```bash
LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-collab" \
  ~/.local/bin/lark-cli event consume im.message.receive_v1 --as bot --max-events 1 --timeout 60s
```

然后在飞书私聊机器人发一句话。没有输出说明后台事件订阅没开、应用没发布、
或可用范围不含你。

**卡片点了没反应**

```bash
LARKSUITE_CLI_CONFIG_DIR="$HOME/.lark-cli-collab" \
  ~/.local/bin/lark-cli event consume card.action.trigger --as bot --max-events 1 --timeout 60s
```

点一次按钮。没有输出说明 `card.action.trigger` 事件没订阅，或
`im:message:readonly` 没开。

**合并失败**：卡片会显示“已验收，合并未完成”并给出“重试合并”按钮。
先看 GitHub 上的分支保护、必需检查、冲突，再重试。

**绑定码丢了**：

```bash
python3 run.py --bind-code
```

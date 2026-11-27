#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.collab.approval-bot"
TARGET="/Library/LaunchDaemons/$LABEL.plist"

# LaunchDaemon 必须装到 /Library/LaunchDaemons 并用 launchctl bootstrap system 加载，
# 这样 Mac 重启停在锁屏页、尚未登录桌面时也会拉起（LaunchAgents 做不到免登录自启）。
if [[ $EUID -ne 0 ]]; then
    echo "✖ 需要管理员权限：系统级 LaunchDaemon 必须写入 /Library/LaunchDaemons 并用"
    echo "  launchctl bootstrap system 加载。将以 sudo 重新执行本脚本（需要你输入管理员密码）。"
    exec sudo "$0" "$@"
fi

# 用 sudo 执行时，SUDO_USER 才是真正要跑服务的普通用户。
USER_NAME="${SUDO_USER:-$USER}"
if [[ -z "$USER_NAME" || "$USER_NAME" == "root" ]]; then
    echo "✖ 无法确定要运行服务的普通用户。请用普通用户执行 sudo ./install.sh，不要直接以 root 登录。"
    exit 1
fi
HOME_DIR="$(eval echo "~$USER_NAME")"

# 独立环境文件路径：与程序默认读取位置一致（~/.config/collab/feishu.env）。
ENV_FILE="${COLLAB_BOT_ENV_FILE:-$HOME_DIR/.config/collab/feishu.env}"
# 独立镜像仓：与 config.py 的 COLLAB_BRIDGE_MIRROR_ROOT 默认值一致。
REPO="${COLLAB_REPO:-$HOME_DIR/.collab-bridge/repos/collab-mvp-demo}"

mkdir -p "$HOME_DIR/.collab-approval-bot/logs" "$HOME_DIR/.config/collab"

sed -e "s#__ROOT__#$ROOT#g" \
    -e "s#__HOME__#$HOME_DIR#g" \
    -e "s#__USER_NAME__#$USER_NAME#g" \
    -e "s#__REPO__#$REPO#g" \
    -e "s#__ENV_FILE__#$ENV_FILE#g" \
    "$ROOT/launchd/$LABEL.plist.template" > "$TARGET"

chmod 644 "$TARGET"
chown root:wheel "$TARGET"

launchctl bootout system "$TARGET" 2>/dev/null || true
launchctl bootstrap system "$TARGET"
launchctl kickstart -k "system/$LABEL"

echo "已安装并启动（系统级 LaunchDaemon）：$TARGET"
echo "绑定码："
cd "$ROOT" && sudo -u "$USER_NAME" python3 run.py --bind-code
echo "日志：tail -f $HOME_DIR/.collab-approval-bot/logs/bot.log"
echo "验证开机自启：重启后停在锁屏页、不登录桌面，手机飞书应能收到卡片。"

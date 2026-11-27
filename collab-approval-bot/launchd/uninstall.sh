#!/bin/bash
set -euo pipefail

LABEL="com.collab.approval-bot"
TARGET="/Library/LaunchDaemons/$LABEL.plist"

if [[ $EUID -ne 0 ]]; then
    echo "✖ 需要管理员权限卸载系统级 LaunchDaemon。将以 sudo 重新执行本脚本。"
    exec sudo "$0" "$@"
fi

launchctl bootout system "$TARGET" 2>/dev/null || true
rm -f "$TARGET"
echo "已停止并移除：$TARGET"

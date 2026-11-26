#!/usr/bin/env bash
# 项目门禁入口：保留这个固定名字，方便 CI、习惯和文档引用。
# 真正的检查逻辑在 scripts/collab.py；这里只转发，避免两套实现漂移。
set -euo pipefail
cd "$(dirname "$0")/.."
exec python3 scripts/collab.py gate "$@"

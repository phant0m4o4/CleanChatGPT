#!/bin/zsh
# macOS ChatGPT / Codex 本地重置入口。无参数只预览；--apply 才会修改文件。
# 不要 source。所有执行逻辑在同目录 cleanup_chatgpt_codex.py 中。
emulate -LR zsh
set -euo pipefail
script_dir="${0:A:h}"
if ! command -v python3 >/dev/null 2>&1; then
  print -u2 -- '需要 Python 3.11 或更高版本；未执行任何清理。'
  exit 1
fi
# -I 隔离 PYTHONPATH / 用户 site；-B 禁止生成 __pycache__。
exec python3 -I -B "$script_dir/cleanup_chatgpt_codex.py" "$@"

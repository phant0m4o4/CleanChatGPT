#!/bin/zsh -f
# macOS ChatGPT / Codex 默认数据清理。
# 阅读顺序：参数 → 默认清单 → 工作文件保护 → 预览 → 确认后删除。
# 不读取配置内容、不发现自定义存储位置、不创建备份；默认只预览。
# 仅依赖 macOS 自带 zsh 和系统命令。不要 source 本文件。
if [[ $ZSH_EVAL_CONTEXT == *:file ]]; then
  print -u2 -- '请直接执行脚本，不要 source。'
  return 1
fi
emulate -LR zsh
setopt ERR_EXIT NO_UNSET PIPE_FAIL EXTENDED_GLOB

typeset -i apply_mode=0 assume_yes=0 dry_run=0 remove_apps=0 deleted_count=0
# candidates 是固定清单中实际存在的对象；protected 是用户额外保护的路径。
typeset -a candidates=() protected=() planned=() kept=() app_bundles=() empty_dirs=()
typeset script_dir=${0:A:h} account_home=''
typeset -a service_ids=(com.openai.chat com.openai.codex ChatGPTHelper
  com.openai.sky.CUAService com.openai.sky.CUAService.cli)
typeset -a group_ids=(group.com.openai.chat 2DC432GLL2.com.openai.codex.notifications
  2DC432GLL2.com.openai.sky.CUAService)
typeset sqlite_re='^((state|logs|goals|memories|queue|thread_history)(_[0-9]+)?\.sqlite|codex-dev\.db)(-wal|-shm|-journal)?$'

die() { print -u2 -r -- "停止：$*"; exit 1; }
usage() {
  print -r -- 'ChatGPT / Codex 默认数据清理（macOS / zsh）
无参数 / --dry-run   只预览，不删除
--apply              按清单直接清理，不备份
--yes                仅配合 --apply，跳过 DELETE 确认
--remove-apps        另外清理默认位置中已核对身份的应用包
--protect PATH       保留指定文件/目录，可重复
--no-open            兼容旧参数；本脚本不自动打开网页
--help               显示说明
只处理默认位置；不读取配置，也不处理自定义数据位置。'
}

# 比较完整路径边界，避免 /abc 被当成 /abcd 的父目录。
# 调用方式：inside 子路径 父路径；成立时返回 0。
inside() {
  local child=${(L)1} parent=${(L)2}
  [[ $child == "$parent" || $parent == / || $child == "$parent/"* ]]
}

# 候选根或任一父级是软链接时跳过，避免沿链接扩大删除范围。
# 目录内部的链接不由 find 跟随；rm -r 也只移除链接本身。
has_link_component() {
  local cursor=$1
  while [[ $cursor != / ]]; do
    [[ -L $cursor ]] && return 0
    cursor=${cursor:h}
  done
  return 1
}

# 只登记确实存在的固定路径，不打开文件内容、不读取配置值。
# 不存在的路径直接忽略；软链接另放入保留项，方便预览时看见。
add_default() {
  local item=$1
  if has_link_component "$item"; then
    kept+=("软链接路径，保留：${(qqq)item}")
  elif [[ -e $item ]]; then
    candidates+=("$item")
  elif [[ -d ${item:h} && ( ! -r ${item:h} || ! -x ${item:h} ) ]]; then
    kept+=("父目录不可读取，未确认该项是否存在：${(qqq)item}")
  fi
}

# 每个默认 Codex 根只登记已知状态；skills、工作树、生成成果和未知根项不纳入。
# sessions/log/sqlite/shell_snapshots 只登记已识别的文件，不删除整个目录。
# 因此混放在这些目录里的未知工作文件会留下。
add_codex_defaults() {
  local base=$1 name item
  for name in .codex-global-state.json .codex-global-state.json.bak .sandbox_migration \
    .sqlite-maintenance.lock auth.json config.toml history.jsonl chrome-native-hosts-v2.json \
    installation_id models_cache.json session_index.jsonl version.json .DS_Store; do
    add_default "$base/$name"
  done
  for item in "$base"/*.config.toml(N.) "$base"/*(N.); do
    if [[ ${item:t} == *.config.toml || ${item:t} =~ $sqlite_re ]]; then add_default "$item"; fi
  done
  # 普通缓存/运行状态仍按目录清理；后面会先检查里面有没有工作内容标记。
  for name in .tmp ambient-suggestions browser cache code-review-plugin computer-use \
    ipc node_repl project-metadata-locks thread-writer-locks tmp; do
    add_default "$base/$name"
  done
  for item in "$base"/(sessions|archived_sessions)/**/rollout-*.jsonl(N.) \
    "$base"/(log|logs)/codex-(tui|login).log(|.<->)(N.) \
    "$base"/codex-(tui|login).log(|.<->)(N.); do
    add_default "$item"
  done
  for item in "$base"/sqlite/*(N.); do
    [[ ${item:t} =~ $sqlite_re ]] && add_default "$item"
  done
  for item in "$base"/shell_snapshots/*.sh(N.); do
    [[ ${item:t} =~ '^[0-9a-fA-F-]{36}\.sh$' ]] && add_default "$item"
  done
  for name in cache .plugin-appserver .remote-plugin-install-staging; do add_default "$base/plugins/$name"; done
  add_default "$base/vendor_imports/skills-curated-cache.json"
  # 这些目录只在清理后为空时移除；不递归删除其中的未知条目。
  for item in "$base"/(sessions|archived_sessions)/<->/<->/<->(N/) \
    "$base"/(sessions|archived_sessions)/<->/<->(N/) \
    "$base"/(sessions|archived_sessions)/<->(N/); do empty_dirs+=("$item"); done
  for name in sessions archived_sessions log logs sqlite shell_snapshots plugins vendor_imports; do
    [[ -d "$base/$name" && ! -L "$base/$name" ]] && empty_dirs+=("$base/$name")
  done
  [[ -d $base && ! -L $base ]] && empty_dirs+=("$base")
  return 0
}

# 删除前要求相关应用和 CLI 已退出，防止马上重建数据或继续写入。
# 只读进程列表；不结束任何应用。检查失败时停止。
require_stopped() {
  local output line command_value uid_value pid_value
  local line_re='^[[:space:]]*([0-9]+)[[:space:]]+([0-9]+)[[:space:]]+(.+)$'
  local app_re='(^|/)(ChatGPT( Classic)?|ChatGPTHelper|Codex|codex|codex-browser-app|CUAService|com\.openai\.sky\.CUAService(\.cli)?)([ ._/-]|$)'
  output=$(/bin/ps -axo uid=,pid=,comm=) || die '无法读取进程列表。'
  [[ -n $output ]] || die '无法核实相关应用是否退出。'
  for line in "${(@f)output}"; do
    [[ $line =~ $line_re ]] || die '无法解析进程列表。'
    uid_value=${match[1]}; pid_value=${match[2]}; command_value=${match[3]}
    if [[ $uid_value == "$EUID" && $command_value =~ $app_re ]]; then
      die "请先退出相关应用/CLI：PID $pid_value ${(qqq)command_value}"
    fi
  done
}

# 返回 0 表示需要保留，原因放在 REPLY。
# 规则刻意简单：若整个候选目录含工作标记，就整个跳过，不尝试拆分删除。
# 用户 --protect 的路径位于候选内部时，也保留整个候选，避免误删其父目录。
should_keep() {
  local item=$1 keep cursor found
  REPLY=''
  for keep in "${protected[@]}"; do
    if inside "$item" "$keep" || inside "$keep" "$item"; then REPLY='用户或脚本保护路径'; return 0; fi
  done
  has_link_component "$item" && { REPLY='路径经过软链接'; return 0; }
  # 保护位于现有 Git 项目内部的目标，包含 .git 文件形式的工作树。
  cursor=$item
  [[ -d $cursor ]] || cursor=${cursor:h}
  while [[ $cursor != / ]]; do
    if [[ -e "$cursor/.git" || -L "$cursor/.git" || ( -f "$cursor/HEAD" && -d "$cursor/objects" && -d "$cursor/refs" ) ]]; then
      REPLY='Git 工作目录或裸仓库'; return 0
    fi
    cursor=${cursor:h}
  done
  # 已核对身份的安装应用包属于安装文件，不把其内置资源误当作用户技能。
  if [[ -d $item ]]; then
    local item_device parent_device
    item_device=$(/usr/bin/stat -f '%d' "$item") || die '无法检查目录所在文件系统。'
    parent_device=$(/usr/bin/stat -f '%d' "${item:h}") || die '无法检查父目录所在文件系统。'
    if [[ $item_device != "$parent_device" ]]; then REPLY='候选目录本身是挂载边界'; return 0; fi
    (( ${app_bundles[(Ie)$item]} )) && return 1
    # -xdev 不进入嵌套文件系统；真正清理时 rm 的 -x 也不跨挂载点。
    # find 不跟随软链接；只读名称/元数据，不读取文稿和配置内容。
    found=$(/usr/bin/find -P "$item" -xdev \( -name .git -o -name HEAD \
      -o -iname worktrees -o -iname 'worktree-archives' -o -iname 'worktree_backups' \
      -o -iname 'worktree-backups' -o -iname skills -o -iname rules -o -iname prompts \
      -o -iname automations -o -iname envs -o -iname attachments -o -iname artifacts \
      -o -iname generated_images -o -iname visualizations -o -iname pets \
      -o -iname projects -o -iname workspaces -o -iname Documents -o -iname Downloads \
      -o -iname Desktop \) -print -quit) || die "无法检查目录，未继续清理：${(qqq)item}"
    if [[ -n $found ]]; then REPLY='目录包含工作内容标记'; return 0; fi
  fi
  return 1
}

# ---------- 1. 参数与当前账号 ----------
while (( $# )); do
  case $1 in
    --apply) apply_mode=1; shift ;;
    --dry-run) dry_run=1; shift ;;
    --yes) assume_yes=1; shift ;;
    --remove-apps) remove_apps=1; shift ;;
    --no-open) shift ;;
    --help|-h) usage; exit 0 ;;
    --protect)
      (( $# >= 2 )) || die '--protect 缺少路径。'
      [[ $2 == /* && "/$2/" != */../* ]] || die '--protect 请使用无 .. 的绝对路径。'
      protected+=("${2:a}" "${2:A}"); shift 2 ;;
    *) die "未知参数：${(qqq)1}；本版只处理默认位置。" ;;
  esac
done
(( ! (apply_mode && dry_run) )) || die '--apply 与 --dry-run 不能同时使用。'
(( ! assume_yes || apply_mode )) || die '--yes 必须配合 --apply。'
[[ $OSTYPE == darwin* && $EUID != 0 ]] || die '请在 macOS 下以普通用户执行，不要 sudo。'
typeset account_name raw_home
account_name=$(/usr/bin/id -un) || die '无法核对当前账号。'
raw_home=$(/usr/bin/dscl . -read "/Users/$account_name" NFSHomeDirectory) || die '无法核对账号主目录。'
account_home=${raw_home#NFSHomeDirectory: }
[[ $account_home == /* && $account_home != / && $HOME -ef $account_home ]] || die 'HOME 与当前账号主目录不符。'
account_home=${account_home:A}
# 脚本自身、共享技能及当前工作目录里的资料不纳入清理。
protected+=("$script_dir/clean-chatgpt-codex.sh" "$script_dir/readme.md" "$script_dir/CLEANUP-NOTES.md" "$account_home/.agents")
# --apply 先检查进程，再收集默认位置；只读预览允许在应用运行时查看。
if (( apply_mode )); then require_stopped; fi

# ---------- 2. 固定默认清单：不读取 config.toml，也不使用 CODEX_HOME 等覆盖 ----------
add_codex_defaults "$account_home/.codex"
add_codex_defaults "$account_home/.config/codex"
add_default "$account_home/.cache/codex"
typeset folder ident item name location bundle_id
for folder in 'Application Support' Caches Logs WebKit HTTPStorages Cookies; do
  for ident in "${service_ids[@]}" ChatGPT Codex; do
    add_default "$account_home/Library/$folder/$ident"
    if [[ $folder == HTTPStorages || $folder == Cookies ]]; then add_default "$account_home/Library/$folder/$ident.binarycookies"; fi
  done
done
add_default "$account_home/Library/Application Support/OpenAI/Codex"
for ident in "${service_ids[@]}" com.openai.chat.Widgets; do
  add_default "$account_home/Library/Preferences/$ident.plist"
  add_default "$account_home/Library/Saved Application State/$ident.savedState"
  add_default "$account_home/Library/Containers/$ident"
  add_default "$account_home/Library/Application Scripts/$ident"
done
for ident in "${group_ids[@]}"; do
  add_default "$account_home/Library/Group Containers/$ident"
  add_default "$account_home/Library/Application Scripts/$ident"
done
for name in codex-alert-codex-notification.wav codex-notification.wav; do add_default "$account_home/Library/Sounds/$name"; done
for item in "$account_home/Library/Preferences"/com.openai.(chat|codex).*plist(N.) \
  "$account_home/Library/Preferences/ByHost"/com.openai.(chat|codex).*plist(N.); do add_default "$item"; done
# 诊断报告只匹配已知应用名和报告后缀，不按 openai/codex 关键字全盘搜索。
for folder in "$account_home/Library/Logs/DiagnosticReports" "$account_home/Library/Logs/DiagnosticReports/Retired" "$account_home/Library/Application Support/CrashReporter"; do
  for item in "$folder"/*(N.); do
    if [[ ${item:t} =~ '^(ChatGPT|Codex|codex|ChatGPTHelper|CUAService)( Helper( \([A-Za-z ]+\))?)?[_.-].*\.(ips|crash|hang|diag|plist)$' ]]; then add_default "$item"; fi
  done
done
# getconf 只查询系统提供的当前用户缓存/临时默认位置，不读取应用配置。
for name in DARWIN_USER_CACHE_DIR DARWIN_USER_TEMP_DIR; do
  location=$(/usr/bin/getconf "$name") || die "无法查询 $name。"
  [[ $location == /* && $location != / ]] || die '系统返回了异常缓存/临时路径。'
  location=${location:A}
  for ident in "${service_ids[@]}"; do add_default "$location/$ident"; done
done
# 文稿中的项目和生成文件全部保留，只列入根层 Finder 元数据。
for folder in "$account_home/Documents/ChatGPT" "$account_home/Documents/Codex"; do
  add_default "$folder/.DS_Store"; add_default "$folder/.localized"
  [[ -d $folder && ! -L $folder ]] && empty_dirs+=("$folder")
done
# 应用默认保留；用户另加 --remove-apps 时，只读 Info.plist 核对安装包身份。
# 这里不解析用户配置，也不读取聊天/文稿内容。
if (( remove_apps )); then
  for folder in /Applications "$account_home/Applications"; do
    for name in 'ChatGPT.app' 'ChatGPT Classic.app' 'Codex.app' 'OpenAI Codex.app'; do
      item="$folder/$name"
      [[ -d $item && ! -L $item ]] || continue
      bundle_id=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$item/Contents/Info.plist") || die "无法核对应用身份：${(qqq)item}"
      if [[ $bundle_id == com.openai.chat || $bundle_id == com.openai.codex ]]; then app_bundles+=("$item"); add_default "$item"; fi
    done
  done
fi

# ---------- 3. 先显示计划；命中保护就整项跳过 ----------
# 同一默认文件可能被明确名称和版本名单同时发现，去重但不扩大范围。
candidates=("${(@u)candidates}")
for item in "${candidates[@]}"; do
  # 仅当当前目录本身位于候选内部时保护它，不把整个 HOME 当成保护父目录。
  if inside "${PWD:A}" "$item"; then protected+=("${PWD:A}"); fi
  if should_keep "$item"; then kept+=("$REPLY：${(qqq)item}")
  else planned+=("$item"); fi
done
print -r -- "默认清单中可处理 ${#planned} 项（不创建备份）："
for item in "${planned[@]}"; do print -r -- "  删除 ${(qqq)item}"; done
for item in "${kept[@]}"; do print -r -- "  保留 $item"; done
print -- '已识别的状态父目录仅在清理后为空时移除；文稿中的用户内容原地保留。'
print -- '自定义数据位置、钥匙串、云端内容等不在此清单内；详见 CLEANUP-NOTES.md。'
if (( ! apply_mode )); then print -- '只读预览结束，没有执行删除。'; exit 0; fi

# ---------- 4. 显式执行：确认、再次检查、按固定清单直接删除 ----------
if (( ! assume_yes )); then
  [[ -t 0 ]] || die '非交互执行需明确传入 --apply --yes。'
  print -n -- '输入 DELETE 确认直接删除（无备份）：'
  IFS= read -r confirmation || die '未读取到确认。'
  [[ $confirmation == DELETE ]] || { print -- '已取消。'; exit 0; }
fi
require_stopped
for item in "${planned[@]}"; do
  # 确认之后还要重查保护，不能依赖几分钟前的预览结果。
  if should_keep "$item"; then die "目标状态变化，现需保留：${(qqq)item}（$REPLY）"; fi
  [[ $item == /* && $item != / && $item != "$account_home" && $item != "$account_home/Library" ]] || die '拒绝异常删除目标。'
  /bin/rm -rf -x -- "$item" || die "删除失败：${(qqq)item}；之前完成的删除不会回滚。"
  (( ++deleted_count ))
  print -r -- "已删除 ${(qqq)item}"
done
# rmdir 只会移除空目录。先检查所有子项（包括隐藏文件），非空就保留。
for folder in "${(@Ou)empty_dirs}"; do
  has_link_component "$folder" && continue
  if should_keep "$folder"; then continue; fi
  [[ -d $folder && -r $folder && -x $folder ]] || continue
  typeset -a remaining=("$folder"/*(ND))
  if (( ${#remaining} == 0 )); then /bin/rmdir -- "$folder" || die "无法移除空目录：${(qqq)folder}"; fi
done
print -r -- "默认清单处理完成，共清理 $deleted_count 项。保留项和自定义位置未清理。"

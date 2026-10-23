#!/usr/bin/env python3
"""macOS reset: discover -> protect -> verify -> delete planned app state.

Preview never writes. Config is parsed as data, never sourced or executed.
"""
import sys

if sys.version_info < (3, 11):
    raise SystemExit("需要 Python 3.11+（安全解析 TOML）；未执行清理。")

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import shutil
import stat
import subprocess
import tomllib
import unicodedata

APP_IDS = {"com.openai.chat", "com.openai.codex"}
SERVICE_IDS = APP_IDS | {"ChatGPTHelper", "com.openai.sky.CUAService", "com.openai.sky.CUAService.cli"}
GROUP_IDS = {"group.com.openai.chat", "2DC432GLL2.com.openai.codex.notifications", "2DC432GLL2.com.openai.sky.CUAService"}
APP_NAMES = ("ChatGPT.app", "ChatGPT Classic.app", "Codex.app", "OpenAI Codex.app")
WORKTREE_NAMES = {"worktrees", "worktree-archives", "worktree_backups", "worktree-backups"}
# Root entries are classified by both name and type. Unknown entries are kept.
CODEX_STATE_DIRS = {
    ".tmp", "ambient-suggestions", "browser", "cache", "code-review-plugin",
    "computer-use", "ipc", "log", "logs", "node_repl", "project-metadata-locks",
    "sessions", "archived_sessions", "shell_snapshots", "sqlite",
    "thread-writer-locks", "tmp",
}
CODEX_STATE_FILES = {
    ".codex-global-state.json", ".codex-global-state.json.bak", ".sandbox_migration",
    ".sqlite-maintenance.lock", "auth.json", "config.toml", "history.jsonl",
    "chrome-native-hosts-v2.json", "installation_id", "models_cache.json",
    "session_index.jsonl", "version.json", ".DS_Store",
}
WORK_NAMES = WORKTREE_NAMES | {
    "attachments", "artifacts", "generated_images", "visualizations", "pets",
    "projects", "workspaces", "Documents", "Downloads", "Desktop", "skills",
    "rules", "prompts", "automations", "envs",
}
PROCESS_RE = re.compile(r"(?:^|/)(?:ChatGPT(?: Classic)?|ChatGPTHelper|Codex|codex|codex-browser-app|CUAService|com\.openai\.sky\.CUAService(?:\.cli)?)(?=$|[ ._/-])")
REPORT_RE = re.compile(r"^(?:ChatGPT|Codex)(?: Helper(?: \([A-Za-z ]+\))?)?[_.-].*\.(?:ips|crash|hang|diag|plist)$|^(?:ChatGPTHelper|codex|CUAService)[_.-].*\.(?:ips|crash|hang|diag|plist)$")
SQLITE_RE = re.compile(r"^(?:(?:state|logs|goals|memories|queue|thread_history)(?:_\d+)?\.sqlite|codex-dev\.db)(?:-wal|-shm|-journal)?$")
LOG_RE = re.compile(r"^codex-(?:tui|login)\.log(?:\.\d+)?$")
MANUAL_GUIDE = (
    ("分别核对 Chat/Work/Codex 的活动和归档记录；归档不等于删除，当前界面的批量删除范围尚未核实。", "https://learn.chatgpt.com/docs/app/settings"),
    ("ChatGPT Memory 在 Settings > Personalization 管理；Codex memories 按机器保存，应分开处理。", "https://learn.chatgpt.com/docs/customization/memories"),
    ("Library/Space 独立保存内容需单独检查；不假定当前账号存在清空回收站或 Delete all 按钮。", "https://learn.chatgpt.com/docs/enterprise/chatgpt-space"),
    ("Codex 共享快照：在 ChatGPT data controls > Shared links 查看或撤销。", "https://learn.chatgpt.com/docs/use-chatgpt"),
    ("本地内置浏览器：Settings > Browser > Clear browsing data；不是 Safari/Chrome 等个人浏览器。", "https://learn.chatgpt.com/docs/browser"),
    ("云端浏览器（功能可用时）：Settings > Cloud browser > Browser data > Clear all；会退出其中的网站登录。", "https://learn.chatgpt.com/docs/browser"),
    ("卸载插件不等于断开独立 MCP 连接，也不等于删除已保存内容。", "https://learn.chatgpt.com/docs/plugins"),
    ("其他主机及配对需单独核对；host 的 Settings > Connections 管理设备，退出 ChatGPT 不移除既有配对。", "https://learn.chatgpt.com/docs/remote-connections"),
    ("钥匙串实际 service/account 未读取；只处理可确认归属的单项，不清空整个钥匙串。", "https://learn.chatgpt.com/docs/auth"),
)


class Unsafe(RuntimeError):
    pass


def exists(p):
    try:
        p.lstat()
        return True
    except FileNotFoundError:
        return False


def is_kind(p, predicate):
    try:
        return predicate(p.lstat().st_mode)
    except FileNotFoundError:
        return False


def is_dir(p):
    return is_kind(p, stat.S_ISDIR)


def is_file(p):
    return is_kind(p, stat.S_ISREG)


def is_link(p):
    return is_kind(p, stat.S_ISLNK)


def path_key(p):
    # Conservatively treat case/Unicode aliases alike, including on a volume
    # that happens to be case-sensitive. This can preserve extra files, never
    # bypass a --protect path because Finder displayed a different spelling.
    return tuple(unicodedata.normalize("NFC", part).casefold() for part in p.parts)


def within(p, parent):
    child, ancestor = path_key(p), path_key(parent)
    return child[:len(ancestor)] == ancestor


def physically_within(p, parent):
    if within(p, parent):
        return True
    if not exists(parent):
        return False
    parent_stat = parent.lstat()
    # Also handle macOS firmlinks / volume aliases when checking protected paths.
    return any(exists(node) and os.path.samestat(node.lstat(), parent_stat)
               for node in [p, *p.parents])


def absolute(value):
    # Never expand config commands, variables, or guess another process's cwd.
    if value == "~" or value.startswith("~/"):
        value = str(Path.home()) + value[1:]
    p = Path(value)
    if not p.is_absolute() or ".." in p.parts:
        raise Unsafe(f"只接受无 .. 的绝对路径（相对配置的原工作目录未知）：{value!r}")
    return p


def check_components(p, allow_leaf_link=False):
    for item in [*reversed(p.parents), p]:
        if is_link(item) and not (item == p and allow_leaf_link):
            raise Unsafe(f"路径经过软链接，保留并要求单独核对实际位置：{item}")


def children(p):
    # Permission/traversal errors propagate; unreadable never means empty.
    return sorted(p.iterdir(), key=lambda item: item.name)


def quote(p):
    return json.dumps(str(p), ensure_ascii=False)


def identity(st):
    return (st.st_dev, st.st_ino, st.st_mode, st.st_size, st.st_mtime_ns, st.st_ctime_ns)


class Plan:
    def __init__(self, args):
        self.args = args
        self.home = absolute(str(Path.home()))
        if self.home == Path("/") or os.geteuid() == 0:
            raise Unsafe("请以当前普通用户执行，不要使用 sudo/root 或 HOME=/。")
        check_components(self.home)
        if not os.path.samefile(self.home, pwd.getpwuid(os.getuid()).pw_dir):
            raise Unsafe("HOME 与当前账号的系统主目录不符；拒绝处理其他目录。")
        self.roots, self.protected, self.pins = {}, {}, {}
        self.layout, self.absent = {}, set()
        self.targets, self.notes, self.errors = [], [], []
        self.home_roots = set()
        self.app_roots = set()
        self.download_roots = set()
        self.broad = {
            Path("/"), Path("/Users"), Path("/Applications"), Path("/Library"),
            Path("/System"), Path("/private"), Path("/tmp"), Path("/private/tmp"),
            Path("/usr"), Path("/usr/local"), Path("/opt"), Path("/opt/homebrew"),
            self.home, self.home / "Documents", self.home / "Desktop",
            self.home / "Downloads", self.home / "Library", self.home / ".config",
            self.home / ".cache", self.home / ".local", self.home / ".local/bin",
        }
        self.broad.update(self.home / "Library" / name for name in (
            "Application Support", "Caches", "Logs", "Preferences", "Containers",
            "Group Containers", "Application Scripts", "WebKit", "HTTPStorages",
        ))
        for name in ("cleanup_chatgpt_codex.py", "clean-chatgpt-codex.sh", "readme.md", "CLEANUP-NOTES.md"):
            self.protected[Path(__file__).absolute().with_name(name)] = "清理工具及使用说明"
        self.protected[self.home / ".agents"] = "多个工具可能共享的技能/工作配置"
        for value in args.protect:
            protected = absolute(value)
            self.protected[protected] = "--protect 指定的工作文件"
            # Resolving a protection path may only enlarge the protected scope,
            # never the deletion scope.
            self.protected[Path(os.path.realpath(protected))] = "--protect 的实际位置"

    def add(self, p, reason):
        p = absolute(str(p))
        if any(physically_within(item, p) for item in self.broad):
            raise Unsafe(f"拒绝把通用目录或其祖先作为清理目标：{p}")
        if not exists(p):
            self.absent.add(p)
            return
        try:
            check_components(p)
        except Unsafe as error:
            self.protected[p] = str(error)
            self.notes.append(str(error))
            return
        if any(physically_within(p, other) and physically_within(other, p) for other in self.roots):
            return
        for ancestor in p.parents:
            if exists(ancestor / ".git") or (exists(ancestor / "HEAD") and is_dir(ancestor / "objects") and is_dir(ancestor / "refs")):
                self.protected[p] = f"目标位于 Git 工作目录内部：{ancestor}"
                break
        self.roots[p] = reason

    def remember_layout(self, p, entries):
        names = [entry.name for entry in entries]
        if p in self.layout and self.layout[p] != names:
            raise Unsafe(f"分类后目录出现变化，停止并重新生成计划：{p}")
        self.layout[p] = names

    def protect_unknown_entries(self, p):
        entries = children(p)
        self.remember_layout(p, entries)
        for child in entries:
            if is_file(child) and (child.name in CODEX_STATE_FILES or SQLITE_RE.fullmatch(child.name)
                                   or LOG_RE.fullmatch(child.name) or child.name.endswith(".config.toml")):
                continue
            if is_dir(child) and child.name in CODEX_STATE_DIRS:
                continue
            # Plugin downloads are disposable; custom/unrecognized additions
            # in these parents remain in place, just like unknown root entries.
            if is_dir(child) and child.name in {"plugins", "vendor_imports"}:
                plugin_entries = children(child)
                self.remember_layout(child, plugin_entries)
                for entry in plugin_entries:
                    if child.name == "plugins" and is_dir(entry) and entry.name in {
                        "cache", ".plugin-appserver", ".remote-plugin-install-staging"
                    }:
                        self.download_roots.add(entry)
                        continue
                    if child.name == "vendor_imports" and is_file(entry) and entry.name == "skills-curated-cache.json":
                        continue
                    self.protected[entry] = "未识别的插件/导入内容：原地保留"
                continue
            self.protected[child] = "工作文件、自定义技能/规则或未识别条目：原地保留"

    def codex_home(self, p):
        p = absolute(str(p))
        if p in self.home_roots:
            return
        self.home_roots.add(p)
        if not exists(p):
            self.absent.add(p)
            return
        check_components(p)
        if p != self.home / ".codex" and not any(exists(p / marker) for marker in ("config.toml", "auth.json", "sessions")):
            raise Unsafe(f"自定义 Codex 根目录缺少可识别标记，拒绝整目录处理：{p}")
        self.add(p, "Codex 已识别的本地状态（含历史、配置、凭据；不备份）")
        self.protect_unknown_entries(p)
        configs = [p / "config.toml", *sorted(p.glob("*.config.toml"))]
        for config in configs:
            if not exists(config):
                continue
            check_components(config)
            with config.open("rb") as handle:
                data = tomllib.load(handle)
            profiles = data.get("profiles", {})
            if not isinstance(profiles, dict):
                raise Unsafe(f"{config} 的 profiles 格式异常。")
            for table in [data, *profiles.values()]:
                if not isinstance(table, dict):
                    continue
                for key, kind in (("sqlite_home", "sqlite"), ("log_dir", "log")):
                    value = table.get(key)
                    if value is not None:
                        if not isinstance(value, str):
                            raise Unsafe(f"{config} 的 {key} 不是字符串。")
                        try:
                            self.external_store(absolute(value), kind)
                        except Unsafe as error:
                            self.errors.append(f"{config} / {key}: {error}")

    def external_store(self, p, kind):
        if not exists(p):
            self.absent.add(p)
            return
        check_components(p)
        if not is_dir(p):
            raise Unsafe(f"配置的 {kind} 位置不是目录：{p}")
        pattern = SQLITE_RE if kind == "sqlite" else LOG_RE
        # Custom stores can be shared directories. Never remove the root.
        entries = children(p)
        self.remember_layout(p, entries)
        for child in entries:
            if pattern.fullmatch(child.name) and not is_dir(child):
                self.add(child, f"自定义 {kind} 中明确识别的 Codex 文件")
            elif not any(within(child, root) for root in self.home_roots):
                self.notes.append(f"自定义 {kind} 中未识别的条目保留：{child}")

    def discover(self):
        h, lib = self.home, self.home / "Library"
        homes = [h / ".codex", *map(absolute, self.args.codex_home)]
        if os.environ.get("CODEX_HOME"):
            homes.append(absolute(os.environ["CODEX_HOME"]))
        for p in homes:
            try:
                self.codex_home(p)
            except (OSError, ValueError, Unsafe) as error:
                self.errors.append(str(error))
        if os.environ.get("CODEX_SQLITE_HOME"):
            self.external_store(absolute(os.environ["CODEX_SQLITE_HOME"]), "sqlite")
        for kind, values in (("sqlite", self.args.sqlite_dir), ("log", self.args.log_dir)):
            for value in values:
                self.external_store(absolute(value), kind)
        for p in (h / "Documents/ChatGPT", h / "Documents/Codex"):
            self.add(p, "文稿目录：仅清理根层 Finder 元数据和空目录，工作内容保留")
            if is_dir(p) and not is_link(p):
                check_components(p)
                entries = children(p)
                self.remember_layout(p, entries)
                for child in entries:
                    if is_file(child) and child.name in {".DS_Store", ".localized"}:
                        continue
                    self.protected[child] = "文稿中的工作文件/项目/生成成果：原地保留"
        config_root = h / ".config/codex"
        self.add(config_root, "其他 Codex 配置位置：仅识别的状态")
        if is_dir(config_root) and not is_link(config_root):
            check_components(config_root)
            self.protect_unknown_entries(config_root)
        self.add(h / ".cache/codex", "其他 Codex 缓存")
        names = SERVICE_IDS | {"ChatGPT", "Codex"}
        for folder in ("Application Support", "Caches", "Logs", "WebKit", "HTTPStorages", "Cookies"):
            for name in sorted(names):
                self.add(lib / folder / name, "应用专属本地数据")
                if folder in {"HTTPStorages", "Cookies"}:
                    self.add(lib / folder / (name + ".binarycookies"), "应用 Cookie")
        self.add(lib / "Application Support/OpenAI/Codex", "Codex 应用支持")
        for ident in sorted(SERVICE_IDS | {"com.openai.chat.Widgets"}):
            self.add(lib / "Preferences" / (ident + ".plist"), "应用偏好")
            self.add(lib / "Saved Application State" / (ident + ".savedState"), "窗口恢复状态")
            self.add(lib / "Containers" / ident, "应用沙盒容器")
            self.add(lib / "Application Scripts" / ident, "应用沙盒脚本目录")
        for ident in sorted(GROUP_IDS):
            self.add(lib / "Group Containers" / ident, "应用组容器")
            self.add(lib / "Application Scripts" / ident, "应用组脚本目录")
        for name in ("codex-alert-codex-notification.wav", "codex-notification.wav"):
            self.add(lib / "Sounds" / name, "Codex 提示音")
        for folder in (lib / "Preferences", lib / "Preferences/ByHost"):
            if is_dir(folder):
                check_components(folder)
                for p in children(folder):
                    if p.suffix == ".plist" and any(p.name.startswith(ident + ".") for ident in APP_IDS):
                        self.add(p, "应用命名空间内的偏好/功能开关")
        for folder in (lib / "Application Support/CrashReporter", lib / "Logs/DiagnosticReports", lib / "Logs/DiagnosticReports/Retired"):
            if is_dir(folder):
                check_components(folder)
                for p in children(folder):
                    if REPORT_RE.fullmatch(p.name) and is_file(p):
                        self.add(p, "ChatGPT/Codex 崩溃诊断报告")
        # Only exact app identifiers under the current user's Darwin locations.
        for key in ("DARWIN_USER_CACHE_DIR", "DARWIN_USER_TEMP_DIR"):
            result = subprocess.run(["/usr/bin/getconf", key], capture_output=True, text=True)
            if result.returncode:
                self.errors.append(f"无法查询 {key}，不把未检查位置当作不存在。")
                continue
            folder = absolute(result.stdout.strip())
            for ident in sorted(SERVICE_IDS):
                self.add(folder / ident, "当前用户的应用临时/缓存目录")
        # Launch agents may recreate data even without an active process.
        for folder in (lib / "LaunchAgents", Path("/Library/LaunchAgents"), Path("/Library/LaunchDaemons")):
            if is_dir(folder):
                check_components(folder)
                for p in children(folder):
                    if any(p.name.startswith(ident + ".") for ident in SERVICE_IDS):
                        self.errors.append(f"发现可能重新创建数据的启动服务；先核实并停用，再清理：{p}")
        discovered_apps = []
        for folder in (Path("/Applications"), h / "Applications"):
            for name in APP_NAMES:
                app = folder / name
                if not exists(app):
                    continue
                discovered_apps.append(app)
                if not self.args.remove_apps:
                    self.notes.append(f"应用保留（--remove-apps 才纳入）：{app}")
                    continue
                check_components(app)
                info = app / "Contents/Info.plist"
                check_components(info)
                with info.open("rb") as handle:
                    ident = plistlib.load(handle).get("CFBundleIdentifier")
                if ident not in APP_IDS:
                    self.errors.append(f"应用 bundle ID 不属于已知客户端，保留：{app}")
                    continue
                self.add(app, "已核对 bundle ID 的应用包（含内置 CLI）")
                self.app_roots.add(app)
        cli = shutil.which("codex")
        if cli:
            cli_path = Path(os.path.realpath(cli))
            if any(within(cli_path, p) for p in discovered_apps):
                if not self.args.remove_apps:
                    self.notes.append(f"内置 CLI 随应用保留：{cli}")
            elif not any(within(cli_path, p) for p in self.roots):
                self.notes.append(f"独立 CLI/包管理器安装需按原安装方式卸载：{cli}")
        self.notes.extend([
            "钥匙串、浏览器站点数据、云端内容、其他主机及系统记录未自动清理；见 CLEANUP-NOTES.md。",
            "项目中的 .codex/.agents、共享技能、外部工作目录、安装包与系统备份不自动删除。",
            "直接删除，不创建备份、不移入废纸篓；保留工作文件意味着仍有相关使用痕迹。",
            "config.toml 及 *.config.toml 属于待清理设置；如需保留内嵌指令，请用 --protect 保护该文件。",
        ])
        roots = [p for p in self.roots if not any(p != other and physically_within(p, other) for other in self.roots)]
        if any(physically_within(Path.cwd(), root) for root in roots):
            self.protected[Path.cwd()] = "执行脚本时的当前工作目录"
        for root in sorted(roots, key=str):
            self.inspect_tree(root, root)
        for root in sorted(roots, key=str):
            self.select(root)
        for runtime in {Path(os.path.realpath(sys.executable)), Path(sys.prefix), Path(sys.base_prefix)}:
            if any(physically_within(runtime, p) for p in self.targets):
                self.errors.append(f"Python 运行环境位于待清理目录中，请改用外部 Python 3.11+：{runtime}")

    def inspect_tree(self, p, root):
        if any(physically_within(p, keep) for keep in self.protected):
            return
        # Protect common work-output locations even inside application support
        # or sandbox containers. Installed application resources are not work.
        if (p != root and path_key(Path(p.name)) in {path_key(Path(name)) for name in WORK_NAMES}
                and not any(within(p, app) for app in self.app_roots | self.download_roots)):
            self.protected[p] = "工作目录/生成成果：原地保留"
            return
        st = p.lstat()
        # Sessions, logs and databases have known file formats. Preserve
        # unrelated documents even if they were placed in these state folders.
        for home in self.home_roots | {self.home / ".config/codex"}:
            if not within(p, home):
                continue
            parts = p.parts[len(home.parts):]
            if len(parts) < 2:
                continue
            kind = parts[0]
            known = True
            if kind in {"sessions", "archived_sessions"}:
                known = ((stat.S_ISDIR(st.st_mode) and re.fullmatch(r"\d{2}|\d{4}", p.name))
                         or (stat.S_ISREG(st.st_mode) and re.fullmatch(r"rollout-[A-Za-z0-9_.-]+\.jsonl", p.name)))
            elif kind in {"log", "logs"}:
                known = stat.S_ISREG(st.st_mode) and LOG_RE.fullmatch(p.name)
            elif kind == "sqlite":
                known = stat.S_ISREG(st.st_mode) and SQLITE_RE.fullmatch(p.name)
            elif kind == "shell_snapshots":
                known = stat.S_ISREG(st.st_mode) and re.fullmatch(r"[0-9a-fA-F-]{36}\.sh", p.name)
            if not known:
                self.protected[p] = "状态目录中未识别的内容：原地保留"
                return
        if os.path.ismount(p) or (p != root and st.st_dev != root.lstat().st_dev):
            self.protected[p] = "挂载点/不同文件系统：原地保留"
            return
        if stat.S_ISLNK(st.st_mode):
            # Internal links are removed as links, never traversed. Their target
            # is not an extra deletion candidate. Candidate roots that are links
            # have already been excluded by add()/check_components().
            return
        elif stat.S_ISDIR(st.st_mode):
            if exists(p / ".git") or (exists(p / "HEAD") and is_dir(p / "objects") and is_dir(p / "refs")):
                self.protected[p] = "Git 工作目录/裸仓库：原地保留，保护未提交及未推送成果"
                return
            entries = children(p)
            self.remember_layout(p, entries)
            for child in entries:
                self.inspect_tree(child, root)
        elif not stat.S_ISREG(st.st_mode):
            self.protected[p] = "socket/FIFO/设备等特殊对象：不自动删除"

    def select(self, p):
        if any(physically_within(p, keep) for keep in self.protected):
            return
        if any(physically_within(keep, p) for keep in self.protected):
            if is_dir(p):
                for child in children(p):
                    self.select(child)
            return
        self.targets.append(p)
        self.pins[str(p)] = identity(p.lstat())

    def verify_layout(self, removed=()):
        for p in self.absent:
            if exists(p):
                raise Unsafe(f"计划之后出现新的应用数据，停止并重新核对：{p}")
        for folder, original in self.layout.items():
            if any(within(folder, p) for p in removed):
                continue
            check_components(folder)
            expected = [name for name in original if not any(within(folder / name, p) for p in removed)]
            if [p.name for p in children(folder)] != expected:
                raise Unsafe(f"目录条目与计划不一致，停止继续清理：{folder}")

    def show(self):
        print("计划：直接删除已识别的应用数据，不备份、不移入废纸篓；工作文件保留原地。")
        print(f"待处理 {len(self.targets)} 项；只有 --apply 才执行删除。")
        for p in self.targets:
            print("  删除", quote(p))
        print("\n保留项（包括它们的必要祖先目录）：")
        for p, reason in sorted(self.protected.items(), key=lambda item: str(item[0])):
            if exists(p) and any(physically_within(p, root) or physically_within(root, p) for root in self.roots):
                print("  保留", quote(p), reason)
        print("\n边界与待核对项：")
        for note in dict.fromkeys(self.notes):
            print("  -", note)
        for error in self.errors:
            print("  阻止执行：", error)
        print("\n已按官方文档核对的手工步骤及适用范围：", quote(Path(__file__).with_name("CLEANUP-NOTES.md")))
        print("以下菜单来自官方文档，不表示已核实当前账号的界面或已完成操作：")
        for instruction, source in MANUAL_GUIDE:
            print("  -", instruction)
            print("    官方说明：", source)


def snapshot(root):
    result = {}
    def walk(p):
        before = p.lstat()
        row = {"identity": identity(before), "mode": stat.S_IMODE(before.st_mode)}
        if stat.S_ISLNK(before.st_mode):
            row.update(type="link", target=os.readlink(p))
        elif stat.S_ISDIR(before.st_mode):
            row.update(type="dir")
            for child in children(p):
                walk(child)
        elif stat.S_ISREG(before.st_mode):
            digest = hashlib.sha256()
            fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, "rb") as handle:
                if identity(os.fstat(handle.fileno())) != identity(before):
                    raise Unsafe(f"读取期间文件被替换：{p}")
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            row.update(type="file", size=before.st_size, sha256=digest.hexdigest(), mtime_ns=before.st_mtime_ns)
        else:
            raise Unsafe(f"不能自动处理的特殊文件：{p}")
        row["xattrs"] = {
            name: hashlib.sha256(os.getxattr(p, name, follow_symlinks=False)).hexdigest()
            for name in sorted(os.listxattr(p, follow_symlinks=False))
        }
        if identity(p.lstat()) != identity(before):
            raise Unsafe(f"扫描期间内容发生变化：{p}")
        result[str(p.relative_to(root))] = row
    walk(root)
    return result


def open_directory(p):
    """Pin each ancestor separately; O_NOFOLLOW also applies to ancestors."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for name in p.parts[1:]:
            next_fd = os.open(name, flags, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def remove_planned(root, records, progress):
    """Delete only recorded objects; never expand the plan during deletion."""
    tree = {}
    for relative, row in records.items():
        if row["type"] == "dir":
            tree[relative] = []
    for relative in records:
        if relative != ".":
            key = str(Path(relative).parent)
            tree[key].append(Path(relative).name)
    for names in tree.values():
        names.sort()

    def walk(parent_fd, name, relative):
        row = records[relative]
        path = root if relative == "." else root / relative
        before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if identity(before) != row["identity"]:
            raise Unsafe(f"删除前对象被替换或修改：{path}")
        if row["type"] == "dir":
            fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
            try:
                if identity(os.fstat(fd)) != row["identity"]:
                    raise Unsafe(f"打开时目录被替换：{path}")
                remaining = set(tree[relative])
                for child in tree[relative]:
                    # Our own deletions change directory mtime/ctime. Match the
                    # stable object identity and exact remaining names instead.
                    if identity(os.fstat(fd))[:3] != row["identity"][:3] or set(os.listdir(fd)) != remaining:
                        raise Unsafe(f"目录出现计划外变化，保留剩余内容：{path}")
                    current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                    if not os.path.samestat(current, os.fstat(fd)):
                        raise Unsafe(f"目录位置发生变化：{path}")
                    walk(fd, child, str(Path(relative) / child))
                    remaining.remove(child)
                if os.listdir(fd):
                    raise Unsafe(f"目录出现新文件，拒绝递归扩大删除：{path}")
                if not os.path.samestat(os.stat(name, dir_fd=parent_fd, follow_symlinks=False), os.fstat(fd)):
                    raise Unsafe(f"删除空目录前位置发生变化：{path}")
                os.rmdir(name, dir_fd=parent_fd)
            finally:
                os.close(fd)
        else:
            if row["type"] not in {"file", "link"}:
                raise Unsafe(f"未识别的计划对象：{path}")
            # Only unlink this exact name through the pinned parent; links are
            # never followed. No rmtree, rename, copy, trash, or backup fallback.
            os.unlink(name, dir_fd=parent_fd)
        progress["deleted"] += 1
        progress["last"] = str(path)

    check_components(root, allow_leaf_link=True)
    parent_stat = root.parent.lstat()
    parent_fd = open_directory(root.parent)
    try:
        if not os.path.samestat(os.fstat(parent_fd), parent_stat):
            raise Unsafe(f"目标父目录被替换：{root.parent}")
        walk(parent_fd, root.name, ".")
    finally:
        os.close(parent_fd)


def require_stopped():
    result = subprocess.run(["/bin/ps", "-axo", "uid=,pid=,comm="], capture_output=True, text=True)
    if result.returncode or not result.stdout.strip():
        raise Unsafe("无法可靠检查运行中的进程，停止清理。")
    found = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 2)
        if len(fields) == 3 and fields[0] == str(os.getuid()) and PROCESS_RE.search(fields[2]):
            found.append(f"PID {fields[1]}: {fields[2]}")
    if found:
        raise Unsafe("请先退出以下进程（不会强制结束它们）：\n" + "\n".join(found))


def apply(plan):
    if plan.errors:
        raise Unsafe("计划存在未解决的错误，没有执行删除。")
    if not plan.targets:
        print("没有可自动处理的对象；保留项和人工核对项仍需检查。")
        return 2
    require_stopped()
    if not plan.args.yes:
        if not sys.stdin.isatty():
            raise Unsafe("非交互终端需要显式 --apply --yes；未执行清理。")
        if input("\n上述数据将直接删除，不备份、不移入废纸篓。输入 DELETE 确认：") != "DELETE":
            print("未确认，没有修改任何文件。")
            return 0
    require_stopped()
    plan.verify_layout()
    source_snapshots = {}
    # Finish the read-only preflight for every target before the first unlink.
    for p in plan.targets:
        check_components(p, allow_leaf_link=True)
        if identity(p.lstat()) != plan.pins[str(p)]:
            raise Unsafe(f"预览后目标发生变化，请重新审阅：{p}")
        source_snapshots[str(p)] = snapshot(p)
    require_stopped()
    plan.verify_layout()
    removed = []
    progress = {"deleted": 0, "last": None}
    current = None
    try:
        for p in plan.targets:
            current = p
            require_stopped()
            plan.verify_layout(removed)
            check_components(p, allow_leaf_link=True)
            if snapshot(p) != source_snapshots[str(p)]:
                raise Unsafe(f"删除前目标发生变化，停止后续操作：{p}")
            remove_planned(p, source_snapshots[str(p)], progress)
            removed.append(p)
            if exists(p):
                raise Unsafe(f"目标仍存在或被重新创建：{p}")
            print("已直接删除：", quote(p))
        require_stopped()
        plan.verify_layout(removed)
        residuals = [str(p) for p in plan.targets if exists(p)]
        if residuals:
            raise Unsafe("复核发现目标重新出现：" + repr(residuals))
    except BaseException:
        print(f"操作停止：已完整处理 {len(removed)} 个目标，已删除 {progress['deleted']} 个文件/目录/链接。", file=sys.stderr)
        if current is not None:
            print("当前目标可能仅部分清理：", quote(current), file=sys.stderr)
        if progress["last"]:
            print("最近已删除对象：", quote(progress["last"]), file=sys.stderr)
        print("没有备份、恢复区或自动回滚；尚未处理的对象保持原位。", file=sys.stderr)
        raise
    print("本次本地计划已完成；工作文件保留原地，未创建备份。")
    print("人工核对项未自动清理；不保证所有安装/使用痕迹消失，也不属于磁盘安全擦除。")
    return 0


def parse_args():
    parser = argparse.ArgumentParser(description="macOS ChatGPT/Codex 本地重置。默认只预览；--apply 直接删除已识别状态，不备份，工作文件保留。")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="直接删除已识别数据，不备份、不移入废纸篓；默认不执行")
    mode.add_argument("--dry-run", action="store_true", help="只读预览，不创建备份，不打开网页（默认）")
    parser.add_argument("--yes", action="store_true", help="配合 --apply 跳过确认；不会跳过安全检查")
    parser.add_argument("--remove-apps", action="store_true", help="纳入 /Applications 和 ~/Applications 中已验证的 ChatGPT/Codex 应用包")
    parser.add_argument("--no-open", action="store_true", help="兼容旧参数；新版始终不自动打开网页")
    parser.add_argument("--codex-home", action="append", default=[], metavar="PATH", help="另一个 Codex 数据根目录，可重复；保护工作树")
    parser.add_argument("--sqlite-dir", action="append", default=[], metavar="PATH", help="额外数据库目录；仅处理识别出的 Codex 文件")
    parser.add_argument("--log-dir", action="append", default=[], metavar="PATH", help="额外日志目录；仅处理识别出的 Codex 日志")
    parser.add_argument("--protect", action="append", default=[], metavar="PATH", help="原地保留的文件/目录，可重复")
    args = parser.parse_args()
    if args.yes and not args.apply:
        parser.error("--yes 必须显式配合 --apply；默认预览不会删除。")
    return args


def main():
    args = parse_args()
    if sys.platform != "darwin":
        raise Unsafe("仅支持 macOS；没有修改文件。")
    plan = Plan(args)
    plan.discover()
    plan.show()
    if not args.apply:
        print("\n只读预览结束：没有创建备份、修改文件、打开网页或执行删除。")
        return 1 if plan.errors else 0
    return apply(plan)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, Unsafe) as error:
        print(f"停止：{error}", file=sys.stderr)
        raise SystemExit(1)

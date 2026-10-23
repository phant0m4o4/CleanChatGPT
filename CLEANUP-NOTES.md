# 手工检查与清理边界

核对日期：2026-10-23。下面的“文档已核实”表示已实际打开所链接的 OpenAI 官方页面核对，不表示已检查当前账号或已验证本机版本的界面。核对未执行脚本、删除操作或删除测试。

菜单名称保留官方英文，以免译名与界面不一致。若当前版本、套餐或工作区没有相应入口，应按实际界面继续确认，不应套用其他产品的步骤。未从所查官方页面确认的按钮、批量操作和系统残留，均明确标为未核实。

## 一次 macOS 环境的只读核对结果

以下是开发时检查的环境样本，不代表每台机器均有这些路径或采用相同安装方式。仅检查了路径名称和应用元数据，没有运行应用或清理脚本、没有读取凭据或文稿内容：

- `~/Documents/ChatGPT` 与 `~/Documents/Codex` 均存在，包含项目目录或按日期组织的目录，应按工作内容保护。
- `/Applications/ChatGPT.app` 的 `CFBundleIdentifier` 为 `com.openai.codex`，因此不能只凭应用名称假定它使用 `com.openai.chat`。
- 当前 `PATH` 中的 `codex` 指向 `/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex`，属于该应用内置 CLI。未清点其他位置可能存在的 CLI 安装或 IDE 扩展。
- 本轮没有现场核实账号设置页面、钥匙串项目或云端数据。下面的操作说明以官方文档为依据。

## “清理完成”不等于“从未安装”

本说明的工程边界是：本地文件清理不能证明其他电脑、云端服务、备份或系统记录都已清空，也不能证明历史数据不可恢复。因此，脚本不能保证电脑恢复成“从未安装过 ChatGPT/Codex”的状态。这是对清理范围的限制，不是断言当前电脑一定存在上述残留。

本脚本不创建备份、复制件、恢复快照或清单文件；受保护的工作文件原位保留。“保留工作文件”与“移除所有历史痕迹”仍有区别：代码仓库、生成的文档、导出的聊天、截图和下载文件本身可能包含使用记录。保留这些成果时，不能同时宣称所有历史内容都已移除。不要为了追求零痕迹，按 `openai`、`chatgpt`、`codex` 等关键词递归删除文件。

尤其要区分配置缓存与实际工作内容。官方说明 Codex 自身管理工作树时可能在删除前保存快照，删除工作树后聊天仍可留在历史中；永久工作树也不会随聊天归档自动删除。这描述的是 Codex 的行为，不是本清理脚本提供的备份或恢复机制。工作目录、工作树和输出文件应先确认是否为需要保留的成果，不能仅凭目录名决定删除。[Worktrees](https://learn.chatgpt.com/docs/environments/git-worktrees)

## 账号、聊天与云端内容

- **Chat / Work / Codex 聊天——文档已核实**：Work 历史与 Codex 历史分开。桌面应用的设置文档说明 `Archived chats` 用于列出归档聊天，并提供 `Unarchive` 恢复；Codex App Server 文档另有删除活动或归档线程的能力。后者是协议能力，不能作为桌面界面有相同按钮的证据。**未核实**：当前账号的“删除全部聊天”入口及覆盖范围、归档页的批量删除按钮。应分别确认普通／项目、活动／归档、Chat／Work／Codex 以及本地／云端记录，不提供未经核实的一键删除路径。[项目和聊天](https://learn.chatgpt.com/docs/projects)、[桌面设置](https://learn.chatgpt.com/docs/app/settings)、[Codex 聊天生命周期](https://learn.chatgpt.com/docs/app-server)
- **ChatGPT 云端 Memory——文档已核实**：官方给出的管理入口是 `Settings > Personalization`；ChatGPT Work 使用账号及工作区可用的记忆设置，和 Codex 本地记忆分开。删除聊天不一定删除已有保存记忆。**未核实**：当前账号更深层的菜单名称、`Delete all` 按钮或开关组合；不把关闭功能写成已删除历史记忆。[Memories](https://learn.chatgpt.com/docs/customization/memories)、[Work 数据保留说明](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security)
- **Codex 本地 memories——文档已核实**：`Settings > Personalization` 中的 `Enable Codex memories` 针对所选机器；官方还说明可用 `Delete Codex memories` 重置该机器的记忆。本机执行此操作也会清除可用的 Computer History；IDE 使用所连接 host 的记忆。**限制**：这些控件能否出现在当前版本尚未现场确认；不能据此推断其他机器或 ChatGPT 云端记忆已清理。[Memories](https://learn.chatgpt.com/docs/customization/memories)
- **Computer History——文档已核实**：功能可用时，官方入口为 `Settings > Computer history > History`，可删除单条时间线项目或清除指定时间范围／全部历史；清除会删除相关事件及其生成的记忆。此功能是否在当前账号启用，**未核实**。[Computer History](https://learn.chatgpt.com/docs/customization/computer-history)
- **Library / Space / Pages / Trash——文档已核实**：Enterprise 管理文档将 Space 描述为 formerly Library，并说明删除 Page 或 Space 会将其及嵌套页面移入 Trash；独立保存的 Space 文件不会随聊天或项目删除。**适用范围和未核实项**：这不能证明所有账号的 Library 都已更名，也未证明当前界面有 `Recently deleted`、`Delete all` 或清空回收站按钮。按账号实际提供的 Library／Space 检查自己保存的内容；永久删除入口需界面确认，不套用别处的按钮名称。[Space 管理与删除说明](https://learn.chatgpt.com/docs/enterprise/chatgpt-space)
- **Projects——文档已核实**：项目文件会保留到被移除或项目被删除，独立保存在 Library 的文件另行管理。本地项目目录与云端项目来源不同。**未核实**：当前账号的删除项目按钮及是否覆盖全部相关副本；从侧边栏移除入口也不能作为磁盘文件已删除的验证。保留源码或文档时不要删除对应目录。[项目和聊天](https://learn.chatgpt.com/docs/projects)、[项目文件的保留范围](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security)
- **Shared links——文档已核实**：Codex 共享快照是分享时的内容，后续变化不更新旧快照；官方指定在 ChatGPT data controls 中选择 `Shared links` 查看或撤销链接。**未核实**：当前版本后续是否叫 `Manage` 或 `Delete all shared links`；不再给出这些按钮路径。[Codex 共享快照](https://learn.chatgpt.com/docs/use-chatgpt)
- **插件和连接应用——文档已核实**：在支持的插件浏览器中，若有 `Uninstall plugin`，可用其移除插件；工作区安装或默认插件可能由管理员控制。卸载插件不自动断开单独连接的 MCP 集成。断开应用连接也不自动删除已保存内容。**未核实**：当前账号各连接的断开入口，以及第三方服务侧的授权撤销菜单；这些需要逐项确认，不能把卸载、断开、撤销第三方授权和删除保存内容当作同一步。[插件卸载](https://learn.chatgpt.com/docs/plugins)、[断开连接与保存内容](https://learn.chatgpt.com/docs/enterprise/chatgpt-space)
- **Cloud browser——文档已核实**：这是与本机浏览器分开的浏览器环境。官方清除路径是 `Settings > Cloud browser > Browser data > Clear all`，会退出该云端浏览器内的网站登录。功能受套餐、工作区设置和发布范围影响；当前账号是否有此入口**未核实**，没有入口时不能代换成清空本机浏览器。[Browser：Privacy and browser data](https://learn.chatgpt.com/docs/browser)
- **云端保留期限——文档已核实**：Work 文档说明已删除聊天通常安排在 30 天内永久删除，并有安全、法律和去标识化例外；托管执行状态及快照使用独立生命周期，结束任务或删除聊天不立即清除全部关联产物。不能将该期限扩写为“所有 Codex 历史、文件、快照都已在 30 天内清空”。[Work 数据处理与保留](https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security)

以上核对应覆盖实际使用过的账号和工作区。组织工作区的内容可能受管理员权限和保留规则管理；本地脚本无法证明这些云端清理已经完成。

## 本机登录、浏览器和系统设置

- **钥匙串——文档已核实的范围**：Codex 凭据可以存在 `CODEX_HOME/auth.json` 或操作系统凭据存储中，由 `cli_auth_credentials_store` 等配置决定。**未核实**：本机实际采用哪种存储，以及各版本具体钥匙串服务名／账号名；不能仅凭文档生成通用删除名单。手工处理时只检查能够确认归属的单条凭据，不清空整个钥匙串，不打印凭据内容。[Authentication：Credential storage](https://learn.chatgpt.com/docs/auth)
- **桌面应用内置浏览器——文档已核实**：其 profile 与常用浏览器分开。官方管理入口是 `Settings > Browser`，`Clear browsing data` 可选择时间范围及数据类型，受组织许可限制。它与 `Cloud browser` 的路径不同；当前本机界面是否提供这些控件**未核实**。[Browser：Manage browsing history](https://learn.chatgpt.com/docs/browser)
- **Safari／Chrome／Edge／Firefox 等个人浏览器——本机检查建议，非已核实删除步骤**：OpenAI 认证文档确认 ChatGPT 网页会话存在浏览器中，但未提供这些浏览器当前版本的删除菜单或完整站点清单。`chatgpt.com`、`chat.openai.com`、`openai.com` 仅作辨认相关记录的候选，不能断言都存在或足以覆盖全部登录数据。按实际个人资料与站点归属核对，不清空整个个人资料；不声称 Cookie 会跨设备同步。[ChatGPT 网页认证](https://learn.chatgpt.com/docs/auth)
- **系统权限与通知——文档已核实的范围**：官方要求在 macOS `Privacy & Security` 中调整 Screen Recording／Accessibility 来撤销对应系统权限；应用自身也有通知设置。**未核实**：本机当前权限／通知条目、登录项和后台服务的存在情况、卸载后是否保留，以及确切系统条目名称。LaunchAgent／LaunchDaemon 只是按实际安装情况检查的候选，不是已确认残留；不能整目录删除或按模糊关键词卸载服务。[应用设置](https://learn.chatgpt.com/docs/app/settings)

这些检查可能影响本机其他程序或仍在使用的登录会话，必须按确切对象处理，不能通过扩大删除通配符来代替确认归属。

## 其他电脑、安装来源与备份

- **Remote hosts 与设备配对——文档已核实**：远程工作使用目标 host 的项目、聊天、文件、凭据及工具。官方指定在 host 的 `Settings > Connections` 管理连接设备，并明确退出 ChatGPT 仅关闭 Remote Control，不移除现有配对。**未核实**：当前账号的已配对设备、删除配对按钮名称及其他主机的数据；需要在相应机器确认。不要为清理一个连接而删除整个 `~/.ssh`、共享私钥或其他主机配置。[Remote connections](https://learn.chatgpt.com/docs/remote-connections)
- **安装来源——文档已核实**：官方 CLI 页面列出独立安装器、npm、Homebrew 等安装方式；IDE 页面区分 VS Code 兼容扩展及 Xcode／JetBrains 集成。**未核实**：本机采用的方式、多份安装、准确卸载命令和扩展卸载菜单。只按已识别的安装对象和对应管理器处理，不删除 npm 全局目录、Homebrew 前缀、IDE 扩展总目录或共享依赖。[CLI 安装](https://learn.chatgpt.com/docs/codex/cli)、[IDE 集成](https://learn.chatgpt.com/docs/codex/ide)
- **既有备份、同步服务、快照与导出副本——未核实的外部范围**：本次未检查 Time Machine、iCloud 等同步服务、第三方备份产品、文件系统快照、外置盘、下载目录或聊天导出，也未从所查 OpenAI 文档确认它们的清除步骤。这些是用户原有的独立服务或文件，不是本脚本创建的备份；是否存在相关内容、同步删除或历史版本需按实际服务确认。不能清空整个备份盘或批量删除快照来代替本应用清理。此项为工程边界说明，不是 OpenAI 产品行为结论。

本说明不提供自动清空上述对象的命令。保留的工作内容、归属未确认的对象和受外部保留政策管理的数据，不能视为已清除；本脚本也不为这些对象生成备份或恢复清单。

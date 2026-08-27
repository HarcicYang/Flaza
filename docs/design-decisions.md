# Flaza 设计决策记录

本文档记录项目级设计决策，作为后续开发的一致依据。新增决策前应先充分讨论。

## 协作与提交约定

- 项目文档统一使用简体中文。
- 未经明确允许不修改代码；新设计、新功能必须先充分讨论。
- 所有 git 操作（包括 commit、push、fetch、pull、rebase 等）必须单独经过同意。
- 提交信息使用 Conventional Commits。

## 已确认设计决策

### 1. 架构与运行模型

- 单账号优先，暂不预埋多账号复杂抽象。
- Lagrange 与 Neony 共享同一个 asyncio 事件循环：
  - 在 Neony 的 ready 阶段启动 QQ 运行时任务；
  - UI 回调、核心服务、QQ 协议适配全部使用普通 `await`。
- 协议适配目录命名为 `qq/`，是唯一允许导入 `lagrange` 的模块。
- `core.ports` 是唯一协议边界：
  - `core` 只依赖端口接口；
  - `qq` 实现端口；
  - `ui` 与 `app` 只依赖 `core`；
  - 具体实现只在应用组装根注入。
- 入站事件先使用单 `asyncio.Queue`，由单消费者协程按到达顺序处理；
  后续如有性能需要，再演进为入口队列加按会话分片或批量写入。

### 2. 登录方案

- 只实现静默登录和二维码登录，暂不实现密码登录。
- `qq` 层基于 `Client.fetch_qrcode()` 和 `Client.get_qrcode_result()` 自行编排登录流程，
  不直接使用 `Lagrange.run()` 的登录流程。
- 二维码在 UI 内展示，状态机覆盖：
  - 等待扫码；
  - 等待确认；
  - 已确认；
  - 已过期；
  - 已取消。

### 3. 配置管理

- 配置格式沿用 EulerOneBot 的 `appconfig.json` 风格。
- `appconfig.json` 是程序生成和持久化的文件，而不是要求用户手工维护的文件。
- 所有面向用户的配置项都应在 UI 的设置界面中完成修改。
- 用户不应手工编辑 `appconfig.json`；UI 是唯一受支持的配置修改入口。
- 程序在首次启动时生成带默认值的配置文件，在 UI 保存后由程序写回，保证字段和格式合法。

### 4. 模型、消息与发送接口

- 领域模型统一优先使用 pydantic。
- 协议发送端口使用通用 `send_message(target, elements)`，不在端口层提供 `send_text`。
- `Message.elements` 使用 list，是消息的事实来源。
- `Message.text` 是派生属性，用于列表预览、通知和搜索摘要。
- 每个消息元素都提供自己的预览文本，未来图片、表情、At 等沿用此约定。

### 5. 存储

- 业务数据统一使用异步 SQL（aiosqlite），连接管理抽象参考 EulerOneBot。
- 消息完整 pydantic 模型使用 msgpack 编码为版本化 BLOB，存于 `messages.payload`。
- 查询所需字段从模型中冗余到 SQL 列，读取时仍以 payload 还原 pydantic 模型。
- 消息分页使用本地自增 id 做 keyset 分页，不使用 OFFSET。
- 会话列表由 `messages`、`friends`、`groups` 和 `read_cursors` 派生查询，不建会话实体表。
- 未读数使用本地 `messages.id` 游标计算。
- UI 分页使用 `StoredMessage(id, message)`，领域事件仍只传 `Message`。

### 6. 群事件与身份标记

- 第一批结构化群事件：撤回、群名变更、成员加入/退出、管理员变更、禁言。
- 事件先持久化再派生为聊天流灰条，不压成普通消息文本。
- `Message` 增加 `recalled`、`sender_is_bot`、`sender_role`。
- 群成员身份缓存到 `group_members` 表，登录后后台同步。
- 群聊消息名字旁显示身份 Badge：群主 accent、管理员 success、机器人 neutral。

### 7. MVP UI

- 页面流：配置不完整时显示 SetupPage；配置完整时显示 LoginPage；登录成功后切换到 HomePage。
- 窗口统一使用 Neony TitleBar 自定义标题栏，系统原生标题栏关闭（`decorations=False`）。
- 标题栏同时承载应用名、账号信息、连接状态和主界面操作按钮，不再单独绘制应用头部；标题栏图标使用当前账号头像。
- 登录只做静默登录和二维码登录，二维码以 data URL 内嵌显示。
- 主界面为左侧两行式会话列表 + 右侧消息气泡流和单行输入框。
- 通过 NewChatDialog 选择好友或群发起没有历史消息的新会话。
- 登录配置只在 UI 中修改；保存后写回 `appconfig.json` 并自动重启应用，MVP 不做运行时重配 QQClient。
- 配置保存后的应用重启使用 `os.execv`，适用于当前开发运行方式。
- 连接断开不切回登录页，只在主界面显示连接状态。
- 输入框回车发送，MVP 不提供多行编辑。
- 消息流和会话列表通过领域事件刷新；消息滚动使用 Neony 滚动组件的公开滚动 API。
- 登录流程和离线消息同步期间使用 Neony Progress 显示加载动画。
- 头像通过 QQ 公开头像服务按 uin / group_id 生成 URL，不持久化头像图片。
- 登录成功后补拉离线消息：已有会话按本地最大 seq 续拉（默认最多 500 条）；尚无会话记录的好友和群也拉取最近消息（默认 50 条），以发现离线期间新产生的会话。

### 8. 图片 / 文件发送与历史消息加载

- 图片发送沿用通用 `send_message(target, elements)`：领域层构造带
  `local_path` 的 `ImageElement`，QQ 层识别后上传到对应会话，并返回
  上传后的 `ImageElement` 作为持久化元素；`local_path` 不落库，
  但发送成功后会暂时把原图路径写入 `cached_path`，让本地气泡立即
  渲染，不依赖 CDN 直链。
- 输入栏是一个图文块编辑器：文本块与图片块按顺序渲染，可点击选中、
  前移、后移、删除；`+` 入口的「插入图片」「新增文字」都插入到当前
  选中块之后，发送时按块顺序组装 `MessageElement`。
- 剪贴板粘贴同时支持图片 bytes、本地文件路径、`file://` URL 与带
  扩展名的 http(s) URL；下载得到的临时文件优先清理。
- 消息区拖拽 drop 由页面根节点统一接收：图片进入图文块编辑器，
  非图片文件立即发送；拖动期间显示全屏遮罩提示。
- 文件发送走独立的端口方法 `send_file(target, path, filename)`：
  lagrange 好友文件与群文件走不同协议通道，且好友文件上传即发送。
  两个通道都不直接返回协议 seq，因此发送前记录会话最新 seq，发送
  后轮询等待会话 seq 前进，再与文件元素组装为领域消息持久化；
  发送后主动拉取文件下载链接，保证自己发送的文件卡片可点击。
- 更早历史消息通过 `list_before()` 分页；`MessageList` 在滚动到
  顶部时自动触发加载，识别“前缀新增”并增量插入 DOM，不做全量
  重建，也不使用 JavaScript 滚动补偿。
- 文件卡片提供「下载」按钮，右键菜单也提供「下载文件」；下载走
  Neony 原生保存对话框，成功后 Toast 提示路径。
- 消息气泡右键菜单使用 Neony `MessageBubble` 内建 Menu：当前提供
  复制文本、下载文件与撤回自己发送的消息。
- 图片预览画布占满预览区域：缩放后图片不再受原图显示区域限制，
  可在整个画布内平移查看。

### 9. 插件系统（M1 基础已实现）

- 插件以目录 + `manifest.json` 分发；插件元数据与配套配置只使用 JSON，
  不使用 YAML。
- 插件目录建议为 `plugins/<plugin_id>/`，入口模块由 `entry` 指定；
  插件加载进 Flaza 进程，默认不设沙箱、不做权限墙。
- 安全模型：插件拥有当前用户完整权限，安全责任由插件开发者和使用者承担；
  Flaza 只对可捕获异常做错误隔离，并负责插件任务的退出清理，不承诺防御
  插件主动退出、死循环、耗尽内存或恶意系统调用。
- 插件拥有完整访问通道：`PluginContext.runtime` 暴露 `ApplicationRuntime`，
  可继续访问 Storage、EventBus、服务、QQ 客户端、Shell 与 Neony 应用；
  插件也可以直接 `import flaza.*` / `import neony.*`。稳定便利 API 承诺
  兼容，内部结构允许使用但不承诺长期稳定。
- 生命周期：`PluginHost` 负责发现、校验、加载、启动、停止与任务清理；
  启动时机在存储和 EventBus 就绪后、`start_qq()` 之前，退出时先于
  QQ 与服务停止。
- 依赖：`manifest.json` 的 `dependencies` 记录 PEP 508 字符串；启动时
  仅检查并警告缺失或版本不匹配，不阻止加载，也不自动安装。
- 状态与 KV：插件启停状态、设置与 KV 持久化到根目录 `plugin_state.json`。
- 消息拦截：收发路径增加可注册过滤器。入站过滤在持久化和 UI 投影前
  执行，可改写或吞掉消息；出站过滤在调用 QQ 前执行，可改写目标与元素
  或中止发送。
- 消息段扩展：核心加入通用 `PluginElement(plugin_id, element_type, payload,
  preview_text)`，作为 `MessageElement` 联合的一类；插件注册渲染器、发送器
  与预览文本，插件缺失时回退占位卡。V1 不做动态重建 discriminated union。
- 事件扩展：插件可以自定义 `FlazaEvent` 子类并通过 `ctx.publish` /
  `ctx.subscribe` 使用；`EventBus` 增加优先级，支持 `ctx.before_event` /
  `ctx.after_event`，使插件能赶在内置服务之前处理事件。
- 操作钩子：提供 `ctx.before_recall` 等动作前置钩子；用户主动撤回时可在
  调用 QQ API 之前中止。
- UI 扩展：标题栏按钮、消息快捷动作、右键菜单项与设置页插件面板作为固定
  挂点；插件通过 `PluginContext` 公开能力接入这些挂点，不直接操作 DOM、
  页面或 JavaScript。
- 撤回示例确认：收到撤回事件后，插件可用 `ctx.before_event(MessageRecalled,
  ...)` 改写本地消息（例如保留原元素并追加“（已撤回）”标记，或启用保留
  内容渲染字段）后吞掉事件；若想真正阻止用户主动撤回，应在 `ctx.before_recall`
  中中止，而不是依赖撤回事件处理。
- M1 已落地：`PluginDiscovery`/`PluginManifest` 负责发现与 JSON 校验，
  `PluginState` 以根目录 `plugin_state.json`（`enabled`、`disabled`、`settings`、
  `kv`）持久化，`PluginHost` 在存储与 EventBus 就绪后启动、退出时先于 QQ 停止；
  插件入口导出模块级 `plugin` 实例，插件目录以 `flaza_plugin_<id>` 命名空间包
  动态导入，支持插件内相对导入与跨插件包导入；每次加载或重新加载都会清理旧
  模块缓存，并从磁盘上的入口文件直接重建模块，编辑插件代码后无需重启应用。
- M1 已落地的事件扩展：`EventBus` 支持优先级排序以及 `subscribe_before` /
  `subscribe_after`；`PluginContext` 提供 `publish`、`subscribe`、
  `before_event`、`after_event`，前置处理器可返回替换事件或用 `None` 吞掉事件。
- M2 已落地：`PluginExtensionRegistry` 集中管理出站过滤器、撤回钩子与消息段
  扩展，注册句柄可单独 `dispose`；`PluginContext` 提供 `filter_outgoing_message`、
  `filter_outgoing_file`、`before_recall` 与 `register_element` 便利 API。
- M2 已落地的出站拦截：`MessageService` 在调用 QQ 之前按注册顺序执行出站消息
  与文件过滤器，可改写目标、元素或文件参数，返回 `None` 则中止发送；单个
  过滤器异常只记录日志并跳过，不阻塞整条发送路径。
- M2 已落实的撤回钩子：用户主动撤回前执行 `before_recall`，任一钩子返回
  `False` 时不调用 QQ API；收到撤回事件仍走 `before_event` 改写本地消息，
  两条路径职责分离。
- M2 已落地的消息段扩展：核心模型加入 `PluginElement`；插件可为自己的
  `plugin_id + element_type` 注册 `renderer` 与 `sender`。`renderer` 返回 UI
  元素，未注册或异常时回退占位卡；`sender` 返回协议元素与持久化领域元素，
  `LagrangeQQClient` 在发送路径自动调用，缺失或失败时抛出明确错误。
- M2 已落地的撤回保留渲染：`Message.retain_content_on_recall` 为 `True` 时
  本地气泡保留原内容；`MessageRepository.replace_message` 允许插件在同一会话
  同一 seq 上替换完整领域模型，旧数据库会在启动时自动迁移 `sender_uid` 列。
- M2 示例插件：`examples/plugins/recall-keep/` 提供可直接复制到 `plugins/`
  的撤回保留插件，演示 `before_event` 拦截、`replace_message` 改写本地消息、
  吞掉事件并主动刷新 UI。
- M2 已落地的 UI 接入与卸载清理：`HomePage`、`MessageList` 与
  `build_message_content` 透传插件注册表渲染自定义消息段；`PluginHost.stop`
  依次调用 `on_unload`、退订事件、移除插件扩展注册并取消托管任务。
- M2 已落地的插件管理 UI：设置页新增插件目录输入与原生目录选择入口，
  并提供独立的「插件管理」页面；页面列出已发现插件，显示启用/加载状态，
  支持逐个启用或禁用、重新加载与目录热切换，无需重启应用。
- M3 已落地的消息快捷动作扩展：`PluginExtensionRegistry` 增加
  `register_message_action`，插件可为气泡 actions 注册带独立命名空间的
  按钮；`MessageList` 按注册顺序渲染，`HomePage` 路由到
  `run_message_action`，未注册或异常时在 UI 显示操作失败。
- M3 示例插件：`group-notices/` 演示接管群事件并写入详细播报；
  `plus-one/` 演示消息快捷动作与整元素序列复读；
  `custom-theme/` 演示用 `ctx.apply_theme` 切换内置主题。

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
- 消息流和会话列表通过领域事件刷新；消息滚动使用 `eval_js` 滚动到底部。
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

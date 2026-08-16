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

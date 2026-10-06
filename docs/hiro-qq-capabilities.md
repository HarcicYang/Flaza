# hiro-qq 能力与事件审计

> 目标：盘点 hiro-qq 暴露、且 QQ 用户理应获得的协议能力，标注 Flaza 的接入
> 状态与 UI 落点。所有能力都在应用进程内复用既有 asyncio 事件循环与协议
> 连接，不新增监听端口、独立服务或额外常驻进程。

状态说明：

- ✅ 已接入并可在 UI 使用
- 🔔 已接入为聊天流灰条（信息型事件）
- 🚧 已实现协议动作，UI 入口部分可用
- 📋 已审计，尚未实现
- ⏸ 需要额外素材或风险较高，暂缓

## 事件审计

| hiro-qq 事件 | 关键字段 | 用户价值 | 现状 | UI 落点 |
| --- | --- | --- | --- | --- |
| `FriendMessage` | seq/rand/timestamp/msg_chain | 好友消息 | ✅ | 聊天流 |
| `FriendRecall` | seq/rand | 好友撤回 | ✅ | 消息原位标记 |
| `FriendRequest` | from_uid/message/source | 好友申请 | ✅ | 通知中心 |
| `FriendPoke` | sender/target/action/suffix | 好友戳一戳 | 🔔🚧 | 灰条 + 消息菜单「戳一戳」 |
| `FriendRequestFinished` | result | 申请处理结果 | ✅ | 通知中心 |
| `FriendAddNotify` | status/source | 已成为好友 | ✅ | 通知中心 + 好友列表刷新 |
| `GroupMessage` | seq/rand/msg_chain | 群消息 | ✅ | 聊天流 |
| `GroupRecall` | operator_id/seq | 群撤回 | ✅ | 消息原位标记（含操作者） |
| `GroupNudge` | sender/target/action | 群戳一戳 | 🔔🚧 | 灰条 + 消息菜单「戳一戳」 |
| `GroupSign` | uin/nickname/timestamp | 群打卡 | 🔔 | 灰条 |
| `GroupMuteMember` | operator/target/duration | 禁言 | ✅ | 灰条 |
| `GroupMemberJoinRequest` | grp_id/uid/answer | 入群申请 | ✅ | 通知中心（打开时拉取完整参数） |
| `GroupAdminChange` | uid/is_set | 管理员变更 | ✅ | 灰条 + 身份角标 |
| `GroupMemberJoined` | uid/join_type | 成员加入 | ✅ | 灰条 |
| `GroupMemberQuit` | uid/uin/exit_type/operator | 成员退出/被踢 | ✅ | 灰条 |
| `GroupMemberGotSpecialTitle` | member_uin/special_title | 专属头衔 | 🔔 | 灰条 |
| `GroupNameChanged` | name_new/operator_uid | 群名变更 | ✅ | 灰条 + 群列表刷新 |
| `GroupReaction` | seq/emoji/count/uid | 表情回应 | ✅ | 消息表情条 |
| `GroupAlbumUpdate` | timestamp/image_id | 群相册更新 | 🔔 | 灰条 |
| `GroupInvite` | invitor_uid | 群邀请 | ✅ | 通知中心（打开时拉取完整参数） |
| `GroupMemberJoinedByInvite` | invitor_uin/uin | 邀请入群 | 🔔 | 灰条 |
| `GroupSelfJoined` | op_uid | 你入群 | 🔔 | 灰条 + 群列表刷新 |
| `GroupSelfRequireReject` | message | 入群被拒 | 🔔 | 灰条 |
| `GroupBotAdded` | bot_uid | 机器人入群 | 🔔 | 灰条 |
| `GroupBotJoined` | opqq_uin/robot_name | 添加机器人 | 🔔 | 灰条 |
| `BotGrayTip` | content | 机器人灰条 | 🔔 | 灰条 |
| `ClientOnline` | - | 连接成功 | ✅ | 连接状态 |
| `ClientOffline` | recoverable | 断线 | ✅ | 连接状态 |
| `ServerKick` | title/tips | 被踢下线 | ✅ | 连接状态 + 提示 |
| `OtherClientInfo` | clients | 其它在线端 | ✅ | 设置页「其它在线端」 |

## 客户端能力审计

### 消息

| 能力 | hiro-qq API | 现状 | UI 落点 |
| --- | --- | --- | --- |
| 发送文本/图片/文件 | `send_*_msg` / `upload_*` | ✅ | 输入区、拖拽、粘贴 |
| 发送语音 | `upload_*_audio` | ✅ | 文件选择/拖拽按扩展名识别（amr/silk/mp3/m4a/wav/ogg；服务端可能要求特定编码） |
| 发送视频 | `upload_*_video` | ✅ | 文件选择/拖拽按扩展名自动识别 |
| 撤回消息 | `recall_*_msg` | ✅ | 气泡右键菜单 |
| 表情回应 | `send_grp_reaction` | ✅ | 消息快捷动作 |
| 戳一戳 | `send_nudge` | 🚧 | 气泡右键菜单 |
| 合并转发/展开 | `upload`/`send_*_forward_msg`、`get_forward_msg` | ✅ | 卡片点击展开、单条转发、菜单多选转发 |
| 设置精华消息 | `set_essence` | ✅ | 气泡右键菜单（群主/管理员） |
| 结构化卡片（JSON/服务/按钮消息） | 消息元素 | ✅ | 标题/摘要/来源卡片，带链接可点开系统浏览器 |
| 协议 Markdown 消息 | `Markdown` 元素 | ✅ | Neony Markdown 组件渲染 |
| 群打卡 | 事件驱动 | 🔔 | 灰条 |
| 阅读回执 | `SsoReadedReport` | ⏸ | hiro-qq 无公开 API，库内部按需上报 |

### 好友

| 能力 | hiro-qq API | 现状 | UI 落点 |
| --- | --- | --- | --- |
| 好友列表 | `get_friend_list` | ✅ | 会话列表、发起会话 |
| 好友资料 | `get_user_info` | ✅ | 消息菜单「资料卡」 |
| 好友申请处理 | `set_friend_request` | ✅ | 通知中心 |
| 名片点赞 | `friend_like` | ✅ | 资料卡动作 |
| 好友历史消息 | `get_friend_msg` / `get_friend_latest_seq` | ✅ | 历史分页、离线补拉 |

### 群

| 能力 | hiro-qq API | 现状 | UI 落点 |
| --- | --- | --- | --- |
| 群列表/群资料 | `get_grp_list` | ✅ | 会话列表 |
| 群成员列表 | `get_grp_members` | ✅ | @ 提及、成员面板 |
| 群成员资料 | `get_grp_member_info` | ✅ | 成员资料卡 |
| 群申请列表 | `fetch_grp_request` | ✅ | 通知中心 |
| 处理入群申请 | `set_grp_request` | ✅ | 通知中心 |
| 邀请入群 | `invite_grp_member` | ✅ | 群管理 · 邀请好友（勾选后邀请） |
| 移出成员 | `kick_grp_member` | ✅ | 群管理 · 成员面板 |
| 退群 | `leave_grp` | ✅ | 群管理 · 退出群聊 |
| 修改群名 | `rename_grp_name` | ✅ | 群管理 · 群资料 |
| 修改群名片 | `rename_grp_member` | ✅ | 群管理 · 成员面板 |
| 设置管理员 | `set_grp_admin` | ✅ | 群管理 · 成员面板（群主） |
| 设置专属头衔 | `set_grp_special_title` | ✅ | 群管理 · 成员面板（群主） |
| 全员禁言 | `set_mute_grp` | ✅ | 群管理 · 群资料（管理员） |
| 单人禁言 | `set_mute_member` | ✅ | 群管理 · 成员面板（管理员） |
| 群文件上传/下载 | `upload_grp_file` / `fetch_grp_file_url` | ✅ | 输入区、文件卡片 |
| 群相册更新 | 事件驱动 | 🔔 | 灰条 |

### 资料与账号

| 能力 | hiro-qq API | 现状 | UI 落点 |
| --- | --- | --- | --- |
| 二维码登录 | `fetch_qrcode` / `qrcode_login` | ✅ | 登录页 |
| 密码/Token 登录 | `password_login` / `token_login` | ⏸ | 按用户要求不做密码登录与验证码；Token 登录无独立获取入口 |
| IPv6 / Optimum 线路 | `Client(use_ipv6, use_optimum)` | ✅ | 登录配置表单「网络」开关 |
| 修改昵称 | `set_nickname` | ✅ | 设置页「个人资料」 |
| 修改个性签名 | `set_bio` | ✅ | 设置页「个人资料」 |
| 修改头像 | `set_avatar` | ✅ | 设置页「个人资料 · 更换头像」 |
| 其它在线端 | `OtherClientInfo` | ✅ | 设置页「其它在线端」 |

### 表情与媒体

| 能力 | hiro-qq API | 现状 | UI 落点 |
| --- | --- | --- | --- |
| 接收图片/视频/语音/文件 | 消息元素 | ✅ | 消息渲染 + 本地缓存 |
| 接收商城表情 | `MarketFace` 元素 | ✅ | 消息渲染 |
| 获取商城表情 key | `get_marketface_key` | ⏸ | 表情商城浏览所需；最近表情面板不依赖该 key |
| 复读 QQ 表情 / 商城表情 | `Emoji` / `MarketFace` 元素 | ✅ | 消息菜单「发送表情」+ 输入区最近商城表情面板 |
| HEVC 视频转码 | Neony 托管播放器 | ✅ | 消息渲染 |

## UI 设计原则

- 信息型事件统一进入聊天流灰条，不弹模态框，不打断当前操作。
- 需要用户决策的事件（好友申请、入群申请、群邀请）进入通知中心，未读数
  体现在入口角标上；处理动作复用 Neony 原生 `Button` / `List` / `Badge`。
- 协议动作尽量复用消息气泡右键菜单（撤回、回应、戳一戳、精华、转发），
  避免新增悬浮工具条带来的视觉噪音。
- 群管理动作放在成员面板与群设置中，按当前账号身份动态显示/禁用。
- 所有新增能力只使用已有协议连接，禁止启动本地 HTTP/WebSocket 服务或
  额外端口。

## 实施批次

1. **第一批（已完成）**：戳一戳收发、提示类群事件灰条、离线消息与群成员
   同步并发化、custom sign provider、本地登录信息迁移。
2. **第二批（已完成）**：通知中心（好友申请、入群申请、群邀请、申请结果、
   同意/拒绝、刷新）与好友资料卡、名片点赞。
3. **第三批（已完成）**：群管理面板（改群名、踢人、全员/单人禁言、管理员、
   专属头衔、群名片、退群，按自身与目标身份动态启用/禁用）。
4. **第四批（已完成）**：精华消息、合并转发展开、单条/多选转发、视频与语音
   发送。
5. **第五批（进行中）**：个人资料（昵称/签名/头像）、其它在线端、邀请入群已
   完成；密码/Token 登录待做。

# Flaza

基于 [lagrange-python](https://github.com/LagrangeDev/lagrange-python) 和 [Neony](https://github.com/HarcicYang/Neony) 的 QQ 桌面客户端。

## 功能覆盖

<details>
<summary>消息类型</summary>

| 类型                 | 接收 | 发送 | 说明                     |
| -------------------- | ---- | ---- | ------------------------ |
| 文本                 | ✅   | ✅   | 支持多行文本             |
| 图片                 | ✅   | ❌   | 本地缓存，data URL 展示  |
| 商城表情             | ✅   | ❌   | 图片展示                 |
| 语音                 | ✅   | ❌   | 原生播放器或占位卡       |
| 视频                 | ✅   | ❌   | 原生播放器或占位卡       |
| 文件                 | ✅   | ❌   | 下载链接卡片             |
| @ / @全体成员        | ✅   | ❌   | 高亮文本                 |
| 回复引用             | ✅   | ❌   | 背景深度区分             |
| QQ 内置表情          | 🚧   | ❌   | 当前为占位标签           |
| 戳一戳               | ✅   | ❌   | 卡片展示                 |
| 合并转发             | 🚧   | ❌   | 仅卡片，暂不展开         |
| 卡片 / JSON / 按钮等 | 🚧   | ❌   | 统一占位卡，保留原始类型 |

</details>

<details>
<summary>事件类型</summary>

| 事件                | 状态 | 说明                |
| ------------------- | ---- | ------------------- |
| 好友消息            | ✅   | 进入会话并持久化    |
| 群消息              | ✅   | 进入会话并持久化    |
| 好友 / 群撤回       | ✅   | 标记消息并显示灰条  |
| 群名变更            | ✅   | 灰条 + 会话标题更新 |
| 群成员加入          | ✅   | 灰条                |
| 群成员退出 / 被移出 | ✅   | 灰条                |
| 管理员变更          | ✅   | 灰条 + 身份更新     |
| 禁言                | ✅   | 单人 / 全员禁言灰条 |
| 登录阶段变化        | ✅   | 驱动页面切换        |
| 连接状态变化        | ✅   | 标题栏展示          |
| 联系人 / 群成员同步 | ✅   | 登录后后台同步      |
| 离线消息同步完成    | ✅   | 刷新会话与消息      |
| 好友申请            | ❌   | 未接入              |
| 群申请 / 群邀请     | ❌   | 未接入              |

</details>

<details>
<summary>操作类型</summary>

| 操作             | 状态 | 说明                         |
| ---------------- | ---- | ---------------------------- |
| 静默登录         | ✅   | 已有会话时自动登录           |
| 扫码登录         | ✅   | 二维码内嵌展示               |
| 密码登录         | ❌   | 未规划                       |
| 打开 / 新建会话  | ✅   | 好友与群                     |
| 发送文本消息     | ✅   | 回车发送                     |
| 图片全屏预览     | ✅   | Ctrl+滚轮缩放、滚轮平移、鼠标拖拽、1:1、双击、Esc 关闭 |
| 发送图片等富媒体 | ❌   | 规划中                       |
| 撤回自己的消息   | ❌   | 未接入                       |
| 复制 / 删除消息  | ❌   | 右键菜单未接入               |
| 向上加载历史消息 | 🚧   | 存储层已支持 `list_before()` |
| 修改登录配置     | ✅   | 保存后重启                   |
| 切换主题         | ✅   | 即时生效，持久化             |
| 管理媒体缓存     | ❌   | 自动下载 + LRU，无手动入口   |
| 处理好友申请     | ❌   | 未接入                       |

</details>

## TODO

- [ ] 插件系统

## 技术栈

- Python 3.12
- [uv](https://github.com/astral-sh/uv) 管理依赖
- [lagrange-python](https://github.com/LagrangeDev/lagrange-python) QQ 协议
- [Neony](https://github.com/HarcicYang/Neony) UI
- aiosqlite 本地存储
- msgpack 消息载荷编码
- ruff + pyrefly 静态检查

## 项目结构

```text
src/flaza/
├── core/                 # 领域模型、事件、端口、服务、存储；不依赖 UI/协议
│   ├── models/           # 消息元素、会话、联系人等领域模型
│   ├── services/         # 消息、联系人、媒体缓存等用例服务
│   └── storage/          # SQLite、repository、msgpack codec
├── qq/                   # lagrange-python 适配；唯一允许 import lagrange 的模块
├── ui/                   # Neony UI；页面、组件、状态
│   ├── components/       # 消息流、会话列表、设置、消息内容渲染器等
│   └── pages/            # setup / login / home
├── app.py                # Neony 应用组装
├── runtime.py            # 对象组装与生命周期
└── config.py             # appconfig.json 配置模型
```

## 快速开始

要求：

- Python 3.12
- [uv](https://github.com/astral-sh/uv)
- Linux 桌面环境（GTK / WebKitGTK）

```bash
uv sync --group dev
uv run flaza
```

首次启动时会在界面内引导填写登录配置，保存后应用自动重启。

## 运行时数据

| 路径                      | 用途                               | 是否入库 |
| ------------------------- | ---------------------------------- | -------- |
| `appconfig.json`          | 登录、协议、窗口与媒体缓存路径配置 | 否       |
| `flaza.db`                | 联系人、会话、消息与已读游标       | 否       |
| `media_cache/`            | 下载到本地的消息媒体文件           | 否       |
| `device.json` / `sig.bin` | QQ 设备信息与会话签名              | 否       |

媒体缓存默认目录为 `./media_cache`，总量上限 2 GiB（LRU 淘汰），单文件上限 512 MiB，下载并发 2，超时 60 秒。

## 常用开发命令

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyrefly check
uv run pytest -q
uv build
uv run flaza
```

提交信息遵循 Conventional Commits。架构与协作约定见 [docs/design-decisions.md](docs/design-decisions.md)。

# Flaza

非官方 QQ 桌面客户端，使用 Python编写，由
[lagrange-python](https://github.com/LagrangeDev/lagrange-python) [^1] 和
[Neony](https://github.com/HarcicYang/Neony) 驱动。

目前项目仍处于早期开发阶段，功能与数据格式可能会继续调整。

## 项目亮点

- **Tauri 同源的系统 Webview 与 Rust 内核的 GUI** : 更小的储存空间占用和潜力丰富的性能
- **丰富的主题系统** : 四类八种丰富主题
- **强力拓展** : 高度自由的插件系统，翻修覆写不在话下

## 项目进度与规划

核心功能已经可用：登录与消息收发、本地持久化、媒体缓存、群事件、表情回应、
历史消息分页、会话草稿与未读计数、会话切换缓存与后台预取、多主题和插件管理 。

- **待完善**：语音、视频、商城表情与 QQ 内置表情发送；合并转发内容展开； 
更多结构化卡片渲染；媒体缓存的可视化手动管理...
- **规划中**：本地删除消息；更方便的分发与更新...

## 快速开始

运行要求：

- Python 3.12
- uv ( 可选 )
- [Lagrange V2 签名服务](https://github.com/LagrangeDev/SignApiGuide) [^2]

```bash
uv sync
uv sync --group dev  # 开发环境
uv run flaza
```

首次启动时会进入登录配置页，填写 `uin`、协议、签名服务地址与 token；
保存后应用会自动重启并尝试登录， 已有设备数据时静默登录，否则在页面中展示二维码
扫码确认后进入主界面。

## 插件系统

Flaza 的插件是加载进应用进程的 Python 模块。插件可以注册新的消息段、事件和
[气泡动作](https://harcic.me/neony/zh/api/components.html#messagebubble)，
也可以改写出站消息、拦截主动撤回、向会话写入灰条，或直接通过
`ctx.runtime` 触碰应用内部对象。

一个插件就是一个目录：

```text
plugins/
  my-plugin/
    manifest.json
    main.py
```

```json
{
  "id": "my-plugin",
  "name": "示例插件",
  "version": "0.1.0",
  "entry": "main.py",
  "author": "Sakuraba Ema",
  "description": "Hiro-chan, Hiro-chan!",
  "dependencies": []
}
```

入口文件应当导出模块级 `plugin` 实例：

```python
from flaza.plugins import FlazaPlugin, PluginContext


class MyPlugin(FlazaPlugin):
    async def on_load(self, context: PluginContext) -> None:
        await context.notify("user:114514", "插件已加载")


plugin = MyPlugin()
```

`dependencies` 声明依赖后，宿主只在启动时检查并警告，不会自动安装也不会阻止
加载。插件可以随时从设置页启用、禁用、重新加载或切换目录，编辑代码后无需重启
应用。仓库里提供了可直接复制的示例：

- `recall-keep`：收到撤回事件时保留消息内容并标记为已撤回
- `group-notices`：把群事件播报成更详细的灰条
- `plus-one`：在消息气泡上增加 `+1` 按钮，原样复读消息
- `custom-theme`：加载时覆盖 CSS 变量，卸载时恢复内置主题

完整说明见 [examples/plugins/README.md](examples/plugins/README.md)

## 架构

Flaza 把协议、领域与界面分成四个主要区域：

```text
src/flaza/app.py      应用组装与桌面入口
src/flaza/core/       领域模型、事件、服务与存储
src/flaza/qq/         唯一允许导入 lagrange 的协议适配层
src/flaza/ui/         Neony 界面、状态投影与用户动作
src/flaza/plugins/    插件宿主、扩展注册表与插件 API
```

所有模块共享同一个 asyncio 事件循环：协议适配层发布领域事件，服务层处理业务，
UI 状态层把事件投影到 Neony 的可绑定信号，插件则通过事件总线与扩展注册表接入
任意环节。

运行时数据全部在本地：

- `appconfig.json`：登录、协议、路径、窗口与主题配置
- `flaza.db`：联系人、会话、消息、群成员与已读游标
- `chat_cache.json`：最近消息快照，用于跨启动复用的快速会话切换
- `plugin_state.json`：插件启停状态、设置与 KV
- `media_cache/`：下载到本地的消息媒体文件

## 开发

```bash
uv run ruff format --check .
uv run ruff check .
uv run pyrefly check
uv run pytest -q
uv run flaza
```

落地细节、取舍和后续计划记录在 [docs/design-decisions.md](docs/design-decisions.md)。

## License

GPL-3.0，见 [LICENSE](LICENSE)。

## 免责声明

- Flaza 是非官方 QQ 客户端，与腾讯公司无任何关联。
- 项目仅供学习、研究和技术交流，请勿用于违反法律法规或 QQ 服务条款的用途。
- 使用者应自行确认使用方式符合所在地法律，并自行承担账号安全、数据丢失、功能
  受限等风险。
- 插件默认拥有当前用户完整权限，安装第三方插件前请确认来源与代码内容。

[^1]: 本仓库依赖中的 lagrange-python 包指向
[作者自己的 fork](https://github.com/HarcicYang/lagrange-python)，其中包含本项目
所需而上游尚未提供的实现；直接替换为 LagrangeDev 原版包可能无法正常运行。

[^2]: 部分环境下，安装相关依赖库可能需要额外配置 openssl 与 rust 开发环境。

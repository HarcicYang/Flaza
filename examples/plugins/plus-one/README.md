# 复读 +1 示例

这个示例插件演示消息气泡快捷动作扩展点：插件在原有回复、表情按钮旁边
增加一个 `+1` 按钮，点击后把原消息的完整 `elements` 原样发送到同一会话，
因此文字、图片、@、引用等元素都会保持一致。

## 原理

- `ctx.register_message_action("send", handler, label="+1")` 注册快捷动作。
- 核心 `MessageList` 会把插件动作作为气泡 actions 按钮渲染。
- `handler` 收到对应的 `StoredMessage`，用 `ctx.send_message` 发送
  `message.elements` 的逐项副本。
- 若原消息包含插件自定义消息段，则该插件必须仍处于加载状态并提供
  `sender`，发送器由核心注册表统一转发。

## 配置

本示例不需要额外配置。卸载插件后，气泡上的 `+1` 按钮会随注册清理消失。

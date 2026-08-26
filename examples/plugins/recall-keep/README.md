# 撤回内容保留示例

这个示例插件演示 M2 插件扩展能力：当收到 `MessageRecalled` 事件时，在
内置服务处理之前改写本地消息，把原消息标记为已撤回并保留内容，使气泡
继续显示原文而不是变成“撤回了一条消息”灰条。

## 原理

- `ctx.before_event(MessageRecalled, ...)` 在普通事件处理器之前执行。
- 插件用 `storage.messages.get_by_seq()` 找到原消息。
- `replace_message()` 写入 `recalled=True`、`retain_content_on_recall=True`，
  并追加可配置的标记文本。
- 返回 `None` 吞掉事件，避免核心撤回灰条与 UI 处理器覆盖保留内容。
- 插件直接刷新当前会话消息与会话列表，让界面立即反映存储中的结果。

## 配置

在 `plugin_state.json` 的 `settings.recall-keep` 中可覆盖追加标记：

```json
{
  "settings": {
    "recall-keep": {
      "marker": "（内容已被插件保留）"
    }
  }
}
```

把 `marker` 设为空字符串则只保留内容，不追加标记文本。

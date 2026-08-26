# Flaza 示例插件

这里提供可直接复制到 `plugins/<plugin_id>/` 运行的示例插件。插件元数据、
设置与状态全部使用 JSON，不使用 YAML。

| 目录 | 说明 |
| --- | --- |
| `recall-keep/` | 收到撤回事件时保留本地消息内容，并标记为已撤回。 |

## 使用

```bash
mkdir -p plugins
cp -r examples/plugins/recall-keep plugins/
```

插件默认启用；程序运行后会自动生成 `plugin_state.json`，可通过其中的
`settings` 调整示例插件行为。

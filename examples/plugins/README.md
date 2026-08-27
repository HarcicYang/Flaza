# Flaza 插件

这里提供可直接复制到 `plugins/<plugin_id>/` 运行的示例插件。插件元数据、 设置与状态全部使用 JSON，不使用 YAML。

| 目录             | 说明                                             |
|------------------|--------------------------------------------------|
| `recall-keep/`   | 收到撤回事件时保留本地消息内容，并标记为已撤回。 |
| `group-notices/` | 群成员进出、管理员、禁言与群名变更的详细播报。   |
| `plus-one/`      | 在消息气泡快捷动作中增加 +1 按钮，原样复读消息。 |
| `custom-theme/`  | 通过公开 API 切换到 Flaza 内置主题。             |

## 使用

```bash
mkdir -p plugins
cp -r examples/plugins/recall-keep examples/plugins/group-notices plugins/
cp -r examples/plugins/plus-one examples/plugins/custom-theme plugins/
```

插件默认启用；程序运行后会自动生成 `plugin_state.json`，可通过其中的
`settings` 调整示例插件行为。

`plus-one` 依赖消息气泡快捷动作扩展点，`custom-theme` 依赖
`ctx.apply_theme`，其余示例仅使用插件公开 API。

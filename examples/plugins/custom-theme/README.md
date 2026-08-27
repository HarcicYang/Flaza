# 自定义主题示例

这个示例演示插件通过公开上下文切换 Flaza 内置主题：加载时切换到
`planet-plaza-dark`。主题选择不会写入配置，卸载、禁用或重启后回到当前
配置声明的主题。

## 用法

```python
await context.apply_theme("planet-plaza-dark")
```

如需自定义配色，请扩展 Neony 主题对象并通过宿主的公开主题 API 注册，
不要直接写入 CSS 变量或操作 DOM。

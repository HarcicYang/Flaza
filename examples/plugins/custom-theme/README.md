# 自定义主题示例

这个示例插件演示插件直接操作运行时给出的“纸页浅色”主题：加载时向
`:root` 写入一组 CSS 颜色变量，界面无需重启即可换色；卸载或禁用插件时
移除行内变量，回到内置主题。

## 原理

- 插件设置 `variables` 是 `--color-*` 到 CSS 值的 JSON 映射。
- `on_load` 用 `ctx.runtime.eval_js` 逐项写入 `documentElement.style`，
  行内样式优先级高于主题样式表，因此会覆盖当前内置主题。
- 插件记住写入过的 key，`on_unload` 时逐项 `removeProperty` 恢复原状。

## 配置

默认提供一套纸页浅色调。在 `plugin_state.json` 中覆盖任意变量即可：

```json
{
  "settings": {
    "custom-theme": {
      "variables": {
        "--color-bg": "#f2f6f3",
        "--color-accent": "#3f7d6a"
      }
    }
  }
}
```

也可以把不需要覆盖的变量移出映射；插件只会移除本次写入过的 key。

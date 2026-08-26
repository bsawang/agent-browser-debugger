# AGENT-LOGGER — agent-browser-debugger

## 2026-08-26 建立项目：CDP 浏览器接管调试方案

**背景**：ComfyUI「视频对比预览」节点信息栏定位问题排查时，先走 headless 黑盒测试（自启 chromium + CDP 探测），发现不可靠（canvas 不渲染、状态不同步、反复重启耗时）。用户要求改为**观察型调试**——接管用户已运行的 Chrome 直接看真实前端。

**改动**：建立 agent-browser-debugger 项目，沉淀 CDP 接管调试 skill 与常用命令；配套改造了全局 `~/.claude/skills/cdp-observe/`。

**关键实现点**：
- **Chrome 136+ 安全变更**：`--remote-debugging-port` 在默认数据目录被静默忽略，必须配 `--user-data-dir`（非默认）或 `chrome://inspect` 手动开启
- **chrome://inspect 模式**（Chrome 144+）：默认 profile 保留登录，但每次新 CDP 连接弹授权（无永久信任，Chrome 官方确认）——引出常驻代理方案
- **常驻代理 cdp_proxy.py**：后台保持单个 CDP 连接，本地 HTTP 端口收发命令（eval/shot/pages），避免重复授权弹窗
- **cdp.py** 单次命令也改为单连接（list/eval/multi/shot 都在一个 ws 连接内），`multi` 一次连接执行多条
- **观察式调试原则**：只读观察 + 临时 JS，不自行启动/重启浏览器，结束不留痕

**附带解决**（aigc-study 的 VCP 节点）：信息栏位置问题根因 = 视频预览是 Vue `video-preview` 组件（lg-node-content 内），信息栏 widget 在 widgets 区（天然在预览上方）；改为纯 DOM div 插到 video-preview 之后（MutationObserver 防 Vue 重渲染清掉）。

**关键命令**：见 `docs/commands.md`（cdp.py / cdp_proxy.py / 常用观察 JS / ComfyUI 重启）。
**相关**：aigc-study 项目 `assets/nodes/bsawang-nodes/web/video_compare_ui.js`；全局 `~/.claude/skills/cdp-observe/`。

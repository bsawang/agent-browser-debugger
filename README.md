# agent-browser-debugger

Chrome 前端接管调试工具包——通过 DevTools 协议（CDP）实时查看/调试浏览器前端状态。

## 解决的问题

ComfyUI 前端布局/DOM/widget/渲染问题排查时，黑盒 headless 测试不可靠（渲染限制、状态不同步），需要**接管用户真实浏览器**观察。本包沉淀这一调试模式为可复用 skill + 常用命令。

## 包含

- `skills/cdp-observe/` — skill：CDP 接管观察（SKILL.md + cdp.py 单次命令 + cdp_proxy.py 常驻代理）
- `docs/setup.md` — Chrome 远程调试配置（Chrome 136+ 安全变更、两种开启方式）
- `docs/commands.md` — 调试命令（CDP 工具、Chrome 配置，按软件区分）
- `docs/comfy/commands.md` — ComfyUI 专题命令（观察节点/触发执行/重启/踩坑）

## 快速开始

```bash
# 1. 用户 Chrome 开启调试（chrome://inspect 勾选 Allow remote debugging）
# 2. 常驻代理（弹一次授权后不弹）
python skills/cdp-observe/scripts/cdp_proxy.py 9333 &
# 3. 发命令
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
```

详见 `.claude.md` 与 `docs/`。

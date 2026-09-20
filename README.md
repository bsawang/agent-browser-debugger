# agent-browser-debugger

浏览器调试 CDP 接口层 — 通过 Chrome DevTools 协议（CDP）实时观察/调试浏览器前端状态。

## 定位

**通用 CDP 调试基础设施**，面向两类消费方：

1. **AI agent 的浏览器调试 skill** — agent 发命令（eval/shot/navigate/事件监听）观察真实浏览器的 DOM/布局/渲染/交互状态
2. **其他项目的可嵌入插件** — 如 `browser-action` 这类需要 CDP 能力的项目，可直接 `from cdp_core import CDP, detect_ws_url` 复用底层

### 与 browser-action 的边界

| 维度 | 本项目 | browser-action |
|---|---|---|
| 定位 | 调试观察接口层（被动查询 + 按需操作） | 任务执行引擎（主动驱动循环） |
| 谁主动 | agent 发命令查状态 | 框架按 step 自动循环执行 |
| 核心能力 | eval/shot/navigate/事件监听/ensure_tab | TaskTemplate + InjectorRegistry + Loop |
| 不做的事 | 不启动浏览器、不自动跑循环、不存应用状态 | 不做前端观察/诊断 |
| 底层共享 | CDP 连接探测 + attach 模式 | 完全共享（同一套 cdp_core 设计） |

### 包含 / 不包含

**包含（通用 CDP 能力）**：
- Chrome 远程调试探测（chrome://inspect + 传统 --remote-debugging-port 自动回退）
- `ensure_tab`：目标 tab 不存在时自动创建（解决「没 tab 就退出」问题）
- eval / shot / navigate / pages / target 切换
- Network/DOM/Page 等事件监听 + 环形缓冲
- 常驻代理（避免 inspect 模式重复授权弹窗）
- attach/enable 去重（同一 targetId 不重复 attach，同一 CDP 域不重复 enable）

**不包含（由消费方自己提供）**：
- 特定站点/应用的观察 JS 命令和踩坑备忘（如 ComfyUI、Vue、React 专题）
- 特定框架的 CDP 封装（如 Playwright/Puppeteer 兼容层）
- 任务自动化/循环执行/凭证管理

## 架构

```
Agent ──HTTP──▶ cdp_proxy.py ──WebSocket──▶ Chrome CDP
                  │
                  ├── HTTP JSON API（统一命令格式）
                  ├── CDP 封装层（pending Map、attach 去重、事件缓冲）
                  └── 连接层（直连 Chrome CDP WebSocket）
```

所有调试命令通过一个常驻代理（`cdp_proxy.py`）暴露。Chrome 侧只需开启远程调试（`chrome://inspect` 勾选或 `--remote-debugging-port`）。

## 快速开始

```bash
# 1. 确认 Chrome 已开调试（不弹授权的只读探测）
python skills/cdp-observe/scripts/cdp.py detect
#   mode: inspect   → chrome://inspect 已开
#   mode: traditional → --remote-debugging-port 已开
#   未检测到        → 提示用户开启

# 2. 起常驻代理（弹一次授权后不弹）
python skills/cdp-observe/scripts/cdp_proxy.py 9333 &

# 3. 发命令（curl 或任何 HTTP 客户端）
curl -s http://127.0.0.1:9333/ -d '{"eval":"JSON.stringify({url:location.href})"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"page.png"}'
curl -s http://127.0.0.1:9333/ -d '{"ensure":"example.com"}'   # 有则复用 tab，无则创建
curl -s http://127.0.0.1:9333/ -d '{"enable":"Network"}'        # 监听网络事件
curl -s http://127.0.0.1:9333/ -d '{"events":"Network"}'        # 拉取事件缓冲
```

**依赖**：Python 需 aiohttp（`pip install aiohttp`）

## HTTP API

所有命令 POST JSON 到 `http://127.0.0.1:<port>/`：

| 命令 | 请求 | 响应 | 说明 |
|---|---|---|---|
| detect | `{"detect":1}` | `{"found":true, "mode":"inspect"}` | 只读探测 Chrome 调试状态 |
| open | `{"open":"https://..."}` | `{"opened":"...", "targetId":"..."}` | 新建 tab 打开 URL 并 attach |
| pages | `{"pages":1}` | `{"pages":[...]}` | 列所有 page tab |
| target | `{"target":"<URL子串>"}` | `{"target":{...}}` | 热切换目标 tab |
| ensure | `{"ensure":"<URL子串>"}` | `{"target":{...}}` | 有则复用 tab，无则创建 |
| eval | `{"eval":"<js表达式>"}` | `{"result":<值>}` | 执行 JS |
| shot | `{"shot":"<文件路径>"}` | `{"saved":"...", "size":N}` | 截图保存为 PNG |
| navigate | `{"navigate":"<url>"}` | `{"navigated":"..."}` | 导航 |
| enable | `{"enable":"<Domain>"}` | `{"enabled":"...", "wasNew":true/false}` | 启用 CDP 事件域（幂等去重） |
| events | `{"events":"<Domain>"}` | `{"events":[...]}` | 拉取事件缓冲（可选 domain 过滤） |
| clear_events | `{"clear_events":1}` | `{"cleared":true}` | 清空事件缓冲 |

## 可嵌入 API（browser-action 等项目用）

```python
from cdp_core import CDP, detect_ws_url, select_target

# 只读探测（不连 ws，不弹授权）
ws_url, mode, tabs = await detect_ws_url()

# 完整启动 + ensure tab
c = CDP()
target = await c.connect_and_ensure("example.com", "about:blank")

# 或分步
c = CDP()
await c.connect(ws_url)
await c.start()
target = await c.ensure_tab("example.com", "about:blank")   # 有则复用，无则创建
await c.attach_page(target["targetId"])

# 核心方法
await c.send("Runtime.evaluate", {"expression": "...", "returnByValue": True})
await c.on_event(lambda method, params: print(method))   # Chrome 事件 → Python 回调
await c.create_target("https://...")
await c.close()
```

## 项目结构

```
skills/cdp-observe/
├── SKILL.md              # Agent 工作流约定
└── scripts/
    ├── cdp_core.py       # 共享核心（CDP 类 + detect + select + ensure）  ← 可嵌入
    ├── cdp.py            # CLI：detect / open / list / eval / multi / shot / navigate
    └── cdp_proxy.py      # 常驻代理：HTTP 接口 + 长连接（避免重复授权）

docs/
├── setup.md              # Chrome 远程调试配置
└── commands.md           # 代理命令速查
```

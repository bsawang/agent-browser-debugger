# cdp-debug

CDP 调试工具集 — 通过 Chrome DevTools Protocol 连接用户**已运行的 Chrome**，做运行态调试、自发操作、事件监听。

一个 Python 包 + MCP server + HTTP proxy。安装后 agent / IDE 直接调 MCP tools 或走 HTTP fallback。

## 核心特性

| 能力 | 实现 | 说明 |
|---|---|---|
| MCP server | `cdp_mcp.py` | **推荐入口**，16 tools，stdio 协议，零 Shell 开销 |
| HTTP proxy | `cdp_proxy.py` | fallback，9333 端口，常驻长连接避免重复授权 |
| CLI | `cdp.py` | detect / eval / shot / navigate / ensure 等单次命令 |
| 可嵌入模块 | `cdp_core.py` | 其他 Python 项目直接 `from cdp_core import CDP, detect_ws_url` |
| 事件系统 | enable_domain + 200 条环形缓冲 | Network/DOM/Page/Runtime 等 CDP 域事件自动缓存 |
| 运行态插入 | 直连用户 Chrome | 保留登录态/tab/状态，不启新浏览器 |
| 自动探测 | detect_ws_url() | chrome://inspect + --remote-debugging-port 两种模式自动识别 |

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│ 消费方                                                         │
│ TRAE / Claude Code Cursor / Copilot (MCP)                     │
│ 或任何 HTTP 客户端 (curl / Python requests)                    │
└──────┬──────────────────────────────┬─────────────────────────┘
       │ MCP stdio                    │ HTTP :9333
       ▼                              ▼
┌──────────────────┐      ┌──────────────────┐
│  cdp_mcp.py      │      │  cdp_proxy.py    │
│  (推荐入口)      │      │  (fallback)      │
└────────┬─────────┘      └────────┬─────────┘
         │                         │
         └────────────┬────────────┘
                      ▼
              ┌─────────────┐
              │  cdp_core.py│  ← 共享核心
              │  CDP 类     │
              └──────┬──────┘
                     │ WebSocket
                     ▼
              ┌─────────────┐
              │ Chrome CDP  │
              └─────────────┘
```

## 安装

### 一键（Windows）

```
git clone https://github.com/bsawang/agent-browser-debugger.git
cd agent-browser-debugger
install.bat
```

install.bat 干三件事：
1. `pip install -e .` → `cdp-mcp` / `cdp-proxy` / `cdp` 进 PATH
2. 复制 SKILL.md + .py 脚本到 `~/.trae-cn/skills/cdp-debug/` 和 `~/.claude/skills/cdp-debug/`
3. 向 `mcp.json` / `.claude.json` 合并 MCP server 条目

### 手动

```bash
pip install -e .

# MCP 配置（TRAE: Settings → MCP; Claude Code: ~/.claude.json）
# { "mcpServers": { "cdp-debug": { "command": "cdp-mcp", "args": [] } } }
```

## Chrome 前置

用户 Chrome 需开启远程调试，二选一：

1. **chrome://inspect/#remote-debugging** → 勾选 "Allow remote debugging"（保留默认 profile + 登录态）
2. 桌面快捷方式加参数 `--remote-debugging-port=9222`（独立 profile，无授权弹窗）

验证（不弹授权）：

```bash
cdp detect
# mode: inspect   → chrome://inspect 已开
# mode: traditional → --remote-debugging-port 已开
# 未检测到        → 提示开启
```

## MCP Tools（16 个）

重启 IDE 后 agent 自动看到。参数结构化，直接调用：

| Tool | 说明 |
|---|---|
| `detect_chrome` | 只读探测 Chrome 调试状态 |
| `list_pages` | 列所有 page tab |
| `ensure_tab` | 目标 tab 有则复用，无则创建 |
| `open_tab` | 新建 tab |
| `close_tab` | 关 tab |
| `navigate` | 导航 |
| `eval` | 执行 JS |
| `take_screenshot` | 截图 |
| `click` | 点击（CSS selector 或坐标） |
| `hover` | 悬停 |
| `type_text` | 输入（可选先聚焦 selector） |
| `press_key` | 按键 |
| `handle_dialog` | 处理 JS 对话框 |
| `enable_domain` | 启用 CDP 事件域（Network/DOM/Page/Runtime/Log） |
| `get_events` | 读事件缓冲 |
| `clear_events` | 清空缓冲 |

### 典型工作流

```
detect_chrome → found=true → 继续
ensure_tab(url_substr="baidu") → 目标 tab
navigate(url="https://www.baidu.com")
type_text(text="hello", selector="#kw")
press_key(key="Enter")
take_screenshot(path="result.png")
enable_domain(domain="Network") → 事件自动缓冲
get_events(domain="Network") → 读缓冲
```

## HTTP Fallback

无 MCP 支持的环境用。启动 proxy：

```bash
cdp-proxy 9333
```

发命令（POST JSON 到 http://127.0.0.1:9333/）：

```json
{"eval":"document.title"}
{"shot":"page.png"}
{"navigate":"https://www.baidu.com"}
{"click":"button.submit"}
{"type":{"selector":"#kw","text":"hello"}}
{"press_key":"Enter"}
{"enable":"Network"}
{"events":"Network"}
```

## 可嵌入 Python API

```python
from cdp_core import CDP, detect_ws_url, chrome_running
import asyncio

async def demo():
    # 只读探测（不连 ws，不弹授权）
    ws_url, mode, tabs = await detect_ws_url()
    if not ws_url:
        print("Chrome 未开远程调试")
        return

    # 连接 + ensure tab
    c = CDP()
    await c.connect(ws_url)
    await c.start()
    await c.enable_domain("Runtime")
    target = await c.ensure_tab("example.com", "about:blank")
    await c.attach_page(target["targetId"])

    # 调试操作
    result = await c.eval("document.title")
    await c.click("button.submit")
    await c.type_text("hello", selector="#kw")
    await c.shot("screenshot.png")

    # 事件
    def on_event(method, params):
        print(f"{method}: {params}")
    c.on_event(on_event)
    await c.enable_domain("Network")
    # ... 事件自动触发回调

    await c.close()

asyncio.run(demo())
```

## 与 browser_use / Chrome DevTools MCP 的区别

| | cdp-debug | browser_use | Chrome DevTools MCP |
|---|---|---|---|
| 连接 | 用户已运行的 Chrome | Playwright 自动启 Chromium | autoConnect 或自动启 |
| 运行态插入 | ✅ 就是为这个设计的 | ❌ | ❌ |
| 事件缓冲 | ✅ 200 条环形缓冲 | ❌ | 被动列表 |
| 性能/内存分析 | ❌ | ❌ | ✅ |
| 依赖 | aiohttp + mcp | Playwright | puppeteer + Chrome DevTools 前端 |
| 数据收集 | 零 | 零 | Google 默认收集 |
| pip install | `pip install -e .` | Playwright install | npx |
| 适用场景 | 调试、运行态观察、自发 UI 操作 | 自动化任务、表单填写 | 完整 DevTools 替代 |

## 项目结构

```
agent-browser-debugger/
├── README.md              # 本文件
├── install.bat            # 一键安装（Windows）
├── pyproject.toml         # pip 包 + console scripts
├── cdp_core.py            # 共享核心 ← 可嵌入
├── cdp_mcp.py             # MCP server（推荐入口）
├── cdp_proxy.py           # HTTP proxy（fallback）
├── cdp.py                 # CLI
├── skill/
│   └── SKILL.md           # IDE skill 安装时复制到 ~/.trae-cn/skills/ / ~/.claude/skills/
└── docs/
```

## 约定

- **MCP 优先**：IDE 支持 MCP 时走 `cdp-mcp`。无 MCP 时走 `cdp-proxy` HTTP。
- **不启动浏览器**：Chrome 需已在运行。自动创建 tab，但不启动 Chrome 进程。
- **操作 = 调试手段**：click/type/press_key 是为了复现 bug、触发调试场景，不是替代用户正常浏览。
- **持久化改动先征得同意**：需要改用户浏览器持久内容（设置、数据、cookie）时先确认。

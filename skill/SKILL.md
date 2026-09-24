---
name: cdp-debug
description: >
  通过 CDP（Chrome DevTools Protocol）**直接控制用户已运行的 Chrome**，
  支持实时调试、元素观察、截图、事件监听、以及点击/输入/键盘等自发操作。
  场景：前端调试、运行态观察、自发 UI 交互、Network/Console/DOM 事件捕获。
  **disambiguation**：本 skill 通过 CDP 协议连接用户 Chrome（非 Playwright 自动化），
  不启动新浏览器、不跑独立 profile；与 browser_use（Playwright 驱动自动化）互斥。
  优先用本 skill 当需要调试**用户正在用的 Chrome**、需要自发操作 + 观察、
  或需要 CDP 事件监听时。
---

# CDP 接管调试（Chrome）

## 什么时候用
- 实时查看/调试前端状态：DOM / 布局 / 渲染 / Network / Console
- 自发操作浏览器：点击按钮、填写表单、输入文本、按键触发交互
- 运行态观察：用户在 Chrome 操作时 agent 捕获事件（Network/DOM/Page 事件缓冲）
- 任务确定的 UI 交互场景：agent 自主完成操作，无需等待用户介入

## 前置（用户环境）
用户 Chrome 需开启远程调试，二选一：
1. **chrome://inspect/#remote-debugging** 勾选「Allow remote debugging for this browser instance」
   （默认 profile 保留登录；每次**新连接**弹授权）
2. 或桌面「Chrome（可接管）」快捷方式（传统 `--remote-debugging-port=9222 --user-data-dir`，无授权但独立 profile）

## 两种连接方式

| | MCP server（推荐） | HTTP proxy（fallback） |
|---|---|---|
| 启动 | MCP 客户端自动拉起 stdio 进程 | 手动 `python cdp_proxy.py` |
| 命令调用 | **MCP tool 直接调**（零 Shell、零临时脚本） | curl -s http://127.0.0.1:9333/ -d '...' |
| 跨平台 | ✅ 纯 Python stdio | ❌ PowerShell curl 是别名，要用 curl.exe 或 Python |
| 依赖 | `pip install mcp aiohttp` | `pip install aiohttp` |
| 适用 | TRAE / Claude Code / Cursor 等支持 MCP 的 IDE | 无 MCP 支持的环境 / CLI 兜底 |

## 连接模型：长连接（默认）

**MCP server 和 HTTP proxy 都是长连接设计**——进程启动时建立 CDP WebSocket，之后所有操作复用同一条连接。这和 CLI `cdp eval`（短连接，每次 detect → connect → 用完丢）完全不同。

长连接的实际好处：
- **chrome://inspect 模式只弹一次授权**：后续所有 tool call 免授权
- **事件持续缓冲**：`enable_domain` 一次启用，之后事件自动进缓冲，随时 `get_events` 读取
- **零重复握手**：省掉每次 `GET /json/version` + WebSocket 握手开销

| 模式 | 连接生命周期 | 授权弹窗 | 事件缓冲 |
|---|---|---|---|
| **MCP server（推荐）** | 进程活多久连多久 | 最多 1 次 | ✅ 持续 |
| HTTP proxy（fallback） | proxy 进程活多久连多久 | 最多 1 次 | ✅ 持续 |
| CLI `cdp`（兜底） | 单次命令，用完断开 | 每次都弹 | ❌ |

## 探测去重：三层防御

Chrome 调试状态探测有**三层递进去重**，避免无意义的重复工作和授权弹窗：

| 层 | 方法 | 开销 | 弹授权？ |
|---|---|---|---|
| 1 | **进程检测**（`tasklist chrome.exe` / `pgrep`） | 零网络，毫秒级 | ❌ |
| 2 | **只读探测**（`DevToolsActivePort` 文件 或 HTTP `/json/version`） | 只读，不连 WebSocket | ❌ |
| 3 | **懒加载 + 双检锁**（MCP 内部 `_ensure_cdp()`） | 内存判断，已连过直接复用 | ❌ |

实际流程：`detect_chrome` 只用层 1+2，**永远不弹授权**；第一次 tool call（如 `eval`）会走层 3 触发真实 WebSocket 连接（这是唯一可能弹授权的时刻）；之后所有 tool call 全走层 3，零开销、零弹窗。

对比：browser_use 每次新建 Playwright 实例 → 新浏览器进程 → 无此问题，但代价是无法连接用户已运行的 Chrome。

---

## MCP server（推荐）

### 配置到 IDE 的 MCP client

```jsonc
// TRAE: Settings → MCP → Edit config (mcp.json)
// Claude Code: ~/.claude.json
// 如果用 install.bat 一键安装过，这步自动完成
{
  "mcpServers": {
    "cdp-debug": {
      "command": "cdp-mcp",
      "args": []
    }
  }
}
```

重启 IDE 后 agent 会在 tool 列表里看到 **16 个 cdp tools**，直接调用即可。

### 16 个 MCP tools

| Tool | 说明 | 参数 |
|---|---|---|
| `detect_chrome` | 只读探测 Chrome 调试状态（不连 CDP、不弹授权） | 无 |
| `list_pages` | 列出 Chrome 所有 page tab | 无 |
| `ensure_tab` | 确保目标 tab 存在 — 有则切换，无则创建 | `url_substr?: str, create_url?: str` |
| `open_tab` | 新建 tab 打开 URL 并 attach | `url: str` |
| `close_tab` | 关闭指定 tab | `target_id: str` |
| `navigate` | 导航 | `url: str` |
| `eval` | 执行 JS | `expr: str` |
| `take_screenshot` | 截图保存 PNG | `path: str` |
| `click` | 点击（CSS selector 或坐标） | `selector?: str, x?: num, y?: num, button?: "left"\|"right"\|"middle"` |
| `hover` | 悬停 | `selector?: str, x?: num, y?: num` |
| `type_text` | 输入文本（可选先聚焦 selector） | `text: str, selector?: str` |
| `press_key` | 按键 | `key: str, modifiers?: int` |
| `handle_dialog` | 处理 JS 对话框 | `accept?: bool, prompt_text?: str` |
| `enable_domain` | 启用 CDP 事件域（幂等） | `domain: str` |
| `get_events` | 读事件缓冲（最近 200 条） | `domain?: str` |
| `clear_events` | 清空事件缓冲 | 无 |

### 典型 MCP 调用示例（agent 直接调 tool，不需要写代码）

```
detect_chrome → found=true → 继续
list_pages → 看看有哪些 tab
ensure_tab(url_substr="baidu", create_url="about:blank") → 目标 tab
navigate(url="https://www.baidu.com") → 导航
type_text(text="hello", selector="#kw") → 聚焦并输入
press_key(key="Enter") → 搜索
take_screenshot(path="H:/temp/result.png") → 截图
enable_domain(domain="Network") → 启用事件
get_events(domain="Network") → 读事件缓冲
```

---

## HTTP proxy（fallback）

### 启动代理

```powershell
# detect（不弹授权）
cdp detect

# 起 proxy（fallback 用）
cdp-proxy 9333
```

### 命令（跨平台兼容：用 Python 调 urllib，避免 PowerShell curl 别名坑）

```bash
# eval
python -c "import urllib.request,json; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9333/', data=json.dumps({'eval':'document.title'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"

# shot
python -c "import urllib.request,json; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9333/', data=json.dumps({'shot':'H:/temp/d.png'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"

# navigate
python -c "import urllib.request,json; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9333/', data=json.dumps({'navigate':'https://www.baidu.com'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"

# click
python -c "import urllib.request,json; print(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:9333/', data=json.dumps({'click':'button.submit'}).encode(), headers={'Content-Type':'application/json'})).read().decode())"

# type + press_key 同理
```

> ⚠️ PowerShell 里别用 `curl`（是 `Invoke-WebRequest` 别名），要么 `curl.exe`，要么上面的 Python 一行命令。

### 单次 CLI 兜底

```bash
cdp detect
cdp eval '<js>'
cdp shot <文件.png>
```

---

## 常用观察 JS（eval 用）

- 页面信息：`JSON.stringify({url: location.href, title: document.title})`
- 读元素文本：`(()=>{const e=document.querySelector('<选择器>'); return e?.innerText?.slice(0,500) ?? null;})()`
- 元素尺寸/位置/样式：`(()=>{const e=document.querySelector('<选择器>'); if(!e) return null; const s=getComputedStyle(e), r=e.getBoundingClientRect(); return JSON.stringify({w:r.width,h:r.height,x:r.x,y:r.y,display:s.display});})()`

## 约定 ⚠️

- **MCP 优先**：IDE 支持 MCP 时，一律走 MCP tool（零 Shell、零临时脚本）。无 MCP 时走 HTTP proxy。
- **不自行启动浏览器**：Chrome 需已在运行。会自动创建 tab，但不会启动浏览器进程。
- **操作 = 调试手段**：click/type/press_key 是为了复现 bug、触发调试场景——不是替代用户正常浏览。
- **持久化改动先征得同意**：需要改动用户浏览器持久内容时先问。

## 与 browser_use 的区别

| | cdp-debug | browser_use |
|---|---|---|
| 连接方式 | CDP WebSocket 直连 | Playwright 驱动 |
| 浏览器实例 | **用户已运行的 Chrome**（保留登录态/tab） | 自动启独立 Chromium（干净 profile） |
| 事件监听 | ✅ enable 域 + 200 条事件缓冲 | ❌ 无 |
| 运行态插入 | ✅ 就是为这个设计的 | ❌ 只能自己启新浏览器 |
| 适用场景 | 调试、观察、运行态复现 | 自动化任务、表单填写、无状态操作 |

需要操作**用户正在用的 Chrome** → cdp-debug。
需要**干净独立可任意控制**的浏览器 → browser_use。

## 脚本

| 文件 | 说明 |
|---|---|
| `cdp_core.py` | 共享核心（CDP 类 + detect + click/type/hover/press_key/handle_dialog）← 可嵌入 |
| `cdp_mcp.py` | **MCP server**（16 tools，stdio 协议，推荐入口） |
| `cdp_proxy.py` | HTTP 9333 代理（fallback，常驻长连接） |
| `cdp.py` | CLI：detect / open / list / eval / shot / navigate |

安装：`pip install -e .`（repo 根）。之后 `cdp-mcp` / `cdp-proxy` / `cdp` 直接进 PATH。

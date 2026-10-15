---
name: cdp-debug
description: >
  通过 CDP（Chrome DevTools Protocol）**直接控制用户已运行的 Chrome**，
  支持实时调试、元素观察、截图、事件监听、以及点击/输入/键盘等自发操作。
  场景：前端调试、运行态观察、自发 UI 交互、Network/Console/DOM 事件捕获、
  以及**与静态源码分析协同**（源码定位调用链 → CDP 实证，CDP 抓到现象 → 回源码追入口）。
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
- **源码协同分析**：站点 SPA/混淆 bundle/内部 API，光看运行态 DOM 是盲人摸象时，静态源码与 CDP 双向互查（SOP-F）

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

重启 IDE 后 agent 会在 tool 列表里看到 **18 个 cdp tools**，直接调用即可。

### 18 个 MCP tools

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
| `enable_domain` | 启用 CDP 事件域（幂等，重连后自动恢复） | `domain: str` |
| `get_events` | 读事件缓冲（最近 200 条） | `domain?: str` |
| `clear_events` | 清空事件缓冲 | 无 |
| `connection_status` | 查连接状态（卡住/连不上的第一步，零副作用） | 无 |
| `send_cdp` | **全协议透传口子**：发任意原生 CDP 命令（Debugger.getScriptSource / DOM.* / Network.* …），无白名单，调用方自负其责 | `method: str, params?: dict, browser_level?: bool` |

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

## 标准作业流程（SOP，agent 必须按场景执行，禁止自由发挥）

### SOP-0 开工自检（任何会话第一次用 CDP）

1. `detect_chrome`：`found=false` → 停止操作，把返回的指引原话转告用户（开 Chrome / chrome://inspect 勾选），**不要反复重试**
2. 需要确认当前状态时 `connection_status`：看 `alive` / `last_error` / `enabled_domains`，不靠猜
3. 首次连接 Chrome 弹授权框 → 请用户点允许，不要连发命令

### SOP-A 页面取证（DOM / 样式 / 布局核查）

1. `ensure_tab(url_substr="<站点特征>")` 锁定目标 tab
2. **一次 eval 取全**（不要零散发十几次）：URL/title + 目标元素 `getBoundingClientRect()` + `getComputedStyle()` 关键字段，参考文末观察 JS
3. 元素查询返回 `null` → 先确认选择器是否命中（Shadow DOM / iframe / 动态挂载 / 拼写），**禁止凭印象下结论或改代码**
4. `take_screenshot` 默认 jpeg 即可；结论必须引用具体数值（x/y/w/h/display/z-index），不写"看起来在右边"

### SOP-B 自发交互（点击 / 输入，复现 bug 或触发场景）

1. **先验位再点**：eval 取矩形，确认元素存在、`w/h>0`、非 `display:none`、在视口内
2. `click(selector=...)` —— 内部已是完整手势序列（pointerdown→mousedown→pointerup→mouseup→click），不要用 eval 调 `el.click()` 单点兜底（部分站点处理器不响应单点）
3. **必须验证结果**：eval 读状态变化 或 截图核对。禁止"点了 = 成功"
4. selector 点击无效 → 坐标点击（eval 拿到的 x/y）兜底一次；仍无效 → 取证后回报，不重复猛点
5. 登录 / 验证码 / 人机验证 / 支付 → 交用户手动完成，agent 不硬闯
6. 每步操作之间留 0.5~2s 给站点反应，不要连击

### SOP-C 网络 / 播放链路取证（弹窗、跳转、视频源接口）

1. `clear_events` → 2. `enable_domain("Network")`（需要控制台加 `"Runtime"`，导航信息加 `"Page"`）
3. **先 enable 再触发操作**：缓冲只能收到启用之后的事件，attach 之前发生的请求看不到（`get_events` 为空不等于没有请求）
4. 触发：能 agent 点的走 SOP-B；需要登录态/复杂手势的请用户手动操作，告知"请在 {N} 秒内完成操作"
5. 等 1~3s → `get_events("Network")`
6. 梳理方法：`requestWillBeSent` 与 `responseReceived` 按 **requestId 配对**；重定向看同一 requestId 上的 redirect 链；重点读 url / method / status / mimeType
7. 环形缓冲只有 200 条，复杂链路分批：每阶段 clear → 操作 → 取走

### SOP-D 注入样式 / 脚本验证（站点 adapter 开发）

1. eval 先验证选择器命中数量（`document.querySelectorAll(sel).length`），再注入
2. eval 注入 CSS/JS，返回受影响元素数；**不要直接改 adapter 源码赌效果**
3. 验证生效：eval 读 `getComputedStyle` 具体属性 或 截图
4. 观察 React/框架水合：注入的节点可能被重渲染移除，需重复验证 2 次（间隔 1s）确认是否被吞
5. 验证通过的表达式/选择器再回写源码；没验证过的选择器不许进 commit

### SOP-E 故障处置（按现象对号入座）

| 现象 | 处置 |
|---|---|
| 命令卡很久 | **已内置 20s 超时**，不会再无限挂；超时后下一次调用自动重连。同一操作**只重试一次**，再失败 → `connection_status` 看 `last_error` |
| Chrome 刚重启过 / 调试开关被关 | 任意调用会自动重连（2 次尝试）；重连后自动回到原 tab、自动恢复已 enable 的域（`connection_status` 可确认） |
| `last_error` 提示未开调试 | 原话转告用户：chrome://inspect → 勾选 Allow remote debugging；不要自己启动浏览器 |
| 截图偶发黑屏/卡住 | 视频页已知问题，已内置 surface→DOM 层→置前三级兜底；**不要反复重拍**。像素级排查才用 `fmt="png"` |
| `eval` 返回 `{"_error":...}` | 这是 JS 侧异常文本，先读内容修表达式（语法错/跨域/undefined 属性），不是连接问题 |
| `connection_status.alive=false` 但 Chrome 在 | 下次调用自动重建；若反复重建失败，看 `last_error`（多半是调试授权被撤/端口变了） |

### SOP-F 源码协同分析（静态源码 ↔ CDP 运行态，双向互查）

**核心原则：CDP 给运行态事实，源码给结构和意图；任何一方的推测都必须经另一方实证才允许写成结论。**

**什么时候必须上源码**（只靠运行态等于盲人摸象）：
- 要知道点击之后的**内部调用链**：框架 MVC/ViewController 生命周期、事件处理器绑在谁身上
- DOM class 动态/混淆，需要**稳定锚点**：源码里的方法名、枚举、常量比运行态 class 可靠
- 请求**参数/签名怎么构造**：Network 只能看到发出去的结果，看不到生成逻辑
- 要调站点内部 API（如 `unsafeWindow.services.*`）：必须先在源码确认方法签名、参数、返回类型、是否需要回调

**第一步：拿源码（按成本从低到高）**

1. DevTools Sources 直接看（未压缩站点）
2. **CDP 列全脚本 + 取原文**：`clear_events` → `enable_domain("Debugger")` → 刷新页面/导航触发（Debugger.enable 也会补发已加载脚本的 scriptParsed）→ **立刻** `get_events("Debugger")` 取走（`scriptParsed` 事件量大，200 条环形缓冲会被刷爆，动作要连贯；提取 `scriptId` / `url` / `sourceMapURL`）→ 对目标脚本调 `send_cdp("Debugger.getScriptSource", {"scriptId": id})` 取**浏览器实际执行的原文**（动态 eval 脚本也能取，不走 HTTP、不怕防盗链）；有 source map 的优先拉 `.map` 还原原始源码
3. Network/Sources 下载 bundle 到本地分析；混淆代码走反混淆 pipeline，产物**分版保留**：`raw`（原始下载）→ `decoded`（字典解码）→ `human`（语义化）+ `keymap`，解码步骤脚本化可重跑，完成后用解析器（acorn 等）做语法验证
4. Electron 应用：`npx asar extract app.asar dir` 解包后分析；批量模块/IPC 关系可用 `npx rea-agents analyze-javascript-application <dir>`
5. 反编译产物归档进项目的 facts/ 目录，不留临时目录；关键 API/枚举/踩坑写成事实文档

**方向①：源码 → CDP（先读码，形成假设，再实证）**

1. Grep 锚点定位：URL path、响应字段名、按钮文案、已知 class、枚举名 → 命中模块/函数
2. 读调用链，形成**可证伪假设**：selector 是什么、参数怎么拼、该调哪个高层方法
3. CDP eval 实证：`typeof unsafeWindow.services.X === 'function'`、枚举实际值、`document.querySelectorAll(sel).length`
4. 假设被推翻 → **回源码换路径**，禁止在运行态无依据地硬试/瞎点
5. 写进 adapter 的每个 selector/API 必须双证据齐全：**源码出处（文件+关键词）+ CDP 实证结果**

**方向②：CDP → 源码（抓到现象，回码追入口）**

1. 按 SOP-C 抓到请求 / console 异常 / DOM 现象
2. 拿 URL path、字段名、报错栈里的特征字符串回源码 Grep
3. 顺调用链**向上**找入口：谁发的请求、点击处理器绑在哪、VC 生命周期哪一步触发
4. 回 CDP 在入口处验证（手动调入口方法 / 在入口断点观察）

**纪律（踩坑实证）**：
- **读到 ≠ 跑着**：源码版本可能与线上不一致、代码分支可能根本没走到——一切以 CDP 实证为准
- 静态还原不了的混淆残名（压缩器销毁的局部变量名）标注"无法还原"，**不臆造语义名**
- 调内部 API 前先在源码确认它是**高层安全方法**（内部已正确处理订阅/回调）还是需要完整参数的低层 DAO——错误手动订阅/observe 可直接崩 SPA
- 每次逆向的结论回写事实文档（API 签名、枚举值、锚点 selector + 源码出处），同一目标不重复逆向

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
- **源码协同是标配不是例外**：SPA / 混淆站点 / 内部 API 场景下，禁止只凭运行态表面现象下结论——按 SOP-F 拿源码定位调用链、CDP 实证后再动手。运行态给事实，源码给结构，双向互证。

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
| `cdp_mcp.py` | **MCP server**（18 tools，stdio 协议，推荐入口；命令 20s 超时 + 自动重连保活 + send_cdp 全协议透传） |
| `cdp_proxy.py` | HTTP 9333 代理（fallback，常驻长连接） |
| `cdp.py` | CLI：detect / open / list / eval / shot / navigate |

安装：`pip install -e .`（repo 根）。之后 `cdp-mcp` / `cdp-proxy` / `cdp` 直接进 PATH。

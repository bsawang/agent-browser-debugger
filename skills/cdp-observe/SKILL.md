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
   （默认 profile 保留登录；每次**新连接**弹授权，用常驻代理避免）
2. 或桌面「Chrome（Claude可接管）」快捷方式（传统 `--remote-debugging-port=9222 --user-data-dir`，无授权但独立 profile）

**检查可调试**（一行命令，不弹授权）：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect
```

> ⚠️ 坑：inspect 模式下 HTTP `/json/version` 是 **404**（此模式不走 HTTP 发现，改由 `DevToolsActivePort` 文件给 ws 地址）；`detect` 已同时覆盖两种模式。

## 工作流（⚠️ 硬性要求：一律走常驻代理长连接）
> chrome://inspect 模式下每次**新 CDP 连接**弹一次授权。
> 常驻代理启动时连一次（弹一次 Allow），之后所有命令复用同一连接——**再小的调试也只用代理**。

**0. 确保代理在跑**（顺序：先 `detect` 确认 Chrome 可调试 → 再查/起代理）：

**跨平台（Python 兜底，推荐）**：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect   # 快速探测（不弹授权）
python <repo>/skills/cdp-observe/scripts/cdp.py ensure   # 代理探活 + 自动起（没跑就起，起时弹一次授权）
```

**或者手动分步（PowerShell 兼容）**：
```powershell
# 快速探测（不弹授权）
python <repo>/skills/cdp-observe/scripts/cdp.py detect

# 代理探活 — 没跑就起，起时弹一次授权
try {
  Invoke-WebRequest -Uri "http://127.0.0.1:9333/" -Method POST -ContentType "application/json" -Body '{"pages":1}' -TimeoutSec 2 | Out-Null
} catch {
  $log = Join-Path $PWD "_cdp_proxy.log"
  Start-Process python -ArgumentList "<repo>/skills/cdp-observe/scripts/cdp_proxy.py","9333" -RedirectStandardOutput $log -RedirectStandardError $log -WindowStyle Hidden
  Start-Sleep 2
}
```

> Chrome 重启后代理连接失效 → 重跑上面命令重启代理（会再弹一次授权）。

**1. 观察类命令**：
```bash
# 执行 JS
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'

# 截图
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'

# 导航
curl -s http://127.0.0.1:9333/ -d '{"navigate":"<url>"}'

# 列 page tab
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'

# 切换目标页（代理启动后可热切换，不用重连）
curl -s http://127.0.0.1:9333/ -d '{"target":"<url子串>"}'

# 确保目标 tab 存在 — 有则复用，无则创建新 tab
curl -s http://127.0.0.1:9333/ -d '{"ensure":"<url子串>"}'

# 显式新建 tab 打开 URL
curl -s http://127.0.0.1:9333/ -d '{"open":"<url>"}'
```

> **目标页选择**：代理启动时自动 `ensure_tab` — 优先匹配 `CDP_TARGET` 环境变量指定的 URL 子串，然后找第一个非 chrome:// 页面；**所有 tab 都没有时自动创建 `about:blank`**。

**2. 操作类命令（agent 自发交互）**：
```bash
# 点击 CSS selector 元素
curl -s http://127.0.0.1:9333/ -d '{"click":"button.submit"}'

# 右键点击
curl -s http://127.0.0.1:9333/ -d '{"click":{"selector":"button","button":"right"}}'

# 坐标点击
curl -s http://127.0.0.1:9333/ -d '{"click":{"x":100,"y":200}}'

# 悬停
curl -s http://127.0.0.1:9333/ -d '{"hover":"input.search"}'

# 聚焦元素并输入
curl -s http://127.0.0.1:9333/ -d '{"type":{"selector":"input.search","text":"hello"}}'

# 在当前焦点位置输入（比如先 click 聚焦，再 type）
curl -s http://127.0.0.1:9333/ -d '{"type":"hello world"}'

# 按键
curl -s http://127.0.0.1:9333/ -d '{"press_key":"Enter"}'
curl -s http://127.0.0.1:9333/ -d '{"press_key":"Tab"}'
curl -s http://127.0.0.1:9333/ -d '{"press_key":"Escape"}'
curl -s http://127.0.0.1:9333/ -d '{"press_key":"ArrowDown"}'

# 处理 JS 对话框（alert/confirm/prompt）
curl -s http://127.0.0.1:9333/ -d '{"handle_dialog":true}'
curl -s http://127.0.0.1:9333/ -d '{"handle_dialog":{"accept":true,"promptText":"some input"}}'
```

**3. 事件观察（被动监听 + 缓冲）**：
```bash
# 启用 CDP 事件域（Network / DOM / Page / Runtime / Log）
curl -s http://127.0.0.1:9333/ -d '{"enable":"Network"}'
curl -s http://127.0.0.1:9333/ -d '{"enable":"DOM"}'

# 触发操作 → 拉取事件
curl -s http://127.0.0.1:9333/ -d '{"events":"Network"}'     # 只要 Network.*
curl -s http://127.0.0.1:9333/ -d '{"events":1}'             # 全部事件
curl -s http://127.0.0.1:9333/ -d '{"clear_events":1}'        # 清空
```

**典型自发操作流程**：
```
目标：在百度搜索 "hello" 并看结果
  1. navigate → https://www.baidu.com
  2. type → {"selector":"#kw","text":"hello"}
  3. press_key → "Enter"
  4. shot → 截图看结果
  5. enable + events → Network 事件看搜索请求
```

**单次 `cdp.py` 仅兜底**（代理不可用/无法重起时）：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect
python <repo>/skills/cdp-observe/scripts/cdp.py open '<url>'
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
python <repo>/skills/cdp-observe/scripts/cdp.py navigate '<url>'
```

> python 需 aiohttp（`pip install aiohttp`）

## 常用观察 JS（通用，任意页面可用）
- 页面信息（url/title）：
  ```js
  JSON.stringify({url: location.href, title: document.title})
  ```
- 读元素文本：
  ```js
  (()=>{const e=document.querySelector('<选择器>'); return e?.innerText?.slice(0,500) ?? null;})()
  ```
- 元素尺寸/位置/样式：
  ```js
  (()=>{const e=document.querySelector('<选择器>'); if(!e) return null;
   const s=getComputedStyle(e), r=e.getBoundingClientRect();
   return JSON.stringify({w:r.width,h:r.height,x:r.x,y:r.y,display:s.display});})()
  ```

## 约定 ⚠️
- **一律走常驻代理长连接**：每条单次命令各弹一次授权，仅代理不可用且无法重起时才兜底
- **不自行启动浏览器**：Chrome 需已在运行（由用户启动）。代理会自动创建 tab，但不会启动整个浏览器进程
- **操作 = 调试手段**：click/type/press_key 是为了复现 bug、触发调试场景、让页面进入目标状态——不是替代用户正常浏览。任务完成后停止操作，转为观察
- **持久化改动先征得同意**：需要改动用户浏览器持久内容（保存状态、改设置、删数据等）时，先问

## 与 browser_use 的区别
| | cdp-debug | browser_use |
|---|---|---|
| 连接方式 | CDP WebSocket 直连 | Playwright 驱动 |
| 浏览器实例 | **用户已运行的 Chrome**（保留登录态/tab） | 自动启独立 Chromium（干净 profile） |
| 事件监听 | ✅ enable 域 + 200 条事件缓冲 | ❌ 无 |
| 运行态插入 | ✅ 就是为这个设计的 | ❌ 只能自己启新浏览器 |
| 选择器 | CSS selector（标准 DOM） | CSS selector |
| 适用场景 | 调试、观察、运行态复现 | 自动化任务、表单填写、无状态操作 |

当需要操作**用户正在用的 Chrome**（有登录态、有 tab、有状态）时，选 cdp-debug。
当需要一个**干净的、独立的、可任意控制**的浏览器实例（不怕污染、不怕打断）时，选 browser_use。

## 脚本
`scripts/cdp_core.py` — 共享核心（CDP 类 + detect + select + ensure_tab + click/type/hover/press_key/handle_dialog）← 可嵌入
`scripts/cdp.py` — CLI：detect / open / list / eval / shot / navigate
`scripts/cdp_proxy.py` — HTTP 代理：常驻连接 + ensure_tab + 事件缓冲 + 操作命令

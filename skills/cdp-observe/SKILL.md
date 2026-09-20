---
name: cdp-observe
description: >
  需要实时查看/调试浏览器前端状态时使用——DOM/布局/渲染/预览表现、执行结果在界面的呈现、
  任何「前端实际长什么样/为什么这样显示」的疑问。
  通过 Chrome DevTools 协议（CDP）接管用户已运行的 Chrome，提供实时调试能力。
  **不自行启动/重启浏览器**，但会在目标 tab 不存在时自动创建。
---

# CDP 接管观察（Chrome）

## 什么时候用
- 看浏览器里真实的 DOM / 布局 / 渲染 / 交互状态
- 任何前端应用的调试：组件渲染、元素状态、预览渲染、执行结果在界面的表现
- 任何「前端实际长什么样 / 为什么这样显示」的疑问

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
```bash
# 快速探测（不弹授权）
python <repo>/skills/cdp-observe/scripts/cdp.py detect

# 代理探活 + 自动起（没跑就起，起时弹一次授权）
curl -s -m 2 http://127.0.0.1:9333/ -d '{"pages":1}' >/dev/null 2>&1 \
  || (python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 > <repo>/_cdp_proxy.log 2>&1 &)
sleep 1
```
> Chrome 重启后代理连接失效 → 重跑上面命令重启代理（会再弹一次授权）。

**1. 所有命令走代理**：
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

> **目标页选择**：代理启动时自动 `ensure_tab` — 优先匹配 `CDP_TARGET` 环境变量指定的 URL 子串，然后找第一个非 chrome:// 页面；**所有 tab 都没有时自动创建 `about:blank`**，不再出现「没 tab 就退出」。启动后可随时 `{"ensure":"..."}` 或 `{"open":"..."}` 切换。

**单次 `cdp.py` 仅兜底**（代理不可用/无法重起时；每条命令各弹一次授权，优先 `multi` 一次连多条）：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect          # 只读探测（不弹授权）
python <repo>/skills/cdp-observe/scripts/cdp.py open '<url>'   # 新建 tab
python <repo>/skills/cdp-observe/scripts/cdp.py list            # 列 tab
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
python <repo>/skills/cdp-observe/scripts/cdp.py navigate '<url>'
```

> python 需 aiohttp（`pip install aiohttp`）

## 事件观察（内置）
代理自动监听所有 CDP 事件并缓冲最近 200 条，随时拉取：

```bash
# 启用 CDP 事件域（如 Network、DOM、Page）
curl -s http://127.0.0.1:9333/ -d '{"enable":"Network"}'

# 触发页面操作（用户在浏览器操作，或用 {"navigate":"..."} 触发）

# 拉取事件（可选 domain 过滤）
curl -s http://127.0.0.1:9333/ -d '{"events":"Network"}'     # 只要 Network.*
curl -s http://127.0.0.1:9333/ -d '{"events":1}'             # 全部事件
curl -s http://127.0.0.1:9333/ -d '{"clear_events":1}'        # 清空
```

**典型用法**：
- **抓网络请求**：`{"enable":"Network"}` → 操作页面 → `{"events":"Network"}` 看 `requestWillBeSent` / `responseReceived`
- **观察 DOM 变更**：`{"enable":"DOM"}` → 页面元素变化时 `documentUpdated` 事件
- **抓页面加载事件**：`{"enable":"Page"}` → `loadEventFired` / `domContentEventFired`

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
- **调试一律走常驻代理长连接**：禁止直接调 `cdp.py` 单次命令（每条各弹一次授权）；仅代理不可用且无法重起时才兜底
- **只观察 + 临时调试**：工具具备完整的 CDP 写能力，但调试场景下应优先用只读能力。临时 JS 注入在页面刷新后还原，不主动做持久化改动
- **不自行启动浏览器**：Chrome 需已在运行（由用户启动）。代理会自动创建 tab，但不会启动整个浏览器进程
- 需要改动用户浏览器持久内容（保存状态、改设置等）时，**先征得用户同意**

## 文档索引
- Chrome 远程调试配置：[`docs/setup.md`](../docs/setup.md)
- 代理命令速查：[`docs/commands.md`](../docs/commands.md)
- 项目 README（定位 + 可嵌入 API）：[`README.md`](../README.md)

## 脚本
`scripts/cdp_core.py` — 共享核心（CDP 类 + detect + select + **ensure_tab**）← 可嵌入
`scripts/cdp.py` — CLI：detect / open / list / eval / multi / shot / navigate
`scripts/cdp_proxy.py` — HTTP 代理：常驻连接 + ensure_tab 自动创建 + 事件缓冲

---
name: cdp-observe
description: >
  需要实时查看/调试浏览器前端状态时使用——DOM/布局/渲染/预览表现、执行结果在界面的呈现、
  任何「前端实际长什么样/为什么这样显示」的疑问。适用于任意浏览器应用
  （ComfyUI、Flask/Vue 页面、自建 web 工具等，不限定具体软件）。
  通过 Chrome DevTools 协议（CDP）接管用户已运行的 Chrome，只读观察，
  **不自行启动/重启浏览器**。
---

# CDP 接管观察（Chrome）

## 什么时候用
- 看浏览器里真实的 DOM / 布局 / 渲染 / 交互状态
- 任意浏览器应用的前端排查：ComfyUI 节点 widget、Vue/React 组件、普通页面元素、预览渲染、执行结果在界面的表现
- 任何「前端实际长什么样 / 为什么这样显示」的疑问

## 前置（用户环境）
用户 Chrome 需开启远程调试，二选一：
1. **chrome://inspect/#remote-debugging** 勾选「Allow remote debugging for this browser instance」
   （默认 profile 保留登录；每次**新连接**弹授权，用常驻代理避免）
2. 或桌面「Chrome（Claude可接管）」快捷方式（传统 `--remote-debugging-port=9222 --user-data-dir`，无授权但独立 profile）

**检查可调试**（判据＝其中任一即可：`/json/version` 返 **200** 或 `DevToolsActivePort` 文件存在）：
```bash
code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9222/json/version)
port_file="$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort"
if [ "$code" = "200" ]; then echo "传统模式可调试"; \
elif [ -f "$port_file" ]; then echo "inspect模式可调试: ws://127.0.0.1:$(head -1 "$port_file")$(sed -n 2p "$port_file")"; \
else echo "Chrome未开调试"; fi
```
- `/json/version` 返 **200** → 传统模式可用
- **404/空** → **仍是 inspect 模式、可调试**——此模式不走 HTTP json 发现，改由 `DevToolsActivePort` 文件给 ws 地址（`ws://127.0.0.1:<port><path>`）
- **两者都无** → Chrome 未开调试，**不要自行启动/重启浏览器**，提示用户开启远程调试后继续

> ⚠️ 坑：inspect 模式下 `9222/json/version` 是 **404/空**，**不等于没开调试**——所以**不能只看 `/json/version` 有无响应**判可调试，必须两个判据都查。

## 工作流（⚠️ 硬性要求：一律走常驻代理长连接）
> 一次调试少则 4~5 条命令；单次命令每条都是新连接、各弹一次授权。
> **即使再小的调试也只用常驻代理**，不直接调 `cdp.py`（代理不可用时才兜底，见下）。

**0. 先查代理 9333，没跑再起**（顺序：① 前置确认 Chrome 可调试 → ② 查 9333 在不在 → ③ 不在才起）：
```bash
curl -s -m 2 http://127.0.0.1:9333/ -d '{"pages":1}' >/dev/null 2>&1 \
  || (python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 > <repo>/_cdp_proxy.log 2>&1 &)
sleep 1
```
> 代理依赖 Chrome 已可调试——前置未确认前**不直接起代理**（起了也连不上）。
> Chrome 重启后代理连接失效 → 重跑上面命令重启代理（会再弹一次授权）。

**1. 所有命令走代理**（连接保持，不弹窗）：
```bash
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
```

> **目标页**：代理启动时选定——有 `CDP_TARGET` 用其 URL 子串（调试任意应用），
> 否则选含 `8188` 的 tab（ComfyUI 常用），再无则第一个 tab：
> ```bash
> CDP_TARGET=127.0.0.1:5000 python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &
> ```

**单次 `cdp.py` 仅兜底**（代理不可用/无法重起时；每条命令各弹一次授权，优先 `multi` 一次连多条）：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py list
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...   # 一次连接多条
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
```

> python 需 aiohttp：系统 python 缺则用运行副本
> `H:\ComfyUI_Windows_portable\python_standalone\python.exe <脚本> ...`

## 常用观察 JS（通用，任意页面可用）
- 页面信息（url/title）：
  ```js
  JSON.stringify({url: location.href, title: document.title})
  ```
- 读元素文本（`<选择器>` 替换为目标）：
  ```js
  (()=>{const e=document.querySelector('<选择器>'); return e?.innerText?.slice(0,500) ?? null;})()
  ```
- 元素尺寸/位置/样式：
  ```js
  (()=>{const e=document.querySelector('<选择器>'); if(!e) return null;
   const s=getComputedStyle(e), r=e.getBoundingClientRect();
   return JSON.stringify({w:r.width,h:r.height,x:r.x,y:r.y,display:s.display});})()
  ```
- 列页面 video/img 元素：
  ```js
  (()=>JSON.stringify([...document.querySelectorAll('video,img')].map(x=>[x.tagName, x.src||x.currentSrc])))()
  ```

> 特定软件/站点的观察 JS 与踩坑按专题归档，见「命令归档规约」：ComfyUI → `docs/comfy/commands.md`，其他专题按需新建文档。

## 约定 ⚠️
- **调试一律走常驻代理长连接**：禁止直接调 `cdp.py` 单次命令（每条各弹一次授权）；仅代理不可用且无法重起时才兜底，且优先 `multi` 一次连多条
- **只观察 + 临时调试**：不保存页面/应用状态、不改浏览器设置/配置/书签/扩展
- **不自行启动/重启浏览器**：用户浏览器常态运行；确需重启时提示用户操作，不代劳
- 临时 JS 注入只在该页面进程内生效，刷新即还原；结束不留痕
- 需要改动用户浏览器持久内容（保存应用状态、改设置等）时，**先征得用户同意**

## 命令归档规约 ⚠️
调试中遇到的**新可复用命令 / 新坑，定案后归档到 agent-browser-debugger 项目对应文档**（追加，不覆盖）：

| 命令类型 | 归档位置 |
|---|---|
| 调试本身（Chrome/CDP 通用） | `E:\work\ai\agent-browser-debugger\docs\commands.md` |
| **ComfyUI 专题**（观察 JS、执行、重启、节点/预览坑） | `E:\work\ai\agent-browser-debugger\docs\comfy\commands.md` |
| 其他应用专题（站点/软件专属命令） | `E:\work\ai\agent-browser-debugger\docs\<主题>\commands.md`（按需新建） |
| Chrome 远程调试原理与配置 | `E:\work\ai\agent-browser-debugger\docs\setup.md` |

SKILL.md 只放触发/工作流/约定，具体命令一律归档到上述文档；新条目一句话（命令 + 用途）即可。

## 脚本
`scripts/cdp.py` — 单次命令（单连接）：`list` / `eval` / `multi` / `shot`
`scripts/cdp_proxy.py` — 常驻代理（推荐）：后台保持单连接，本地端口收发命令，避免重复授权弹窗

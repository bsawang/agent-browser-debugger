---
name: cdp-observe
description: >
  需要实时查看/调试浏览器前端状态时使用——ComfyUI 节点 DOM/widget 布局、前端渲染异常、
  节点预览问题、执行结果在界面的表现、任何「前端实际长什么样/为什么这样显示」的疑问。
  通过 Chrome DevTools 协议（CDP）接管用户已运行的 Chrome，只读观察，
  **不自行启动/重启浏览器**。
---

# CDP 接管观察（Chrome）

## 什么时候用
- 看浏览器里真实的 DOM / widget / 布局 / 渲染状态
- ComfyUI 前端：节点 widget 结构、位置布局、预览渲染、执行结果在界面的表现
- 任何「前端实际长什么样 / 为什么这样显示」的排查

## 前置（用户环境）
用户 Chrome 需开启远程调试，二选一：
1. **chrome://inspect/#remote-debugging** 勾选「Allow remote debugging for this browser instance」
   （默认 profile 保留登录；每次**新连接**弹授权，用常驻代理避免）
2. 或桌面「Chrome（Claude可接管）」快捷方式（传统 `--remote-debugging-port=9222 --user-data-dir`，无授权但独立 profile）

**检查端口**：`curl -s -m 3 http://127.0.0.1:9222/json/version`
- 有响应 → 传统模式可用
- 404 或空 → inspect 模式（HTTP 404 属正常），读 `$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort` 拿连接地址
- 完全无响应 → **不要自行启动/重启浏览器**，提示用户开启远程调试后继续

## 工作流
**推荐：常驻代理**（启动时弹一次授权，之后随时操作不弹窗）：
```bash
# 后台启动
python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &
# 发命令（连接保持）
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
```

**或单次命令**（每次连接弹一次授权）：
```bash
python <repo>/skills/cdp-observe/scripts/cdp.py list
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...   # 一次连接多条
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
```

> python 需 aiohttp：系统 python 缺则用运行副本
> `H:\ComfyUI_Windows_portable\python_standalone\python.exe <脚本> ...`

## 常用观察 JS（ComfyUI）
- 节点 widget 结构（name/type/y/高度）：
  ```js
  (()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
   return JSON.stringify((n?.widgets||[]).map(w=>({n:w.name,t:w.type,y:w.y,h:w.computedHeight})),null,1);})()
  ```
- 节点 DOM / Vue 预览区（视频预览是 `video-preview` 组件，不在 node.widgets）：
  ```js
  (()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
   const d=document.querySelector(`.lg-node[data-node-id="${n.id}"]`);
   const c=d?.querySelector('.lg-node-content');
   return JSON.stringify(c?[...c.children].map(x=>String(x.className).slice(0,40)):null);})()
  ```
- 触发执行 / 居中节点 / 页面 video 元素 / 后端状态等更多命令见 `docs/comfy/commands.md`

## 约定 ⚠️
- **只观察 + 临时调试**：不保存工作流、不改浏览器设置/配置/书签/扩展
- **不自行启动/重启浏览器**：用户浏览器常态运行；确需重启时提示用户操作，不代劳
- 临时 JS 注入只在该页面进程内生效，刷新即还原；结束不留痕
- 需要改动用户浏览器持久内容（保存工作流、改设置等）时，**先征得用户同意**

## 命令归档规约 ⚠️
调试中遇到的**新可复用命令 / 新坑，定案后归档到 agent-browser-debugger 项目对应文档**（追加，不覆盖）：

| 命令类型 | 归档位置 |
|---|---|
| 调试本身（Chrome/CDP 通用） | `E:\work\ai\agent-browser-debugger\docs\commands.md` |
| **ComfyUI 专题**（观察 JS、执行、重启、节点/预览坑） | `E:\work\ai\agent-browser-debugger\docs\comfy\commands.md` |
| Chrome 远程调试原理与配置 | `E:\work\ai\agent-browser-debugger\docs\setup.md` |

SKILL.md 只放触发/工作流/约定，具体命令一律归档到上述文档；新条目一句话（命令 + 用途）即可。

## 脚本
`scripts/cdp.py` — 单次命令（单连接）：`list` / `eval` / `multi` / `shot`
`scripts/cdp_proxy.py` — 常驻代理（推荐）：后台保持单连接，本地端口收发命令，避免重复授权弹窗

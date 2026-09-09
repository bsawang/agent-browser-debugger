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

## 2026-08-27 skill 泛化 + 硬性要求长连接

**背景**：① 用户指出 cdp-observe 是通用浏览器调试方式，却被 frontmatter 描述/示例写死成 ComfyUI 限定，导致调试其他 web 前端不会触发；② 实测调试增强器宽度时连续十几次 `cdp.py` 单次命令，chrome://inspect 模式每条新连接各弹一次授权，用户确认到烦，立下硬性要求。

**改动**：
- **skill 泛化**：frontmatter description → 任意浏览器应用（ComfyUI 降为示例）；「什么时候用」泛化；「常用观察 JS」换成通用示例（页面信息/读文本/元素尺寸样式/列 video-img），ComfyUI 专属 JS 全部归 `docs/comfy/commands.md`；约定「不保存工作流」→「不保存页面/应用状态」；归档规约加「其他应用专题 `docs/<主题>/commands.md`」行
- **脚本支持任意目标页**：`cdp.py` / `cdp_proxy.py` 新增 `select_target()`，目标页选择顺序 `CDP_TARGET`（URL 子串，调试任意应用）→ 8188（ComfyUI 默认）→ 第一个 tab
- **硬性要求长连接**（用户指令）：调试一律走常驻代理 `cdp_proxy.py`（启动弹一次授权，之后 curl 发命令不弹窗）；禁止直接调 `cdp.py` 单次命令（每条各弹一次授权）；skill 工作流加「0. 确保代理在跑」步骤（curl 探测 9333，没跑就起）；约定区加硬性规则；`docs/commands.md`、`.claude.md` 同步改「常驻=唯一方式、单次=仅兜底」

**关键实现点**：
- 新前端（comfyui_frontend_package 1.48.7）DOM widget 布局尺寸走 `computeLayoutSize`（读 CSS 变量/`getMinHeight`/`getHeight`），`minWidth:0` 不驱动节点宽——节点宽由其他 widget + `node.computeSize` 决定，面板元素 `width:100%` 即可填满节点
- 坑：运行副本 `custom_nodes/ComfyUI-bsawang/` 下有**两份** `prompt_enhancer_ui.js`，根目录一份是残留副本，实际服务的是 `web/`（`WEB_DIRECTORY="./web"`）；改错位置刷新无效

**关键命令**：常驻代理 `curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'`；确保在跑 `curl -s -m 2 http://127.0.0.1:9333/ -d '{"pages":1}' || (python skills/cdp-observe/scripts/cdp_proxy.py 9333 &)`
**相关**：aigc-study `assets/nodes/bsawang-nodes/web/prompt_enhancer_ui.js`（增强器面板自适应宽度，另记于 bsawang-nodes AGENT-LOGGER）；全局 `~/.claude/skills/cdp-observe/`（已同步）

## 2026-09-10 cdp-observe 工作流补「先查可调试 → 查9333 → 再起」顺序 + 双判据

**背景**：排查「9333 开了但连不上」——实测 9222（Chrome 远程调试）在监听、9333（常驻代理）没起，用户误以为开了 9333。另发现本机 `9222/json/version` 返 **404/空**（inspect 模式特征），代理靠读 `DevToolsActivePort` 文件才连上。原 SKILL.md「步骤 0」只写「curl 9333 没跑就起」，没先确认 Chrome 可调试，信息不全。

**改动**（全局 `~/.claude/skills/cdp-observe/SKILL.md`）：
- 前置「检查端口」→「**检查可调试**」双判据：`/json/version` 返 **200** 或 `DevToolsActivePort` 文件存在，任一即算可调试，并给一行探测 bash
- 明确坑：inspect 模式 `9222/json/version` 是 **404/空 ≠ 没开调试**，不能只看 `/json/version` 有无响应判可调试，必须两判据都查
- 工作流「步骤 0」改为「先查代理 9333，没跑再起」，补顺序 ① 前置确认可调试 → ② 查 9333 → ③ 不在才起；注明代理依赖 Chrome 已可调试、前置未确认前不直接起

**关键命令**：可调试探测 `code=$(curl -s -m 3 -o /dev/null -w '%{http_code}' http://127.0.0.1:9222/json/version)`；inspect 模式 ws 地址经 `$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort`（`ws://127.0.0.1:<port><path>`）拼出
**相关**：`E:\work\ai\agent-browser-debugger\skills\cdp-observe\scripts\{cdp,cdp_proxy}.py`——`get_browser_ws_url()` 本就是 file 优先、回退 9222 HTTP 双分支，本改动只补了 skill 文档的「先判可调试再起代理」顺序

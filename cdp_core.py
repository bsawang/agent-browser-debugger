#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 核心模块 — 浏览器调试基础设施，可被 agent skill 和其他项目（如 browser-action）嵌入。

导出公共 API:
  detect_ws_url()    → (ws_url, mode, tabs)   # 只读探测，不弹授权
  select_target(pages, url_substr)            # 从 page 列表选一个
  CDP 类：
    connect(ws_url)                              # 建立 WebSocket 连接
    start()                                      # 启动后台接收协程
    send(method, params, session_id)             # 发 CDP 命令
    on_event(handler) / off_event(handler)       # 事件监听
    pages()                                      # 列 page target
    attach_page(target_id)                       # attach 到指定 target
    create_target(url)                           # 创建新 tab
    close_target(target_id)                      # 关闭 tab
    ensure_tab(url_substr, create_url)           # 有则复用，无则创建
    eval(expr) / shot(path) / navigate(url)      # 便捷方法
    close()                                      # 关闭连接

设计参考 browser-action backend/src/injectors/cdp.ts：
  - pending Map + 后台接收协程（替换 while True 忙等）
  - 事件 handler 列表（支持 Network/DOM/Page 等事件监听）
  - detect / attach / create 分离
"""
import asyncio
import base64
import json
import os

import aiohttp

# —— Chrome 连接探测 ——

DEFAULT_PORT = 9222

# Windows virtual key codes (subset for press_key)
_KEY_CODE_MAP = {
    "Enter": 13, "Tab": 9, "Escape": 27, "Backspace": 8, "Delete": 46,
    "ArrowUp": 38, "ArrowDown": 40, "ArrowLeft": 37, "ArrowRight": 39,
    "Home": 36, "End": 35, "PageUp": 33, "PageDown": 34, "Insert": 45,
    " ": 32,
}


def default_user_data_dir():
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Google", "Chrome", "User Data")


def chrome_running() -> bool:
    """检测 Chrome 进程是否在跑（跨平台，用 tasklist/ps）。"""
    import subprocess
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq chrome.exe"],
                                 capture_output=True, text=True).stdout
            return "chrome.exe" in out.lower()
        else:
            out = subprocess.run(["pgrep", "-f", "chrome"], capture_output=True, text=True).stdout
            return bool(out.strip())
    except Exception:
        return False


async def detect_ws_url():
    """探测 Chrome 远程调试 WebSocket 地址（只读不连 ws，不弹授权）。

    返回：(ws_url, mode, tabs) 或 (None, None, [])
      mode: 'inspect' | 'traditional' | None
      tabs: 仅在 traditional 模式下可用（HTTP /json/list 可直接访问）
    """
    # 1. chrome://inspect 模式（Chrome 144+ 默认方式）
    ap = os.path.join(default_user_data_dir(), "DevToolsActivePort")
    if os.path.isfile(ap):
        try:
            with open(ap, encoding="utf-8") as f:
                lines = f.read().splitlines()
            if len(lines) >= 2:
                return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}", "inspect", []
        except Exception:
            pass

    # 2. 传统 --remote-debugging-port 模式
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"http://127.0.0.1:{DEFAULT_PORT}/json/version",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as r:
                ver = await r.json()
                ws_url = ver["webSocketDebuggerUrl"]
            # 顺便拉一下 tab 列表（传统模式 /json/list 可直接访问）
            tabs = []
            try:
                async with s.get(
                    f"http://127.0.0.1:{DEFAULT_PORT}/json/list",
                    timeout=aiohttp.ClientTimeout(total=3),
                ) as r:
                    raw = await r.json()
                    tabs = [
                        {"id": t.get("id"), "url": t.get("url", ""), "title": t.get("title", "")}
                        for t in raw
                        if t.get("type") == "page"
                    ]
            except Exception:
                pass
            return ws_url, "traditional", tabs
    except Exception:
        return None, None, []


# —— 目标页选择 ——

def select_target(pages, url_substr=None):
    """从 page target 列表选目标。

    优先级：url_substr 参数 > CDP_TARGET 环境变量 > 非 chrome:// 页面 > 第一个。
    （不硬编码任何特定应用端口，通用性由调用方保证）
    """
    needles = []
    if url_substr:
        needles.append(url_substr)
    env = os.environ.get("CDP_TARGET", "").strip()
    if env:
        needles.append(env)

    for n in needles:
        for p in pages:
            if n in p.get("url", ""):
                return p

    # 过滤掉 chrome:// / devtools://
    for p in pages:
        url = p.get("url", "")
        if not url.startswith(("chrome://", "devtools://")):
            return p

    return pages[0] if pages else None


# —— CDP 客户端 ——

class CDP:
    """CDP WebSocket 客户端（pending Map + 事件 handler 架构）。

    用法：
        c = CDP()
        await c.connect(ws_url)
        await c.start()                              # 启动后台接收协程
        target = await c.ensure_tab("example.com")   # 有则复用，无则创建
        await c.attach_page(target["targetId"])
        result = await c.send("Runtime.evaluate", {...})
        await c.close()
    """

    def __init__(self):
        self.ws = None
        self._http_session: aiohttp.ClientSession | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._handlers: list = []
        self._nid = 0
        self._session: str | None = None
        self._recv_task: asyncio.Task | None = None

        # —— 去重缓存 ——
        self._enabled_domains: set = set()          # 已 enable 的 CDP 域（Runtime/Page/Network/...）
        self._attached_targets: set = set()          # 已 attach 过的 targetId（同一 target 只 attach 一次）
        self._current_target_id: str | None = None   # 当前 self._session 对应的 targetId
        self._lock = asyncio.Lock()                  # 串行化 attach/enable（防并发竞态）

    # —— 连接生命周期 ——

    async def connect(self, ws_url: str):
        self._http_session = aiohttp.ClientSession()
        self.ws = await self._http_session.ws_connect(ws_url)

    async def start(self):
        """启动后台接收协程，必须在 connect() 之后调用。"""
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def _recv_loop(self):
        """持续接收 CDP 消息，分流到 pending Map 或事件 handler。"""
        try:
            async for msg in self.ws:
                data = msg.data if hasattr(msg, "data") else msg
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                self._dispatch(data)
        except Exception:
            pass

    def _dispatch(self, msg: dict):
        if not isinstance(msg, dict):
            return
        mid = msg.get("id")
        if mid is not None and mid in self._pending:
            fut = self._pending.pop(mid)
            if not fut.done():
                fut.set_result(msg)
            return
        method = msg.get("method")
        if method and self._handlers:
            params = msg.get("params", {})
            for h in list(self._handlers):
                try:
                    h(method, params)
                except Exception:
                    pass

    async def close(self):
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
        if self._http_session:
            try:
                await self._http_session.close()
            except Exception:
                pass

    # —— 核心 send ——

    async def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        """发送 CDP 命令，等待响应。"""
        self._nid += 1
        fut = asyncio.Future()
        self._pending[self._nid] = fut

        msg: dict = {"id": self._nid, "method": method, "params": params or {}}
        sid = session_id or self._session
        if sid:
            msg["sessionId"] = sid

        await self.ws.send_json(msg)
        return await fut

    # —— 事件监听 ——

    def on_event(self, handler):
        self._handlers.append(handler)

    def off_event(self, handler):
        if handler in self._handlers:
            self._handlers.remove(handler)

    # —— 页面 target 管理 ——

    @property
    def session(self) -> str | None:
        return self._session

    @property
    def current_target_id(self) -> str | None:
        return self._current_target_id

    @property
    def enabled_domains(self) -> set:
        return set(self._enabled_domains)

    async def enable_domain(self, domain: str, session_id: str | None = None) -> bool:
        """启用 CDP 事件域（幂等去重 — 同一个域只 enable 一次）。

        Returns: True = 这次实际发了 enable；False = 之前已 enable，跳过
        """
        async with self._lock:
            if domain in self._enabled_domains:
                return False
            await self.send(f"{domain}.enable", session_id=session_id)
            self._enabled_domains.add(domain)
            return True

    async def pages(self) -> list:
        """列出所有 page target。"""
        r = await self.send("Target.getTargets")
        return [
            t for t in r.get("result", {}).get("targetInfos", [])
            if t.get("type") == "page"
        ]

    async def attach_page(self, target_id: str) -> dict:
        """attach 到指定 page target，设置 self._session，返回 attach 结果。

        去重优化：
          - 同一个 targetId 不重复发 Target.attachToTarget
          - Runtime.enable / Page.enable 不重复发
          - 用锁串行化，防止并发调用时 session 交错
        """
        async with self._lock:
            # 1. 已 attach 过这个 target → 直接复用 session
            if self._current_target_id == target_id and self._session:
                return {"sessionId": self._session}

            # 2. 已 attach 过但 session 被清了（极端情况），补一次 attach
            if target_id in self._attached_targets:
                r = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
                self._session = r.get("result", {}).get("sessionId")
                self._current_target_id = target_id
                # Runtime/Page enable 已经在之前发过了，跳过
                return r.get("result", {})

            # 3. 首次 attach 这个 target — 完整流程
            if "Runtime" not in self._enabled_domains:
                await self.send("Runtime.enable")
                self._enabled_domains.add("Runtime")
            r = await self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
            self._session = r.get("result", {}).get("sessionId")
            self._current_target_id = target_id
            self._attached_targets.add(target_id)
            # 注意：Runtime.enable 有 browser 级和 session 级两层，flatten attach 后还需要 session 级
            await self.send("Runtime.enable")
            if "Page" not in self._enabled_domains:
                await self.send("Page.enable")
                self._enabled_domains.add("Page")
            return r.get("result", {})

    async def create_target(self, url: str = "about:blank") -> str:
        """创建新的 page target（新 tab），返回 targetId。"""
        r = await self.send("Target.createTarget", {"url": url})
        return r.get("result", {}).get("targetId")

    async def close_target(self, target_id: str) -> bool:
        """关闭指定 target（tab/window）。"""
        r = await self.send("Target.closeTarget", {"targetId": target_id})
        return r.get("result", {}).get("success", False)

    async def ensure_tab(self, url_substr: str | None = None, create_url: str = "about:blank") -> dict:
        """确保目标 page tab 存在 — 有则返回已有 target dict，无则创建新 tab。

        这是核心便捷方法，解决「代理启动时目标 tab 不存在 → 直接退出」的问题。

        Args:
            url_substr: 要找的 URL 子串（None 表示找任意非 chrome:// 页面）
            create_url: 找不到时创建新 tab 用的 URL，默认 about:blank

        Returns:
            target dict（含 targetId, url, title 等）
        """
        pages = await self.pages()
        target = select_target(pages, url_substr)
        if target:
            return target
        # 没找到 → 创建新 tab
        target_id = await self.create_target(create_url)
        # 创建后等一下让 Chrome 完成初始化
        await asyncio.sleep(0.3)
        pages = await self.pages()
        # 找到刚创建的那个（targetId 匹配）
        for p in pages:
            if p.get("targetId") == target_id:
                return p
        # 实在找不到就用 create_url 构造一个最小 dict
        return {"targetId": target_id, "url": create_url, "title": ""}

    # —— 便捷操作方法（需要已 attach 到某个 page）——

    async def eval(self, expr: str, session_id: str | None = None):
        r = await self.send(
            "Runtime.evaluate",
            {"expression": expr, "returnByValue": True, "awaitPromise": True},
            session_id=session_id or self._session,
        )
        rr = r.get("result", {})
        if "exceptionDetails" in rr:
            return {
                "_error": rr["exceptionDetails"].get("text", ""),
                "_desc": rr.get("result", {}).get("description", "")[:500],
            }
        res = rr.get("result", {})
        if "value" in res:
            return res["value"]
        if "description" in res:
            return {"_desc": res["description"][:500]}
        return None

    async def shot(self, path: str, session_id: str | None = None) -> str:
        await self.send("Page.enable", session_id=session_id or self._session)
        r = await self.send(
            "Page.captureScreenshot",
            {"format": "png"},
            session_id=session_id or self._session,
        )
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        return path

    async def navigate(self, url: str, session_id: str | None = None):
        return await self.send(
            "Page.navigate", {"url": url}, session_id=session_id or self._session
        )

    # —— 浏览器操作（CDP Input 域 + DOM 辅助）——

    async def _resolve_selector_center(self, selector: str, session_id: str | None = None) -> tuple[float, float]:
        """selector → getBoundingClientRect → 中心点坐标。找不到抛 ValueError。"""
        sid = session_id or self._session
        js = f"""
        (() => {{
            const el = document.querySelector({json.dumps(selector)});
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, h: r.height}};
        }})()
        """
        r = await self.send(
            "Runtime.evaluate",
            {"expression": js, "returnByValue": True, "awaitPromise": False},
            session_id=sid,
        )
        rr = r.get("result", {}).get("result", {})
        center = rr.get("value") if "value" in rr else None
        if not center:
            raise ValueError(f"selector not found: {selector}")
        return center["x"], center["y"]

    async def _dispatch_mouse(self, x: float, y: float, button: str = "left",
                              types: list[str] | None = None,
                              session_id: str | None = None):
        """派发鼠标事件序列（mouseMoved → mousePressed → mouseReleased 默认 click）。"""
        sid = session_id or self._session
        if types is None:
            types = ["mouseMoved", "mousePressed", "mouseReleased"]
        button_map = {"left": "left", "right": "right", "middle": "middle", "back": "back", "forward": "forward"}
        cd_button = button_map.get(button, "left")
        for t in types:
            params = {
                "type": t,
                "x": x,
                "y": y,
                "button": cd_button,
                "clickCount": 1,
            }
            if t == "mousePressed":
                params["buttons"] = 1 if cd_button == "left" else 2
            elif t == "mouseReleased":
                params["buttons"] = 0
            await self.send("Input.dispatchMouseEvent", params, session_id=sid)
            await asyncio.sleep(0.02)

    async def click(self, selector_or_xy, button: str = "left",
                    session_id: str | None = None) -> bool:
        """点击元素。selector_or_xy 可以是 CSS selector 字符串，或 (x, y) tuple。"""
        sid = session_id or self._session
        if isinstance(selector_or_xy, str):
            x, y = await self._resolve_selector_center(selector_or_xy, sid)
        elif isinstance(selector_or_xy, (tuple, list)) and len(selector_or_xy) == 2:
            x, y = float(selector_or_xy[0]), float(selector_or_xy[1])
        else:
            raise TypeError("click expects selector str or (x,y) tuple")
        await self._dispatch_mouse(x, y, button, session_id=sid)
        return True

    async def hover(self, selector_or_xy, session_id: str | None = None) -> bool:
        """悬停到元素中心（只发 mouseMoved）。"""
        sid = session_id or self._session
        if isinstance(selector_or_xy, str):
            x, y = await self._resolve_selector_center(selector_or_xy, sid)
        elif isinstance(selector_or_xy, (tuple, list)) and len(selector_or_xy) == 2:
            x, y = float(selector_or_xy[0]), float(selector_or_xy[1])
        else:
            raise TypeError("hover expects selector str or (x,y) tuple")
        await self.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseMoved", "x": x, "y": y},
            session_id=sid,
        )
        return True

    async def press_key(self, key: str, modifiers: int = 0,
                        session_id: str | None = None) -> bool:
        """按键（CDP Input.dispatchKeyEvent）。key 是 KeyboardEvent.key 值，如 'Enter'、'a'、'Backspace'。

        modifiers: 0=none, 1=Alt, 2=Ctrl, 4=Meta, 8=Shift（可组合）
        """
        sid = session_id or self._session
        code_map = {
            "Enter": "Enter", "Tab": "Tab", "Escape": "Escape",
            "Backspace": "Backspace", "Delete": "Delete",
            "ArrowUp": "ArrowUp", "ArrowDown": "ArrowDown", "ArrowLeft": "ArrowLeft", "ArrowRight": "ArrowRight",
            "Home": "Home", "End": "End", "PageUp": "PageUp", "PageDown": "PageDown",
            "Insert": "Insert", "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
            "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8", "F9": "F9",
            "F10": "F10", "F11": "F11", "F12": "F12",
        }
        code = code_map.get(key, f"Key{key.upper()}" if len(key) == 1 else key)
        key_code = _KEY_CODE_MAP.get(key, 0)
        await self.send(
            "Input.dispatchKeyEvent",
            {"type": "keyDown", "key": key, "code": code, "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code, "modifiers": modifiers},
            session_id=sid,
        )
        await self.send(
            "Input.dispatchKeyEvent",
            {"type": "keyUp", "key": key, "code": code, "windowsVirtualKeyCode": key_code, "nativeVirtualKeyCode": key_code, "modifiers": modifiers},
            session_id=sid,
        )
        return True

    async def type_text(self, text: str, selector: str | None = None,
                        session_id: str | None = None) -> bool:
        """输入文本。可选先聚焦 selector 元素（click 一下），然后逐字符派发 key events。"""
        sid = session_id or self._session
        if selector:
            await self.click(selector, session_id=sid)
            await asyncio.sleep(0.05)
        for ch in text:
            if ch == "\n":
                await self.press_key("Enter", session_id=sid)
            elif ch == "\t":
                await self.press_key("Tab", session_id=sid)
            else:
                code = f"Key{ch.upper()}" if ch.isalpha() else f"Digit{ch}" if ch.isdigit() else ch
                await self.send(
                    "Input.dispatchKeyEvent",
                    {"type": "char", "text": ch, "key": ch, "code": code},
                    session_id=sid,
                )
            await asyncio.sleep(0.01)
        return True

    async def handle_dialog(self, accept: bool = True, prompt_text: str | None = None,
                            session_id: str | None = None) -> bool:
        """处理 JS 对话框（alert/confirm/prompt/beforeunload）。accept=False = 点取消。"""
        sid = session_id or self._session
        params = {"accept": accept}
        if prompt_text is not None:
            params["promptText"] = prompt_text
        r = await self.send("Page.handleJavaScriptDialog", params, session_id=sid)
        return r.get("result", {}).get("success", False)

    # —— 完整启动便捷方法 ——

    async def connect_and_ensure(self, url_substr: str | None = None, create_url: str = "about:blank"):
        """探测 → 连接 → 启动 → ensure_tab → attach，一步到位。

        解决「没 tab 就退出」的问题：找不到匹配 tab 时自动创建。
        """
        ws_url, mode, _tabs = await detect_ws_url()
        if not ws_url:
            raise RuntimeError("Chrome 未开远程调试")
        await self.connect(ws_url)
        await self.start()
        target = await self.ensure_tab(url_substr, create_url)
        await self.attach_page(target["targetId"])
        return target

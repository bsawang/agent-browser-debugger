#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 接管观察工具：list / eval / multi / shot。

用法（需 aiohttp；系统 python 缺则用 ComfyUI 运行副本 python）：
  python cdp.py list
  python cdp.py eval '<js>'
  python cdp.py multi '<js1>' '<js2>' ...   ← 一次连接执行多条（只弹一次授权）
  python cdp.py shot <file.png>

连接方式（两种自动回退）：
  1. chrome://inspect 手动开启（Chrome 144+，默认 profile 保留登录）：
     读 User Data\\DevToolsActivePort 文件 → ws://127.0.0.1:<port><ws_path>
     —— 此模式每次新连接 Chrome 弹授权提示（无永久信任），请用 multi/长连接减少次数
  2. 传统 --remote-debugging-port（需 --user-data-dir 非默认目录）：无授权弹窗

本工具所有命令在**单个 ws 连接**内完成（list/eval/multi/shot），避免重复授权弹窗。
"""
import asyncio
import base64
import json
import os
import sys

import aiohttp

PORT = 9222


def default_user_data_dir():
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Google", "Chrome", "User Data")


async def get_browser_ws_url():
    """优先读 DevToolsActivePort（chrome://inspect 模式）；回退传统 HTTP。"""
    active_port = os.path.join(default_user_data_dir(), "DevToolsActivePort")
    if os.path.isfile(active_port):
        with open(active_port, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) >= 2:
            return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}", "inspect"
    async with aiohttp.ClientSession() as s:
        async with s.get(f"http://127.0.0.1:{PORT}/json/version", timeout=aiohttp.ClientTimeout(total=3)) as r:
            return (await r.json())["webSocketDebuggerUrl"], "traditional"


class CDP:
    def __init__(self, url):
        self.url = url
        self.ws = None
        self.nid = 0
        self.session = None

    async def connect(self):
        self.ws = await aiohttp.ClientSession().ws_connect(self.url)

    async def call(self, method, params=None, session_id=None):
        self.nid += 1
        msg = {"id": self.nid, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        await self.ws.send_json(msg)
        while True:
            r = await self.ws.receive_json()
            if r.get("id") == self.nid:
                return r

    async def pages(self):
        r = await self.call("Target.getTargets")
        return [t for t in r.get("result", {}).get("targetInfos", []) if t.get("type") == "page"]

    async def attach_page(self, target_id):
        r = await self.call("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        self.session = r.get("result", {}).get("sessionId")
        await self.call("Runtime.enable", session_id=self.session)

    async def eval(self, expr, session_id=None):
        r = await self.call("Runtime.evaluate",
                            {"expression": expr, "returnByValue": True, "awaitPromise": True},
                            session_id=session_id or self.session)
        rr = r.get("result", {})
        if "exceptionDetails" in rr:
            return {"_error": rr["exceptionDetails"].get("text", ""),
                    "_desc": rr.get("result", {}).get("description", "")[:500]}
        res = rr.get("result", {})
        if "value" in res:
            return res["value"]
        if "description" in res:
            return {"_desc": res["description"][:500]}
        return None

    async def shot(self, path, session_id=None):
        await self.call("Page.enable", session_id=session_id or self.session)
        r = await self.call("Page.captureScreenshot", {"format": "png"},
                            session_id=session_id or self.session)
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        return path

    async def close(self):
        if self.ws:
            await self.ws.close()


def fmt(v):
    return json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    ws_url, _mode = await get_browser_ws_url()
    c = CDP(ws_url)
    await c.connect()
    await c.call("Runtime.enable")

    if cmd == "list":
        pages = await c.pages()
        if not pages:
            print("无页面 tab（检查 chrome://inspect 是否已勾选允许远程调试）")
        for p in pages:
            print(f"[page] {p.get('id')} {p.get('url', '')}")

    elif cmd in ("eval", "multi", "shot"):
        pages = await c.pages()
        if not pages:
            print("无页面 tab")
            await c.close(); return
        target = next((p for p in pages if "8188" in p.get("url", "")), pages[0])
        await c.attach_page(target["targetId"])

        if cmd == "eval":
            print(fmt(await c.eval(sys.argv[2])))
        elif cmd == "multi":
            for expr in sys.argv[2:]:
                print("###", expr[:60])
                print(fmt(await c.eval(expr)))
        else:
            print("saved:", await c.shot(sys.argv[2]))

    else:
        print("usage: cdp.py list | eval '<js>' | multi '<js>'... | shot <file.png>")

    await c.close()


if __name__ == "__main__":
    asyncio.run(main())

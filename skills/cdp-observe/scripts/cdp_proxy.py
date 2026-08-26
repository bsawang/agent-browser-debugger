#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常驻 CDP 代理：保持单个 CDP 连接，通过本地 HTTP 端口接收命令。

避免 chrome://inspect 模式「每次连接弹授权」的问题——启动时连一次（弹一次 Allow），
之后所有观察命令走本代理，不再重新连接、不再弹窗。

启动（后台）：python cdp_proxy.py [端口]   # 默认 9333，仅监听 127.0.0.1
调用：
  curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
  curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
  curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
"""
import asyncio
import base64
import json
import os
import sys

import aiohttp
from aiohttp import web

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9333


def default_user_data_dir():
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "Google", "Chrome", "User Data")


async def get_browser_ws_url():
    ap = os.path.join(default_user_data_dir(), "DevToolsActivePort")
    if os.path.isfile(ap):
        with open(ap, encoding="utf-8") as f:
            lines = f.read().splitlines()
        if len(lines) >= 2:
            return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}", "inspect"
    async with aiohttp.ClientSession() as s:
        async with s.get("http://127.0.0.1:9222/json/version", timeout=aiohttp.ClientTimeout(total=3)) as r:
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


async def main():
    url, mode = await get_browser_ws_url()
    c = CDP(url)
    await c.connect()  # 唯一一次授权弹窗
    await c.call("Runtime.enable")
    pages = await c.pages()
    if not pages:
        print("no page tab")
        return
    target = next((p for p in pages if "8188" in p.get("url", "")), pages[0])
    await c.attach_page(target["targetId"])
    print(f"[proxy] connected ({mode}) to {target.get('url', '')} | listen :{PORT}")

    async def handle(req):
        try:
            data = await req.json()
        except Exception:
            return web.json_response({"err": "bad json"})
        try:
            if "eval" in data:
                return web.json_response({"result": await c.eval(data["eval"])})
            if "shot" in data:
                return web.json_response({"saved": await c.shot(data["shot"])})
            if "pages" in data:
                return web.json_response({"pages": await c.pages()})
            return web.json_response({"err": "unknown cmd"})
        except Exception as e:
            return web.json_response({"err": str(e)})

    app = web.Application()
    app.router.add_post("/", handle)
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", PORT)
    await site.start()
    print(f"[proxy] ready: curl -s http://127.0.0.1:{PORT}/ -d '{{\"eval\":\"<js>\"}}'")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

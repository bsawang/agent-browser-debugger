#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""常驻 CDP 代理：保持单个 CDP 连接，通过本地 HTTP 端口接收命令。

设计原则：调试目标最大可能提供实时能力，通用性优先。

启动（后台）：python cdp_proxy.py [端口] [目标URL子串]
  默认 9333；目标 URL 子串可省（代理会自动找第一个非 chrome:// 页面，没有则创建 about:blank）
  目标创建 URL 可通过 CDP_CREATE_URL 环境变量覆盖（默认 about:blank）

所有命令（POST JSON 到 http://127.0.0.1:<port>/）：
  —— 观察类 ——
  {"eval":"<js>"}              执行 JS
  {"shot":"<png路径>"}          截图
  {"pages":1}                  列 page tab
  {"detect":1}                 只读探测 Chrome 调试状态（不弹授权）
  {"enable":"<Domain>"}        启用 CDP 事件域（如 Network、DOM、Page）
  {"events":"<Domain>"}        读取事件缓冲（支持 domain 过滤）
  {"clear_events":1}           清空事件缓冲
  —— 页面管理 ——
  {"navigate":"<url>"}         导航
  {"target":"<url子串>"}       切换目标页（热切换，不用重连）
  {"open":"<url>"}             新建 tab 打开 URL 并 attach
  {"ensure":"<url子串>"}       有匹配 tab 则切换，无则创建并 attach
  —— 操作类 ——
  {"click":"<selector>"}       点击 CSS selector 元素
  {"click":{"selector":"...","button":"right"}}  指定按钮点击
  {"click":{"x":100,"y":200}}   坐标点击
  {"hover":"<selector>"}       悬停到元素
  {"type":{"selector":"...","text":"hello"}}   聚焦元素并输入
  {"type":"hello world"}       在当前焦点位置输入（纯文本模式）
  {"press_key":"Enter"}        按键（Enter/Tab/Escape/Backspace/箭头字母数字）
  {"handle_dialog":true}      确认 JS 对话框（false = 取消）
  {"handle_dialog":{"accept":true,"promptText":"..."}}  处理 prompt 对话框
"""
import asyncio
import os
import sys
from collections import deque

import aiohttp
from aiohttp import web

from cdp_core import CDP, detect_ws_url, select_target, chrome_running

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9333
TARGET_SUBSTR = sys.argv[2] if len(sys.argv) > 2 else None
CREATE_URL = os.environ.get("CDP_CREATE_URL", "about:blank")


# —— 友好提示模板 ——

HELP_INSPECT = """
  Chrome 运行中但未开启远程调试，两步搞定：
    1. 地址栏输入 chrome://inspect 回车
    2. 勾选右下角 "Allow remote debugging"
  （勾选后代理会自动连上；首次连接 Chrome 会弹授权框，点允许即可）"""

HELP_NO_CHROME = """
  没检测到 Chrome 进程，请先启动 Chrome。
  启动后如果还没开调试：chrome://inspect → 勾选 Allow remote debugging"""


# —— 事件缓冲（最近 200 条 CDP 事件，轮询式读取）——
_event_buffer: deque = deque(maxlen=200)


def _on_any_event(method: str, params: dict):
    _event_buffer.append({"method": method, "params": params})


async def main():
    ws_url, mode, _ = await detect_ws_url()

    if not ws_url:
        if chrome_running():
            print(f"[proxy] Chrome 运行中但未开远程调试\n{HELP_INSPECT}")
        else:
            print(f"[proxy] 未检测到 Chrome\n{HELP_NO_CHROME}")
        return

    print(f"[proxy] 检测到 Chrome ({mode}) → {ws_url}")

    c = CDP()
    await c.connect(ws_url)
    await c.start()
    c.on_event(_on_any_event)

    # —— ensure_tab：目标不存在时自动创建 ——
    target = await c.ensure_tab(TARGET_SUBSTR, CREATE_URL)
    await c.attach_page(target["targetId"])

    url_label = target.get("url", "")
    was_created = url_label == CREATE_URL
    if was_created:
        print(f"[proxy] 未找到匹配 tab → 已创建新 tab: {url_label}")
    else:
        print(f"[proxy] 目标 tab: {url_label}")
    print(f"[proxy] 就绪：curl -s http://127.0.0.1:{PORT}/ -d '{{\"eval\":\"<js>\"}}'")

    # —— HTTP handler ——

    async def handle(req):
        try:
            data = await req.json()
        except Exception:
            return web.json_response({"err": "bad json"})

        try:
            # detect：只读探测，不走 CDP 连接
            if "detect" in data:
                ws_url2, mode2, tabs2 = await detect_ws_url()
                return web.json_response({
                    "found": bool(ws_url2),
                    "mode": mode2,
                    "ws": ws_url2,
                    "tabs": tabs2,
                })

            # pages
            if "pages" in data:
                return web.json_response({"pages": await c.pages()})

            # eval
            if "eval" in data:
                return web.json_response({"result": await c.eval(data["eval"])})

            # shot
            if "shot" in data:
                return web.json_response({"saved": await c.shot(data["shot"])})

            # navigate
            if "navigate" in data:
                await c.navigate(data["navigate"])
                return web.json_response({"navigated": data["navigate"]})

            # target 切换
            if "target" in data:
                pages = await c.pages()
                tgt = select_target(pages, data["target"] or None)
                if not tgt:
                    return web.json_response({"err": "no matching target"})
                await c.attach_page(tgt["targetId"])
                return web.json_response({"target": tgt})

            # open：新建 tab 打开 URL 并 attach
            if "open" in data:
                target_id = await c.create_target(data["open"])
                await asyncio.sleep(0.3)
                await c.attach_page(target_id)
                return web.json_response({"opened": data["open"], "targetId": target_id})

            # ensure：有匹配 tab 则 attach，无则创建并 attach
            if "ensure" in data:
                tgt = await c.ensure_tab(data["ensure"], CREATE_URL)
                await c.attach_page(tgt["targetId"])
                return web.json_response({"target": tgt, "wasCreated": tgt.get("url") == CREATE_URL})

            # 启用 CDP 事件域（幂等去重）
            if "enable" in data:
                domain = data["enable"]
                actually_enabled = await c.enable_domain(domain)
                return web.json_response({"enabled": domain, "wasNew": actually_enabled})

            # 读取事件缓冲
            if "events" in data:
                domain_filter = data["events"] if isinstance(data["events"], str) else None
                items = list(_event_buffer)
                if domain_filter:
                    items = [e for e in items if e["method"].startswith(domain_filter + ".")]
                return web.json_response({"events": items})

            # 清空事件缓冲
            if "clear_events" in data:
                _event_buffer.clear()
                return web.json_response({"cleared": True})

            # —— 操作类 ——

            # click：支持三种形式
            #   "click": "<selector>"
            #   "click": {"selector": "...", "button": "left"}
            #   "click": {"x": 100, "y": 200}
            if "click" in data:
                spec = data["click"]
                if isinstance(spec, str):
                    await c.click(spec)
                elif isinstance(spec, dict):
                    if "selector" in spec:
                        await c.click(spec["selector"], button=spec.get("button", "left"))
                    elif "x" in spec and "y" in spec:
                        await c.click((float(spec["x"]), float(spec["y"])), button=spec.get("button", "left"))
                    else:
                        return web.json_response({"err": "click needs selector or x/y"})
                else:
                    return web.json_response({"err": "click bad format"})
                return web.json_response({"clicked": True})

            # hover
            if "hover" in data:
                spec = data["hover"]
                if isinstance(spec, str):
                    await c.hover(spec)
                elif isinstance(spec, dict) and "selector" in spec:
                    await c.hover(spec["selector"])
                elif isinstance(spec, dict) and "x" in spec and "y" in spec:
                    await c.hover((float(spec["x"]), float(spec["y"])))
                else:
                    return web.json_response({"err": "hover needs selector or x/y"})
                return web.json_response({"hovered": True})

            # type：支持两种形式
            #   "type": {"selector": "...", "text": "hello"}
            #   "type": "hello world"（在当前焦点输入）
            if "type" in data:
                spec = data["type"]
                if isinstance(spec, str):
                    await c.type_text(spec)
                elif isinstance(spec, dict) and "text" in spec:
                    await c.type_text(spec["text"], selector=spec.get("selector"))
                else:
                    return web.json_response({"err": "type needs text"})
                return web.json_response({"typed": True})

            # press_key
            if "press_key" in data:
                spec = data["press_key"]
                if isinstance(spec, str):
                    await c.press_key(spec)
                elif isinstance(spec, dict) and "key" in spec:
                    await c.press_key(spec["key"], modifiers=spec.get("modifiers", 0))
                else:
                    return web.json_response({"err": "press_key needs key string"})
                return web.json_response({"pressed": True})

            # handle_dialog：true/false/{"accept":...,"promptText":...}
            if "handle_dialog" in data:
                spec = data["handle_dialog"]
                if isinstance(spec, bool):
                    ok = await c.handle_dialog(accept=spec)
                elif isinstance(spec, dict):
                    ok = await c.handle_dialog(
                        accept=spec.get("accept", True),
                        prompt_text=spec.get("promptText"),
                    )
                else:
                    return web.json_response({"err": "handle_dialog bad format"})
                return web.json_response({"dialogHandled": ok})

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
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())

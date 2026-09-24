#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP 单次命令行工具：detect / ensure / open / list / eval / multi / shot / navigate。

用法（需 aiohttp）：
  python cdp.py detect             # 只读探测 Chrome 调试状态（不弹授权）
  python cdp.py ensure             # 代理探活 + 自动起（跨平台，推荐）
  python cdp.py open '<url>'       # 新建 tab 打开 URL
  python cdp.py list               # 列出 page tab
  python cdp.py eval '<js>'        # 执行 JS
  python cdp.py multi '<js1>' '<js2>' ...   # 一次连接执行多条
  python cdp.py shot <file.png>    # 截图
  python cdp.py navigate '<url>'   # 导航

连接方式自动回退：
  1. chrome://inspect（读 DevToolsActivePort 文件）
  2. 传统 --remote-debugging-port（HTTP /json/version）

核心改进：ensure_tab 保证目标 tab 存在（有则复用，无则创建），
不再出现「目标 tab 不存在 → 命令直接退出」的情况。
"""
import asyncio
import json
import os
import subprocess
import sys

from cdp_core import CDP, detect_ws_url, select_target, chrome_running

CREATE_URL = os.environ.get("CDP_CREATE_URL", "about:blank")


def fmt(v):
    return json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v


def print_help():
    """检测失败时的友好提示。"""
    if chrome_running():
        print("""Chrome 运行中但未开远程调试，两步搞定：
  1. 地址栏输入 chrome://inspect 回车
  2. 勾选右下角 "Allow remote debugging"
（勾选后重试即可）""")
    else:
        print("""未检测到 Chrome 进程，请先启动 Chrome。
启动后 chrome://inspect → 勾选 Allow remote debugging""")


async def _async_main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    # detect：只读探测，不连 ws，不弹授权
    if cmd == "detect":
        ws_url, mode, tabs = await detect_ws_url()
        if not ws_url:
            print_help()
            return
        print(f"mode: {mode}")
        print(f"ws:   {ws_url}")
        if tabs:
            for t in tabs:
                print(f"  [{t.get('id','')}] {t.get('url','')}")
            print(f"({len(tabs)} page tabs)")
        else:
            print("(inspect 模式：HTTP 不可用，需 attach 才能列 tab)")
        return

    # ensure：代理探活 + 自动起（跨平台）
    if cmd == "ensure":
        port = int(sys.argv[2]) if len(sys.argv) > 2 else 9333
        import urllib.request
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/",
                                         data=json.dumps({"pages": 1}).encode(),
                                         headers={"Content-Type": "application/json"},
                                         method="POST")
            resp = urllib.request.urlopen(req, timeout=2)
            print(f"proxy on :{port} ok")
            return
        except Exception:
            pass

        # 代理没跑 → subprocess 起代理
        proxy_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdp_proxy.py")
        log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cdp_proxy.log")
        with open(log_path, "w") as log:
            if os.name == "nt":
                # Windows: CREATE_NO_WINDOW + 重定向
                CREATE_NO_WINDOW = 0x08000000
                subprocess.Popen(
                    [sys.executable, proxy_script, str(port)],
                    stdout=log, stderr=log,
                    creationflags=CREATE_NO_WINDOW,
                    close_fds=True,
                )
            else:
                # Unix: 后台 + 重定向
                subprocess.Popen(
                    [sys.executable, proxy_script, str(port)],
                    stdout=log, stderr=log,
                    start_new_session=True,
                )
        import time
        time.sleep(2)
        print(f"proxy started on :{port} (log: {log_path})")
        return

    # 其他命令：需连接（弹一次授权）
    ws_url, mode, _ = await detect_ws_url()
    if not ws_url:
        print_help()
        return

    c = CDP()
    await c.connect(ws_url)
    await c.start()

    try:
        if cmd == "open":
            # open：新建 tab → 直接返回新 tab 信息
            target_id = await c.create_target(sys.argv[2])
            await asyncio.sleep(0.3)
            pages = await c.pages()
            for p in pages:
                if p.get("targetId") == target_id:
                    print(fmt(p))
                    return
            print(fmt({"targetId": target_id, "url": sys.argv[2]}))

        elif cmd == "list":
            # list：ensure_tab 保证至少有一个 tab，然后列全部
            await c.ensure_tab(None, CREATE_URL)
            pages = await c.pages()
            if not pages:
                print("无页面 tab（Chrome 应至少有一个，检查是否被关闭）")
            for p in pages:
                print(f"[page] {p.get('targetId')} {p.get('url', '')}")

        elif cmd in ("eval", "multi", "shot", "navigate"):
            # 先 ensure 目标 tab 存在（根据 CDP_TARGET 环境变量或默认找第一个）
            target = await c.ensure_tab(None, CREATE_URL)
            await c.attach_page(target["targetId"])

            if cmd == "eval":
                print(fmt(await c.eval(sys.argv[2])))
            elif cmd == "multi":
                for expr in sys.argv[2:]:
                    print("###", expr[:60])
                    print(fmt(await c.eval(expr)))
            elif cmd == "shot":
                print("saved:", await c.shot(sys.argv[2]))
            elif cmd == "navigate":
                print("navigated:", sys.argv[2])
                await c.navigate(sys.argv[2])

        else:
            print("usage: cdp.py detect | open '<url>' | list | eval '<js>' | multi '<js>'... | shot <file.png> | navigate '<url>'")
    finally:
        await c.close()


def main():
    """同步入口 — 供 pyproject.toml [project.scripts] cdp=cdp:main 使用。"""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()

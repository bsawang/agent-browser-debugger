#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CDP MCP Server — 把 cdp_core 的 16 个调试命令暴露成 MCP tools。

配置到 MCP 客户端（TRAE / Claude Code / Cursor / Copilot）：
{
  "mcpServers": {
    "cdp-debug": {
      "command": "python",
      "args": ["<path>/cdp_mcp.py"]
    }
  }
}

启动时自动 detect → connect Chrome CDP → ensure_tab → attach。
之后每个 MCP tool call 都在同一个 Python 进程内执行，零 Shell 开销。
"""
import asyncio
import json
import sys
import os
import time

from mcp.server.fastmcp import FastMCP

# 让 cdp_core 可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_core import CDP, CDPError, CDPTimeoutError, CDPDisconnectedError, detect_ws_url, select_target, chrome_running

mcp = FastMCP("cdp-debug")

# —— 全局状态：CDP 实例 + 事件缓冲（和 cdp_proxy 里的设计一样）——
_cdp: CDP | None = None
_event_buffer: list[dict] = []  # 用 list 当 deque 用（简洁）
_event_maxlen = 200
_lock = asyncio.Lock()

# —— 跨重连保活的会话记忆 ——
# Chrome 重启 / WS 断开后重建连接时，按这里恢复：重新 attach 同一 tab、重新 enable 同样的域
_enabled_domains: set[str] = set()   # 用户启用过的 CDP 域（跨重连不丢）
_last_target: str | None = None      # 最近一次操作的目标 URL 子串
_last_ok: float = 0.0                # 最近一次 ping 成功时间（5s 内不重复 ping）
_last_error: str | None = None       # 最近一次连接错误（人类可读，给 connection_status / 排障用）
_PING_TTL = 5.0
_RECONNECT_ATTEMPTS = 2


def _record_error(msg: str):
    global _last_error
    _last_error = msg


async def _new_connection() -> CDP:
    """探测 → 连接 → attach → 恢复域。失败抛带明确指引的 RuntimeError。"""
    global _last_error
    ws_url, mode, _ = await detect_ws_url()
    if not ws_url:
        if chrome_running():
            msg = ("Chrome 运行中但未开远程调试：地址栏打开 chrome://inspect → "
                   "勾选「Allow remote debugging for this browser instance」（首次连接弹授权框点允许）")
        else:
            msg = "未检测到 Chrome 进程：请先启动 Chrome，再 chrome://inspect 勾选 Allow remote debugging"
        _record_error(msg)
        raise RuntimeError(msg)

    c = CDP()
    c.on_disconnect(lambda: _record_error("CDP WebSocket 异常断开（Chrome 退出或调试被关闭），下次调用将自动重连"))
    await c.connect(ws_url)          # 10s 握手 deadline
    await c.start()
    c.on_event(_on_event)
    target = await c.ensure_tab(_last_target or os.environ.get("CDP_TARGET"))
    await c.attach_page(target["targetId"])
    # 恢复上次的事件域（重建后 Chrome 侧 enable 状态全丢）
    restored = []
    for d in sorted(_enabled_domains):
        try:
            await c.enable_domain(d)
            restored.append(d)
        except Exception:
            pass
    return c


async def _ensure_cdp() -> CDP:
    """懒加载 + 健康探测 + 自动重连。

    - 已有连接：5s 内 ping 过直接复用；否则发 3s 轻量探测（识别半开连接，不再被 ws.closed 骗过）
    - 连接死亡：丢弃旧实例，最多重建 2 次（0.5s 退避），重建后自动恢复 attach 的 tab 和已启用域
    """
    global _cdp, _last_ok, _last_error
    async with _lock:
        if _cdp is not None and _cdp.alive and time.monotonic() - _last_ok < _PING_TTL:
            return _cdp

        if _cdp is not None:
            # 有旧连接 → ping 验证（alive=False 直接跳过 ping）
            if _cdp.alive:
                try:
                    await _cdp.ping()
                    _last_ok = time.monotonic()
                    _last_error = None
                    return _cdp
                except CDPError as e:
                    _record_error(f"健康探测失败，开始重连：{e}")
            try:
                await _cdp.close()
            except Exception:
                pass
            _cdp = None

        last_exc: Exception | None = None
        for attempt in range(1, _RECONNECT_ATTEMPTS + 1):
            try:
                _cdp = await _new_connection()
                _last_ok = time.monotonic()
                _last_error = None
                return _cdp
            except CDPError as e:
                # Chrome 在但连不上（握手超时等），短暂退避再试
                last_exc = e
                if attempt < _RECONNECT_ATTEMPTS:
                    await asyncio.sleep(0.5)
            # RuntimeError（Chrome 没开/没运行）不重试，直接抛明确指引
        if last_exc:
            _record_error(f"重连 {_RECONNECT_ATTEMPTS} 次均失败：{last_exc}")
            raise RuntimeError(f"CDP 重连失败（{_RECONNECT_ATTEMPTS} 次）：{last_exc}")
        raise RuntimeError(_last_error or "CDP 连接失败")


async def _run(fn):
    """执行一个 CDP 操作；连接中途死亡时自动重建并重试一次（只一次，防死循环）。

    工具函数统一走这里 → 用户感知是「卡一下然后自愈」，而不是拿到错误不知所措。
    """
    try:
        c = await _ensure_cdp()
        return await fn(c)
    except (CDPTimeoutError, CDPDisconnectedError):
        # 标记旧实例不可信，下一次 _ensure_cdp 走重建
        global _cdp
        async with _lock:
            old = _cdp
            _cdp = None
        if old:
            try:
                await old.close()
            except Exception:
                pass
        c = await _ensure_cdp()
        return await fn(c)


def _on_event(method: str, params: dict):
    if len(_event_buffer) >= _event_maxlen:
        _event_buffer.pop(0)
    _event_buffer.append({"method": method, "params": params})


# —— 观察类 ——

@mcp.tool()
async def detect_chrome() -> dict:
    """只读探测 Chrome 调试状态（不连 CDP、不弹授权）。

    Returns: {"found": bool, "mode": "inspect"|"traditional"|None, "ws": str|None, "chrome_running": bool}
    """
    ws_url, mode, tabs = await detect_ws_url()
    return {
        "found": bool(ws_url),
        "mode": mode,
        "ws": ws_url,
        "chrome_running": chrome_running(),
    }


@mcp.tool()
async def list_pages() -> list:
    """列出 Chrome 所有 page tab。"""
    return await _run(lambda c: c.pages())


@mcp.tool()
async def eval(expr: str) -> dict:
    """在当前 tab 执行 JavaScript 表达式。

    Args: expr — JS 表达式或语句，如 "document.title" 或 "({url: location.href})"
    Returns: {"result": <JS返回值>} 或 {"err": "<异常文本>"}
    """
    return {"result": await _run(lambda c: c.eval(expr))}


@mcp.tool()
async def take_screenshot(
    path: str,
    max_width: int = 1280,
    quality: int = 62,
    fmt: str = "jpeg",
) -> str:
    """截图并保存。默认 1280 宽 JPEG q62（~30-60KB，供模型识图秒回），
    内置 6s 超时 + fromSurface/置前后重试，永不无限挂起。

    Args:
      path — 保存路径，建议 .jpg，如 "H:/temp/shot.jpg"
      max_width — 等比缩限宽度（默认1280；传0保持原始分辨率）
      quality — JPEG 质量 1-100（默认62）
      fmt — "jpeg"(默认) / "png"(无损，体积大、识图慢，仅像素级排查时用)
    """
    return await _run(lambda c: c.shot(path, fmt=fmt, quality=quality, max_width=max_width or None))


# —— 页面管理 ——

@mcp.tool()
async def navigate(url: str) -> str:
    """导航到 URL。

    Args: url — 完整 URL，如 "https://www.baidu.com"
    """
    await _run(lambda c: c.navigate(url))
    return url


@mcp.tool()
async def ensure_tab(url_substr: str | None = None, create_url: str = "about:blank") -> dict:
    """确保目标 tab 存在 — 有匹配 tab 则切换并 attach，无则创建新 tab。
    目标子串会被记住，连接断开重连后自动回到同一 tab。

    Args:
        url_substr: 要找的 URL 子串，None 表示找任意非 chrome:// 页面
        create_url: 找不到时创建新 tab 的 URL
    Returns: target dict（含 targetId, url, title）
    """
    global _last_target
    _last_target = url_substr

    async def _do(c):
        target = await c.ensure_tab(url_substr, create_url)
        await c.attach_page(target["targetId"])
        return target

    return await _run(_do)


@mcp.tool()
async def open_tab(url: str) -> str:
    """新建 tab 打开 URL 并 attach。

    Args: url — 新 tab 打开的 URL
    Returns: 新 tab 的 targetId
    """
    global _last_target
    _last_target = url

    async def _do(c):
        target_id = await c.create_target(url)
        await asyncio.sleep(0.3)
        await c.attach_page(target_id)
        return target_id

    return await _run(_do)


@mcp.tool()
async def close_tab(target_id: str) -> bool:
    """关闭指定 tab。

    Args: target_id — 目标页 ID（从 list_pages / ensure_tab 返回）
    """
    return await _run(lambda c: c.close_target(target_id))


# —— 操作类 ——

@mcp.tool()
async def click(selector: str | None = None, x: float | None = None,
                y: float | None = None, button: str = "left") -> bool:
    """点击元素或坐标。两种模式二选一：
    - selector: CSS selector 字符串，如 "button.submit"（自动取元素中心）
    - x + y: 坐标点击

    Args:
        selector: CSS selector（优先使用）
        x: 横坐标（selector 为空时使用）
        y: 纵坐标（selector 为空时使用）
        button: "left" / "right" / "middle"
    """
    async def _do(c):
        if selector:
            return await c.click(selector, button=button)
        elif x is not None and y is not None:
            return await c.click((float(x), float(y)), button=button)
        raise ValueError("需要 selector 或 x/y")

    return await _run(_do)


@mcp.tool()
async def hover(selector: str | None = None, x: float | None = None, y: float | None = None) -> bool:
    """悬停到元素中心。

    Args: selector — CSS selector，或提供 x/y 坐标
    """
    async def _do(c):
        if selector:
            return await c.hover(selector)
        elif x is not None and y is not None:
            return await c.hover((float(x), float(y)))
        raise ValueError("需要 selector 或 x/y")

    return await _run(_do)


@mcp.tool()
async def type_text(text: str, selector: str | None = None) -> bool:
    """输入文本。可选先聚焦 selector 元素（会自动 click 一下）。

    Args:
        text: 要输入的文本
        selector: 可选，输入前先 click 聚焦哪个元素
    """
    return await _run(lambda c: c.type_text(text, selector=selector))


@mcp.tool()
async def press_key(key: str, modifiers: int = 0) -> bool:
    """按键。

    Args:
        key: KeyboardEvent.key 值，如 "Enter" / "Tab" / "Escape" / "Backspace" / "ArrowDown" / "a" / "5"
        modifiers: 修饰键位组合（0=none, 1=Alt, 2=Ctrl, 4=Meta, 8=Shift，可相加）
    """
    return await _run(lambda c: c.press_key(key, modifiers=modifiers))


@mcp.tool()
async def handle_dialog(accept: bool = True, prompt_text: str | None = None) -> bool:
    """处理 JS 对话框（alert / confirm / prompt / beforeunload）。

    Args:
        accept: True=确定，False=取消
        prompt_text: 处理 prompt 对话框时填写的文本
    """
    return await _run(lambda c: c.handle_dialog(accept=accept, prompt_text=prompt_text))


# —— 事件类 ——

@mcp.tool()
async def enable_domain(domain: str) -> bool:
    """启用 CDP 事件域（幂等，重复调用跳过）。启用后事件会自动缓冲。
    启用状态跨重连记忆：连接断开重建后自动重新 enable。

    Args: domain — CDP 域名，如 "Network" / "DOM" / "Page" / "Runtime" / "Log"
    Returns: True=这次实际 enable 了；False=之前已 enable
    """
    _enabled_domains.add(domain)
    return await _run(lambda c: c.enable_domain(domain))


@mcp.tool()
def get_events(domain: str | None = None) -> list:
    """读取事件缓冲（最近 200 条 CDP 事件）。

    Args: domain — 可选过滤，只返回 "Domain.*" 事件；None=全部
    """
    if domain:
        return [e for e in _event_buffer if e["method"].startswith(domain + ".")]
    return list(_event_buffer)


@mcp.tool()
def clear_events() -> bool:
    """清空事件缓冲。"""
    _event_buffer.clear()
    return True


# —— 连接状态 ——

@mcp.tool()
async def connection_status() -> dict:
    """查询 CDP 连接状态（排查「卡住/连不上」第一步，零副作用、不触发重连）。

    Returns:
      alive: 当前连接是否可用
      target: 当前 attach 的 tab（targetId/sessionId）
      remembered_target: 重连时要回到的 URL 子串
      enabled_domains: 已启用并会在重连后恢复的事件域
      buffered_events: 事件缓冲条数
      last_ok_age_s: 距上次成功 ping 的秒数
      last_error: 最近一次连接错误/指引（None=无）
      chrome_running: Chrome 进程是否在跑
    """
    age = round(time.monotonic() - _last_ok, 1) if _last_ok else None
    return {
        "alive": bool(_cdp is not None and _cdp.alive),
        "target": _cdp.current_target if _cdp else None,
        "remembered_target": _last_target or os.environ.get("CDP_TARGET"),
        "enabled_domains": sorted(_enabled_domains),
        "buffered_events": len(_event_buffer),
        "last_ok_age_s": age,
        "last_error": _last_error,
        "chrome_running": chrome_running(),
    }


# —— 通用 CDP 透传 ——

@mcp.tool()
async def send_cdp(method: str, params: dict | None = None, browser_level: bool = False):
    """发送任意原生 CDP（Chrome DevTools Protocol）命令——全协议通用口子。

    当精选工具（eval/click/get_events 等）覆盖不到某个 CDP 域方法时用它，
    例如：Debugger.getScriptSource（取脚本原文）、DOM.*、Network.*、Runtime.*、Input.* 等。
    协议方法与参数查官方索引：https://chromedevtools.github.io/devtools-protocol/

    Args:
      method: 完整 CDP 方法名，如 "Debugger.getScriptSource"
      params: 方法参数对象，如 {"scriptId": "12"}；无参数可省略
      browser_level: False（默认）= 命令发往当前 attach 的页面 session（Debugger/DOM/
                    Network/Page/Runtime 等页面域用这个）；True=浏览器级命令不带
                    sessionId（仅 Browser.getVersion / Target.* 等浏览器域需要）

    Returns: 该 CDP 方法的 result 对象；方法返回错误时抛 RuntimeError（含原始 error）

    典型用法（逆向取源码）：
      1. enable_domain("Debugger")
      2. get_events("Debugger") → 从 scriptParsed 事件拿 scriptId/url/sourceMapURL
      3. send_cdp("Debugger.getScriptSource", {"scriptId": "<id>"}) → {"scriptSource": "..."}

    ⚠️ 责任纪律：这是无白名单全透传，等于完整 DevTools 权限。调用前必须知道该方法的
    效果——破坏性命令（Browser.close 关浏览器、Target.closeTarget 关标签、
    Storage.clearDataForOrigin 清站点数据、Page.navigate 跳走用户页面等）会真实影响
    用户正在用的浏览器，禁止为"试试看"乱发；造成后果由调用方负责。
    """
    async def _do(c):
        r = await c.send(method, params or {}, session_id="" if browser_level else None)
        if r.get("error"):
            raise RuntimeError(f"CDP {method} 返回错误: {r['error']}")
        return r.get("result", {})

    return await _run(_do)


def main():
    """CLI entry point — also used by pyproject.toml [project.scripts]."""
    print("[cdp-mcp] starting...", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()

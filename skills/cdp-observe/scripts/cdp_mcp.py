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

from mcp.server.fastmcp import FastMCP

# 让 cdp_core 可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cdp_core import CDP, detect_ws_url, select_target, chrome_running

mcp = FastMCP("cdp-debug")

# —— 全局状态：CDP 实例 + 事件缓冲（和 cdp_proxy 里的设计一样）——
_cdp: CDP | None = None
_event_buffer: list[dict] = []  # 用 list 当 deque 用（简洁）
_event_maxlen = 200
_lock = asyncio.Lock()


async def _ensure_cdp():
    """懒加载：第一次 tool call 时才连 Chrome。后续复用。"""
    global _cdp
    async with _lock:
        if _cdp is not None:
            return _cdp
        ws_url, mode, _ = await detect_ws_url()
        if not ws_url:
            if chrome_running():
                raise RuntimeError(
                    "Chrome 运行中但未开远程调试：chrome://inspect → 勾选 Allow remote debugging"
                )
            raise RuntimeError("未检测到 Chrome，请先启动 Chrome")
        _cdp = CDP()
        await _cdp.connect(ws_url)
        await _cdp.start()
        _cdp.on_event(_on_event)
        target = await _cdp.ensure_tab(os.environ.get("CDP_TARGET"))
        await _cdp.attach_page(target["targetId"])
        return _cdp


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
    c = await _ensure_cdp()
    return await c.pages()


@mcp.tool()
async def eval(expr: str) -> dict:
    """在当前 tab 执行 JavaScript 表达式。

    Args: expr — JS 表达式或语句，如 "document.title" 或 "({url: location.href})"
    Returns: {"result": <JS返回值>} 或 {"err": "<异常文本>"}
    """
    c = await _ensure_cdp()
    return {"result": await c.eval(expr)}


@mcp.tool()
async def take_screenshot(path: str) -> str:
    """截图并保存为 PNG。

    Args: path — 本地保存路径，如 "debug.png" 或 "H:/temp/shot.png"
    """
    c = await _ensure_cdp()
    return await c.shot(path)


# —— 页面管理 ——

@mcp.tool()
async def navigate(url: str) -> str:
    """导航到 URL。

    Args: url — 完整 URL，如 "https://www.baidu.com"
    """
    c = await _ensure_cdp()
    await c.navigate(url)
    return url


@mcp.tool()
async def ensure_tab(url_substr: str | None = None, create_url: str = "about:blank") -> dict:
    """确保目标 tab 存在 — 有匹配 tab 则切换并 attach，无则创建新 tab。

    Args:
        url_substr: 要找的 URL 子串，None 表示找任意非 chrome:// 页面
        create_url: 找不到时创建新 tab 的 URL
    Returns: target dict（含 targetId, url, title）
    """
    c = await _ensure_cdp()
    target = await c.ensure_tab(url_substr, create_url)
    await c.attach_page(target["targetId"])
    return target


@mcp.tool()
async def open_tab(url: str) -> str:
    """新建 tab 打开 URL 并 attach。

    Args: url — 新 tab 打开的 URL
    Returns: 新 tab 的 targetId
    """
    c = await _ensure_cdp()
    target_id = await c.create_target(url)
    await asyncio.sleep(0.3)
    await c.attach_page(target_id)
    return target_id


@mcp.tool()
async def close_tab(target_id: str) -> bool:
    """关闭指定 tab。

    Args: target_id — 目标页 ID（从 list_pages / ensure_tab 返回）
    """
    c = await _ensure_cdp()
    return await c.close_target(target_id)


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
    c = await _ensure_cdp()
    if selector:
        return await c.click(selector, button=button)
    elif x is not None and y is not None:
        return await c.click((float(x), float(y)), button=button)
    else:
        raise ValueError("需要 selector 或 x/y")


@mcp.tool()
async def hover(selector: str | None = None, x: float | None = None, y: float | None = None) -> bool:
    """悬停到元素中心。

    Args: selector — CSS selector，或提供 x/y 坐标
    """
    c = await _ensure_cdp()
    if selector:
        return await c.hover(selector)
    elif x is not None and y is not None:
        return await c.hover((float(x), float(y)))
    else:
        raise ValueError("需要 selector 或 x/y")


@mcp.tool()
async def type_text(text: str, selector: str | None = None) -> bool:
    """输入文本。可选先聚焦 selector 元素（会自动 click 一下）。

    Args:
        text: 要输入的文本
        selector: 可选，输入前先 click 聚焦哪个元素
    """
    c = await _ensure_cdp()
    return await c.type_text(text, selector=selector)


@mcp.tool()
async def press_key(key: str, modifiers: int = 0) -> bool:
    """按键。

    Args:
        key: KeyboardEvent.key 值，如 "Enter" / "Tab" / "Escape" / "Backspace" / "ArrowDown" / "a" / "5"
        modifiers: 修饰键位组合（0=none, 1=Alt, 2=Ctrl, 4=Meta, 8=Shift，可相加）
    """
    c = await _ensure_cdp()
    return await c.press_key(key, modifiers=modifiers)


@mcp.tool()
async def handle_dialog(accept: bool = True, prompt_text: str | None = None) -> bool:
    """处理 JS 对话框（alert / confirm / prompt / beforeunload）。

    Args:
        accept: True=确定，False=取消
        prompt_text: 处理 prompt 对话框时填写的文本
    """
    c = await _ensure_cdp()
    return await c.handle_dialog(accept=accept, prompt_text=prompt_text)


# —— 事件类 ——

@mcp.tool()
async def enable_domain(domain: str) -> bool:
    """启用 CDP 事件域（幂等，重复调用跳过）。启用后事件会自动缓冲。

    Args: domain — CDP 域名，如 "Network" / "DOM" / "Page" / "Runtime" / "Log"
    Returns: True=这次实际 enable 了；False=之前已 enable
    """
    c = await _ensure_cdp()
    return await c.enable_domain(domain)


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


if __name__ == "__main__":
    print("[cdp-mcp] starting...", file=sys.stderr)
    mcp.run()

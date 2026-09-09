# 调试命令（Chrome / CDP）

## 前置

用户 Chrome 已开启远程调试（`chrome://inspect/#remote-debugging` 勾选，或传统 `--remote-debugging-port`）。
python 需 aiohttp（系统 python 缺则用 ComfyUI 运行副本 `H:\ComfyUI_Windows_portable\python_standalone\python.exe`）。

## ⚠️ 硬性要求：一律走常驻代理长连接

一次调试少则 4~5 条命令；单次命令每条都是新连接、各弹一次授权。**即使再小的调试也只用常驻代理**，禁止直接调 `cdp.py`。

## 常驻代理（唯一方式）

```bash
# 0. 确保代理在跑（没跑就起，起时弹一次授权；Chrome 重启后需重起）
curl -s -m 2 http://127.0.0.1:9333/ -d '{"pages":1}' >/dev/null 2>&1 \
  || (python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 > <repo>/_cdp_proxy.log 2>&1 &)
sleep 1

# 1. 通过本地端口发命令（连接保持，不弹窗）
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
```

浏览器/Chrome 重启后代理连接失效，需重启代理（重新弹一次授权）。

## 单次命令（仅兜底，代理不可用/无法重起时）

每条命令各弹一次授权，优先 `multi` 一次连多条：

```bash
# 列出页面 tab
python <repo>/skills/cdp-observe/scripts/cdp.py list

# 执行一段 JS 并返回结果
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'

# 一次连接执行多条 JS（只弹一次授权）
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...

# 截图
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
```

## 目标页选择

代理启动时选定：有 `CDP_TARGET` 用其 URL 子串（调试任意应用），否则选含 `8188` 的 tab（ComfyUI 常用），再无则第一个 tab：

```bash
# 调试其他应用：起代理前指定目标（常驻代理同样适用）
CDP_TARGET=127.0.0.1:5000 python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &
# 或先列出所有 tab 确认目标
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
```

## Chrome 配置操作

```bash
# 检查调试端口
curl -s http://127.0.0.1:9222/json/version        # 传统模式（inspect 模式会 404 属正常）
cat "$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort"   # inspect 模式读此文件（端口 + ws 路径）

# 重建「Chrome（Claude可接管）」桌面快捷方式（带 --remote-debugging-port + 专用 profile，无授权弹窗）
python -c "import win32com.client as w; s=w.Dispatch('WScript.Shell'); sc=s.CreateShortCut(r'D:\用户文件\桌面\Chrome（Claude可接管）.lnk'); sc.TargetPath=r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'; sc.Arguments='--remote-debugging-port=9222 --user-data-dir=\"H:\\temp\\chrome-debug-profile\"'; sc.Save(); print('ok')"
```

详见 [setup.md](setup.md)（Chrome 136+ 安全变更、两种开启方式）。

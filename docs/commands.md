# 调试命令（Chrome / CDP）

## 前置

用户 Chrome 已开启远程调试（`chrome://inspect/#remote-debugging` 勾选，或传统 `--remote-debugging-port`）。
python 需 aiohttp（系统 python 缺则用 ComfyUI 运行副本 `H:\ComfyUI_Windows_portable\python_standalone\python.exe`）。

## 常驻代理（推荐，避免重复授权弹窗）

```bash
# 后台启动（启动时弹一次授权，之后随时操作不弹窗）
python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &

# 通过本地端口发命令（连接保持）
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
```

浏览器/Chrome 重启后代理连接失效，需重启代理（重新弹一次授权）。

## 单次命令（cdp.py，每次连接弹一次授权）

```bash
# 列出页面 tab
python <repo>/skills/cdp-observe/scripts/cdp.py list

# 执行一段 JS 并返回结果（默认 8188 页面）
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'

# 一次连接执行多条 JS（只弹一次授权）
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...

# 截图
python <repo>/skills/cdp-observe/scripts/cdp.py shot <文件.png>
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

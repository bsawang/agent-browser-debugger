# 调试命令速查

## 前置

用户 Chrome 已开启远程调试（`chrome://inspect/#remote-debugging` 勾选，或传统 `--remote-debugging-port`）。
Python 需 aiohttp（`pip install aiohttp`）。

## 快速探测（不弹授权）

```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect
# 输出 mode: inspect / traditional → 已开调试
# 输出 Chrome 未开远程调试 → 提示用户开启
```

## 常驻代理（⚠️ 硬性要求：一律走代理）

chrome://inspect 模式下每次**新 CDP 连接**弹一次授权。代理启动时连一次，之后所有命令复用。

```bash
# 0. 确保代理在跑
curl -s -m 2 http://127.0.0.1:9333/ -d '{"pages":1}' >/dev/null 2>&1 \
  || (python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &)
sleep 1

# 1. 发命令
curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'
curl -s http://127.0.0.1:9333/ -d '{"shot":"<png路径>"}'
curl -s http://127.0.0.1:9333/ -d '{"navigate":"<url>"}'
curl -s http://127.0.0.1:9333/ -d '{"ensure":"<url子串>"}'   # 有则复用，无则创建
curl -s http://127.0.0.1:9333/ -d '{"open":"<url>"}'         # 显式新建 tab
curl -s http://127.0.0.1:9333/ -d '{"pages":1}'
curl -s http://127.0.0.1:9333/ -d '{"detect":1}'             # 只读探测
```

Chrome 重启后代理失效，需重启（重新弹一次授权）。

## 事件监听

```bash
curl -s http://127.0.0.1:9333/ -d '{"enable":"Network"}'     # 启用事件域
curl -s http://127.0.0.1:9333/ -d '{"events":"Network"}'     # 拉事件（支持 domain 过滤）
curl -s http://127.0.0.1:9333/ -d '{"clear_events":1}'        # 清空缓冲
```

## 单次 CLI（仅兜底，每条命令各弹一次授权）

```bash
python <repo>/skills/cdp-observe/scripts/cdp.py detect
python <repo>/skills/cdp-observe/scripts/cdp.py open '<url>'
python <repo>/skills/cdp-observe/scripts/cdp.py list
python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'
python <repo>/skills/cdp-observe/scripts/cdp.py multi '<js1>' '<js2>' ...
python <repo>/skills/cdp-observe/scripts/cdp.py shot <file.png>
python <repo>/skills/cdp-observe/scripts/cdp.py navigate '<url>'
```

## 目标页选择

代理/CLI 自动 `ensure_tab` — 优先匹配 `CDP_TARGET` 环境变量，然后找第一个非 chrome:// 页面，**全部没有时自动创建 `about:blank`**。

```bash
# 指定目标 URL 子串
CDP_TARGET=example.com python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &
CDP_TARGET=example.com python <repo>/skills/cdp-observe/scripts/cdp.py list

# 指定创建 URL（默认 about:blank）
CDP_CREATE_URL=https://example.com python <repo>/skills/cdp-observe/scripts/cdp_proxy.py 9333 &
```

## Chrome 配置

```bash
# 传统模式（--remote-debugging-port）
curl -s http://127.0.0.1:9222/json/version
# inspect 模式
cat "$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort"
```

详见 [setup.md](setup.md)（Chrome 136+ 安全变更、两种开启方式）。

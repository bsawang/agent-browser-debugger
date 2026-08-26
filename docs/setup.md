# Chrome 远程调试配置

## 为什么有这些坑

**Chrome 136+（2025-04）安全变更**：`--remote-debugging-port` 在**默认数据目录**下被**静默忽略**（防止攻击者附加到真实 profile 窃取 Cookie）。必须配 `--user-data-dir` 指向非默认目录，或改用 `chrome://inspect` 手动开启。

参考：
- [Chrome for Developers — 远程调试开关变更](https://developer.chrome.google.cn/blog/remote-debugging-port?hl=zh_tw)
- [Google 支持 — 远程调试版本说明](https://support.google.com/chrome/a/answer/10314655?hl=en)
- [juejin — remote-debugging-port 突然无效](https://juejin.cn/post/7526737895382990882)

## 两种开启方式

### 方式 A：chrome://inspect（推荐日常，保留登录）

1. Chrome 地址栏输入 `chrome://inspect/#remote-debugging`
2. 勾选「Allow remote debugging for this browser instance」
3. Chrome 写 `DevToolsActivePort` 文件到数据目录，监听 9222（新协议）
4. **注意**：此模式下每次**新 CDP 连接**会弹授权提示（Chrome 144+ 设计，无永久信任）；用常驻代理（cdp_proxy.py）保持单连接避免重复弹窗

来源：[Chrome DevTools MCP 配置](https://playwright.dev/mcp/configuration/browser-extension) · [chrome 144 简化 MCP](https://linux.do/t/topic/1479459)

### 方式 B：传统 `--remote-debugging-port`（无授权弹窗，但独立 profile）

需专用 profile（Chrome 136+ 默认目录被忽略）：
```
chrome.exe --remote-debugging-port=9222 --user-data-dir="H:\temp\chrome-debug-profile"
```
- 无授权弹窗，HTTP `/json` 可用（传统发现方式）
- 独立 profile：登录/书签不在，需重新配置
- 迁移原数据目录到非默认路径，App-Bound 加密的登录 Cookie 可能仍失效

## 快捷方式

桌面「Chrome（Claude可接管）」快捷方式 = 方式 B（专用 profile + 9222，无弹窗），备用于不想用 chrome://inspect 时。
任务栏 Chrome 为日常入口（默认 profile，无调试参数）。

## 端口检查

```bash
# 传统模式
curl -s http://127.0.0.1:9222/json/version
# inspect 模式（HTTP /json 返回 404 属正常，读文件拿连接地址）
cat "$LOCALAPPDATA/Google/Chrome/User Data/DevToolsActivePort"
# 期望两行：端口 + /devtools/browser/<uuid>
```

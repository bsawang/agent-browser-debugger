# ComfyUI 专题命令

通过 CDP 调试 ComfyUI 前端（观察节点 / 触发执行 / 重启等）。

> 通过哪个入口发命令：常驻代理 `curl -s http://127.0.0.1:9333/ -d '{"eval":"<js>"}'`
> 或单次 `python <repo>/skills/cdp-observe/scripts/cdp.py eval '<js>'`

## 观察节点（JS）

```js
// 节点 widget 结构（name/type/y/高度）
(()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
 return JSON.stringify((n?.widgets||[]).map(w=>({n:w.name,t:w.type,y:w.y,h:w.computedHeight})),null,1);})()

// 节点 DOM / Vue 预览区（视频预览是 video-preview 组件，不在 node.widgets）
(()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
 const d=document.querySelector(`.lg-node[data-node-id="${n.id}"]`);
 const c=d?.querySelector('.lg-node-content');
 return JSON.stringify(c?[...c.children].map(x=>String(x.className).slice(0,40)):null);})()

// 节点实例状态（预览创建、尺寸、输入连接）
(()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
 return JSON.stringify({id:n.id,size:n.size,pos:n.pos,inputs:(n.inputs||[]).map(i=>({name:i.name,link:!!i.link}))});})()

// 页面 video/img 元素
(()=>JSON.stringify({videos:[...document.querySelectorAll('video')].map(v=>[v.videoWidth,v.videoHeight])}))()

// LoadVideo 用的文件
(()=>JSON.stringify(app.graph.nodes.filter(n=>n.type==='LoadVideo').map(l=>({id:l.id,file:l.widgets?.find(w=>w.name==='file')?.value}))))()
```

## 触发执行

```js
// 提交当前工作流执行
app.queuePrompt(0)

// 居中节点 + 触发重绘（视频预览依赖节点被绘制才创建）
(()=>{const n=app.graph.nodes.find(x=>x.type==='VideoComparePreview');
 app.canvas.centerOnNode(n); app.graph.setDirtyCanvas(true,true);})()
```

## 后端状态

```bash
# 最近执行结果（VCP 等输出节点是否输出 images）
curl -s "http://127.0.0.1:8188/history?max_items=3"

# 节点是否注册 / 输入参数
curl -s "http://127.0.0.1:8188/object_info/VideoComparePreview"

# ComfyUI 重启（加载新 custom_nodes / 前端 JS）
curl -s -X POST http://127.0.0.1:8188/manager/reboot -H "Content-Type: application/json" -d '{}'
```

## 踩坑备忘

- **节点在画布视野外时不被绘制** → `onDrawBackground`/预览更新不跑，video widget 不创建：用「居中节点」JS 或让用户滚动画布
- **后端 VCP 输出空**：先查 `history` 确认输出节点有没有 images；再查输入 LoadVideo 的文件是否存在（`get_annotated_filepath`）
- **信息栏定位**：视频预览是 Vue `video-preview` 组件（lg-node-content 内），自定义信息栏要 DOM 插到它之后，不能用 widget（widget 在 widgets 区，永远在预览上方）

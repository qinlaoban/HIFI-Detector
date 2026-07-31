# Hi-Fi Detector

音频高保真度检测工具。前端 Svelte 5 + Vite，后端 FastAPI（Python），桌面壳 Tauri。

## 架构

```
web/                      Svelte 5 前端（开发源）
  ├── src/components/     页面组件（上传/批量/结果/图表/报告）
  ├── src/lib/            i18n / api / charts / reports / utils
  └── vite.config.js      构建产物输出到 hifi_detector/web/static
hifi_detector/
  ├── web/server.py       FastAPI 静态文件服务（挂载 web/static）
  └── web/routes.py       /api/* 分析接口
tauri/                    Tauri 桌面壳（拉起 Python 后端进程）
```

前端为纯静态产物（Vite 构建后无框架运行时依赖，仅依赖 Plotly CDN），由 FastAPI 以静态文件方式提供。Tauri 只打包 Python 后端，窗口直接 `window.navigate` 到后端端口。

## 开发

```bash
# 1. 启动后端（默认 127.0.0.1:8099）
.venv/bin/python -m hifi_detector.cli web --no-open --port 8099

# 2. 启动前端 dev server（代理 /api 到后端，端口 5173）
cd web && npm install && npm run dev
```

dev 模式前端经 Vite dev server 访问，`/api` 请求代理到后端（可用环境变量 `API_PROXY` 覆盖目标地址）。

## 生产构建

```bash
./tauri/build.sh        # macOS / Linux（含前端构建 + PyInstaller + Tauri）
tauri\build.bat         # Windows
```

构建顺序：`npm ci && npm run build`（产物到 `hifi_detector/web/static`）→ PyInstaller 打包 Python（static 已包含在 spec datas 中）→ Tauri build。

## E2E 测试

依赖后端 8099 运行 + 本机 Chrome：

```bash
cd web && node e2e-test.mjs    # 完整流程（上传→结果→图表→报告→批量）
cd web && node batch-only.mjs  # 仅批量流程
```

## 技术说明

- 前端迁移自单文件 `index.html`（Svelte 5 runes + lucide-svelte 图标）。
- i18n 三语言（en/zh/ja），语言偏好存 `localStorage['hifi-lang']`。
- 图标库：Lucide（此前为 Unicode 字符）。

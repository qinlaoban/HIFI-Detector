# Hi-Fi Detector

判断一个音频文件是不是**真 Hi-Res**——标着 24/96、24/192 的文件，到底是真高解析，还是 CD 上采样 / MP3 转码 / 假 24-bit 冒充的。

前端 Svelte 5 + Vite，后端 FastAPI（Python），桌面壳 Tauri。

## 判定结果（5 档）

| 判定 | 含义 |
|---|---|
| 真 Hi-Res（genuine） | 声称 hi-res，且未检测到任何造假迹象 |
| 假 Hi-Res（fake） | 声称 hi-res，检出高置信度造假 |
| 可疑（suspicious） | 声称 hi-res，有造假迹象但证据不足，建议人工复核 |
| 非 Hi-Res（not hi-res） | 实为 CD 或更低规格，规格属实未虚标 |
| 无法判定（undetermined） | 信号过弱（近乎静音），无有效内容可供分析 |

## 能检测什么

1. **上采样**——在合理源奈奎频率（22.05k / 24k / 11k…）处存在“砖墙”式频谱截断：墙下有内容、墙后大面积空白。这是 CD 源拉到 hi-res 的典型特征。
2. **有损转码**——频谱在特定频率（如 MP3 的 16/18/20 kHz）出现陡峭切顶的编码器低通指纹。
3. **假位深**——24-bit 容器的低 8 位为空（16-bit 内容填充），对 /32768 与 /32767 两种归一都检测。

## 检测边界（诚实声明）

本工具**抓假，不发证**。

- **“真 Hi-Res” = 没检测到造假迹象**，不是来源认证。没有任何工具能仅凭文件内容证明它是原始母带。
- **高质量重采样器（多相 FIR）把 CD 上采样到 hi-res 时不留砖墙**，其频谱与“本身偏暗的合法录音”（如古典、原声）在内容上无法区分——这是信息论极限，不可检测。我们如实报告，不强判为假。
- 因此偏暗的合法录音不会被冤枉；但极少数“恰好砖墙截止在 22.05 kHz”的合法文件可能被误判——这类文件本身也不提供 hi-res 带宽。

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

## 单元测试

核心检测算法 + 判定逻辑有 56 个单元测试覆盖，含一组合成信号回归（真录音/暗录音不误判、砖墙上采样检出、假位深 /32768 与 /32767 网格容忍、静音门、genuine 置信度封顶）：

```bash
.venv/bin/python -m unittest discover -s tests
```

集成测试用的音频样本由 `tests/generate_testdata.py` 生成（`tests/testdata/` 已 gitignore，缺失时相关用例自动 skip）。

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

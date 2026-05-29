# AITestPlatform

<div align="center">

### 🤖 AI 驱动的轻量测试管理平台

**让 AI 做重活，让人做决策。**

一站式覆盖 **需求评审 → 用例生成 → UI / API 自动化执行 → 报告分析** 的全链路；
内置 LLM tool-calling 循环 + Playwright MCP，用自然语言描述用例、AI 自驱浏览器跑通业务，
全程录屏 / 快照 / tool_call 可回放。

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue](https://img.shields.io/badge/Vue-3.5+-4FC08D.svg?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6+-3178C6.svg?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Playwright](https://img.shields.io/badge/Playwright-1.59+-2EAD33.svg?logo=playwright&logoColor=white)](https://playwright.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose%20v2-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[快速开始](#-快速开始) · [部署方式](#-部署方式) · [配置](#%EF%B8%8F-配置详解) · [文档](#-进一步阅读)

</div>

---

## 📖 项目介绍

AITestPlatform 是一款**AI 驱动的轻量级测试管理平台**，目标是把测试团队最耗时的"读需求 → 写用例 → 跑回归 → 看报告"四个环节交给 AI 做，让人专注在**需求理解 / 边界覆盖 / 失败诊断**这些真正需要判断力的地方。

技术上采用：

- **后端** FastAPI + SQLAlchemy 2.0 + PostgreSQL，原生异步、SSE 友好
- **前端** Vue 3.5 + TypeScript + Naive UI + UnoCSS，类型安全 + 极简设计
- **AI 层** OpenAI SDK 兼容协议（DeepSeek / 通义 / Ollama / GPT 等），LLM tool-calling 循环
- **浏览器自动化** Playwright + `@playwright/mcp`（微软官方 MCP），AI 直接驱动 chromium
- **容器化** Docker Compose 三容器最小架构（db / backend / frontend）

与同类平台的差异化优势：

| 差异点 | 说明 |
|---|---|
| 🔌 **AI 用 MCP 操作浏览器** | 不写 selector，靠语义定位元素，对页面 DOM 重构强健 |
| 🧪 **三层数据可信度** | 区分"功能问题"和"测试数据问题"，业务通过率自动剔除数据噪音 |
| 🖥️ **服务器也能观察 AI 浏览器** | 内置 Xvfb + x11vnc + noVNC，远程观察 chromium 操作 |
| 🌐 **VPN / 内网场景一键解** | 双路代理（http_login + chromium 出口分别可控），mac/win/linux 三平台都覆盖 |
| 🛠️ **部署运维** | Docker Compose、自动迁移、清理 cron、token 预算守卫、错误回放等生产部署能力 |

---

## 🎯 核心特性

### 一期：测试管理 + AI 助手

| 模块 | 能力 | 优势 |
|---|---|---|
| 📄 **需求文档管理** | Word / PDF / Markdown 上传，AI 自动评审、抽取关键点、给改进建议 | 替代手工通读全文 |
| 📝 **测试用例管理** | 模块树组织、增删改查、Excel 导入导出 | 与项目 / 模块解耦的多对多结构 |
| 🤖 **AI 用例批量生成** | 基于需求文档 + 系统提示词流式生成；支持中断 / 续接 | 一次生成数十条用例，token 预算自动控制 |
| 💬 **AI 智能对话** | 流式 SSE，自动识别"评审" / "生成"意图并触发后台任务；多会话、文件附件 | 用户用自然语言完成几乎所有操作 |
| 🧠 **多 LLM 支持** | OpenAI 协议兼容（DeepSeek / 通义 / Ollama / GPT 等）；平台内多 Provider 配置切换 | 不绑定单一供应商 |
| 📋 **提示词管理** | 系统模板 + 自定义模板；按分类自动注入对话；版本号 + 历史回滚 | 提示词变更可追溯 |
| 👥 **项目 / 角色 / 用户** | 多项目隔离；RBAC 角色（admin / member / viewer）；项目成员 + 全局权限矩阵 | 简单清晰，覆盖小团队所有场景 |
| 📊 **数据仪表盘** | 项目进度、用例覆盖、AI 活动、UI 自动化双视图通过率（业务/执行/任务） | 单页一览所有运营指标 |

### 二期：UI 自动化

| 模块 | 能力 | 优势 |
|---|---|---|
| 🎯 **执行环境** | URL / 浏览器配置 / 前置步骤模板（http_login / ai_login / state_inject）；登录态 storage_state 自动复用 | 一次配置，N 次复用 |
| 📦 **测试物料体系** | 6 种类型（string / secret / multiline / file / random / dataset）× 5 级层级（项目默认 / 环境 / 用例 / 个人 / 一次性覆盖） | 解决"用例只描述做什么、缺少具体数据"的真实痛点 |
| 🤖 **AI 自驱执行** | LLM tool-calling 循环 + Playwright MCP；每步 accessibility 快照 + diff 增量；token 预算守卫 | 非 selector，靠语义定位元素，对页面 DOM 重构强健 |
| ✅ **三层数据可信度** | reliable（真实物料）/ synthesized（AI 自造）/ data_failure；业务通过率自动排除"数据问题导致的失败" | 区分"功能问题"与"测试数据问题" |
| 🔄 **批量执行 + 用例间状态隔离** | 批量任务在每条用例之间执行 `reset_for_next_case`：关闭多余 page、回到 `about:blank`、保留登录态 | 避免上一条用例的弹窗 / 表单状态污染下一条 |
| 🎬 **执行可观察性** | SSE 实时事件流；每步 snapshot before/after + tool_call 时间线；视频 + trace + 截图 | 失败现场可完整回放 |
| 🖥️ **远程观察（noVNC）** | 容器内 Xvfb + x11vnc + websockify，前端 iframe 查看 chromium 画面 | 服务器部署也能观察 AI 的浏览器操作 |
| 🌐 **内网 VPN 兼容** | 双路代理（http_login 专用 + chromium 出口分别可控）；docker-compose.vpn.yml 一键开启 | 被测系统在公司内网时仍可用 |
| 🧹 **自动清理 cron** | 视频 / 截图 / trace / storage_state / 物料 file 按保留天数自动回收 | 长期运行不爆盘 |

### 三期增强：Skill 体系 + API 管理

| 模块 | 能力 | 优势 |
|---|---|---|
| 🧩 **Skill 体系** | OpenClaw 协议对齐；支持 `SKILL.md`、触发词、always / agent_callable 自动激活、自定义 skill 导入、用量统计与安全扫描 | 把平台能力沉淀为可复用工具包 |
| 🌐 **API 环境配置** | 项目级 API 环境 URL；环境变量增删改查；接口请求中通过 `{{变量名}}` 引用 | 测试 / 预发 / 生产环境切换更清晰 |
| 📡 **API 列表** | 独立 API 模块树；接口名称、方法、环境 URL / 自定义 URL、Path、Query、Header、Body、断言管理 | 常规接口测试配置可沉淀到项目模块 |
| 🔎 **接口调试** | 单接口执行；请求和响应在当前页展示；响应 JSON 格式化；复制响应体、复制实际 curl | 调试闭环更接近 Reqable / Postman 的使用习惯 |
| 📊 **批量执行报告** | 勾选多个 API 或执行模块下全部 API；报告展示环境、状态码、通过/失败、断言期望值和实际值 | 快速验证一组接口健康度 |
| 🔁 **API 自动化** | 多接口顺序编排；上游响应字段提取为 `{{runtime.xxx}}`；下游 Query/Header/Body/Path 依赖注入；支持手动和定时执行 | 覆盖登录取 token、创建数据后查询、链路接口回归等场景 |

---

## 🏗️ 系统架构

### 容器拓扑

```
┌────────── User Browser ──────────┐
│ http://host           ws /novnc/ │
└─────────────┬────────────────────┘
              │
          (port 80)
              │
   ┌──────────┴──────────┐
   │  frontend (nginx)   │   ← 静态 SPA + /api/ 反代 + /novnc/ ws 反代
   │  Vue 3 + Naive UI   │
   └────────┬────────────┘
            │ /api/         /novnc/
       (port 8000)     (backend:6080)
            │
   ┌────────┴───────────────────────────────────┐
   │  backend (FastAPI / uvicorn 单 worker)      │
   │ ┌──────────────────────────────────────┐   │
   │ │  业务模块（auth/projects/llm/...)     │   │
   │ │  ChatStreamHub + ExecutionStreamHub  │   │
   │ │  ─────────────────────────────────   │   │
   │ │  Playwright MCP (Node 子进程)         │   │
   │ │  Chromium (有头 → Xvfb :99)           │   │
   │ │  Xvfb + x11vnc + websockify (:6080)  │   │
   │ │  Cleanup cron (asyncio task)         │   │
   │ └──────────────────────────────────────┘   │
   └────────┬───────────────────────────────────┘
            │
       (port 5432)
            │
   ┌────────┴─────────────┐
   │  PostgreSQL 16       │
   │  (named volume pgdata)│
   └──────────────────────┘
```

### 关键数据卷

| Volume | 容器路径 | 用途 | 是否被 nginx 暴露 |
|---|---|---|---|
| `pgdata` | DB 数据目录 | PostgreSQL 持久化 | 否 |
| `backend_uploads` | `/app/uploads` | 一期需求文档、向后兼容根挂载 | 否 |
| `test_data` | `/app/uploads/test-data` | 物料 file 类型的物理文件 | 否（走后端 reveal API） |
| `ui_artifacts` | `/app/uploads/ui_artifacts` | 视频 / trace / 截图 | 是（`/uploads/ui_artifacts/` 只读） |
| `ui_state` | `/app/uploads/ui_state` | BrowserContext storage_state（含登录 cookie） | 否（容器内 chmod 700） |

> 子挂载顺序很重要：父挂载（`backend_uploads`）在前，子挂载（`test_data` / `ui_artifacts` / `ui_state`）在后。Docker 会让子挂载覆盖父挂载里同路径的目录，**反过来则父挂载会把子挂载吞掉**。

### 端口

| 端口 | 服务 | 是否对外暴露 | 配置项 |
|---|---|---|---|
| 80 → host:`${FRONTEND_PORT}` | frontend nginx | 是（用户访问入口） | `.env` 里 `FRONTEND_PORT=8080` 改宿主端口（容器内固定 80） |
| 8000 → host:`${BACKEND_PORT}` | backend uvicorn | 是（开发 / 直接调 API 用） | `.env` 里 `BACKEND_PORT=7008` 改宿主端口（容器内固定 8000） |
| 5432 → host:`${POSTGRES_PORT}` | PostgreSQL | 默认暴露（生产可关，仅留容器网络） | `.env` 里 `POSTGRES_PORT` |
| 6080 | websockify (noVNC) | **否**（仅容器网络，前端经 `/novnc/` 反代） | — |
| 5173 | vite dev server | 仅本地开发 | — |

#### 浏览器访问规则

| 部署场景 | `.env` 配置 | 浏览器访问地址 |
|---|---|---|
| 默认（80 空闲） | `FRONTEND_PORT=80`（或不写） | `http://localhost` 或 `http://your-server-ip` —— **不用带端口** |
| 80 已被占用 | `FRONTEND_PORT=8080` | `http://your-server-ip:8080` —— **必须带端口** |
| 上游有 Caddy/Nginx + HTTPS | `FRONTEND_PORT=8080`（任意，不直接暴露用户）| `https://your-domain.com`（由上游反代到容器 8080） |

> **为什么默认不带端口？** HTTP 默认走 80 端口，浏览器自动补全；只有改成非 80 端口（如 8080）才需要在 URL 里显式写 `:8080`。
> HTTPS 同理：默认走 443 端口，URL 里也不需要写 `:443`。

#### 端口冲突时怎么改？

后端 / 前端宿主端口都是可配置的，**容器内部端口固定不变**（前端 nginx 通过 docker 内部网络反代 `backend:8000`，不受宿主端口影响）：

```bash
# 服务器上 80 / 8000 都被其它项目占用
echo "FRONTEND_PORT=7080" >> .env
echo "BACKEND_PORT=7008"  >> .env
docker compose up -d              # 重建受影响的容器即可，无需改任何代码
```

- 浏览器访问入口：`http://your-server-ip:7080`
- 后端 API（直接调试）：`http://your-server-ip:7008`

---

## 🛠️ 技术栈

| 层 | 选型 | 关键考量 |
|---|---|---|
| **后端框架** | FastAPI 0.115+ | 原生异步、自动 OpenAPI、SSE 友好 |
| **ORM** | SQLAlchemy 2.0（async） + Alembic | 类型驱动、迁移可控 |
| **数据库** | PostgreSQL 16 | 成熟、JSONB / 全文检索、唯一外键 / 约束完整 |
| **认证** | JWT（python-jose）+ bcrypt | 无状态、可平移 |
| **加密** | Fernet（cryptography） | 密码 / API key / 物料 secret 列加密 |
| **AI 调用** | OpenAI SDK 2.x | 通用协议，可对接 DeepSeek / 通义 / Ollama 等 |
| **浏览器自动化** | Playwright 1.59+ + `@playwright/mcp` | LLM tool-calling 直接驱动 chromium |
| **OCR（验证码）** | ddddocr | 全离线、无外网依赖 |
| **文档解析** | python-docx / pypdf / antiword / catdoc | Word / PDF / 旧 .doc 全覆盖 |
| **远程画面** | Xvfb + x11vnc + websockify + noVNC | 容器内有头浏览器实时投屏 |
| **前端框架** | Vue 3.5 + TypeScript 5.6 + Vite 6 | 性能 + 类型安全 |
| **UI 组件库** | Naive UI 2.40 | 轻量、TS 原生、主题灵活 |
| **CSS** | UnoCSS + 设计 tokens 自定义 | 按需生成、无运行时 |
| **状态管理** | Pinia | Vue 官方推荐 |
| **HTTP 客户端** | ofetch | 体积小、原生 SSE |
| **包管理** | uv（后端）+ pnpm（前端） | 极速、严格 lockfile |
| **容器化** | Docker Compose | 三容器最小架构 |
| **CI / CD** | GitHub Actions + GHCR | 镜像自动构建推送（详见 [`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md)） |
| **进程模型** | uvicorn 单 worker | 内存内 ChatStreamHub / ExecutionStreamHub 不可跨进程；扩容需先迁移到 Redis pub/sub 或 PG LISTEN/NOTIFY |

---

## 📂 项目结构

```
AITestPlatform/
├── docker-compose.yml          # 生产部署编排（默认）
├── docker-compose.dev.yml      # 开发数据库（仅 db）
├── docker-compose.vpn.yml      # VPN 场景 override（详见 §部署方式 D-1）
├── docker-compose.prod.yml     # GHCR 镜像拉取部署（详见 docs/DEPLOYMENT_GHCR.md）
├── run.sh                      # 主命令入口（dev / up / redeploy / docker-smoke / db-* / test ...）
├── Makefile                    # run.sh 的子集（兼容传统 make 用户）
├── scripts/
│   ├── init.sh                 # 一键初始化（首次部署推荐）
│   └── release.sh              # 打 tag + 推送 GHCR 触发 CI
├── .env.example                # 环境变量模板
├── .github/workflows/          # GitHub Actions：build-and-push.yml
├── docs/                       # 设计文档
│   ├── NEW_PLATFORM_DESIGN.md  # 一期总体设计
│   ├── IMPLEMENTATION_PLAN.md  # 一期实施计划
│   ├── PHASE2_DESIGN.md        # 二期 UI 自动化设计
│   ├── PHASE2_IMPLEMENTATION_PLAN.md
│   ├── PHASE3_DESIGN.md        # 三期 Skill 体系设计
│   ├── PHASE3_IMPLEMENTATION_PLAN.md
│   ├── PHASE3_DOCKER_VALIDATION.md
│   ├── PROMPT_MANAGEMENT_DESIGN.md
│   ├── DEPLOYMENT_GHCR.md      # GHCR 拉取镜像部署完整教程
├── backend/                    # FastAPI 后端
│   ├── Dockerfile              # 含 Node + Chromium + Xvfb + noVNC
│   ├── entrypoint.sh           # 启动 Xvfb / x11vnc / websockify / 等待 DB / 迁移 / 建管理员
│   ├── pyproject.toml / uv.lock
│   ├── alembic.ini / alembic/  # 数据库迁移
│   └── app/
│       ├── main.py             # FastAPI 装载所有 router
│       ├── config.py           # Settings（Pydantic）
│       ├── database.py         # async session
│       ├── core/               # 通用：security / crypto / deps / exceptions
│       └── modules/
│           ├── auth/           # 登录、JWT、角色
│           ├── users/          # 用户 CRUD
│           ├── projects/       # 项目 + 成员 + 角色绑定
│           ├── requirements/   # 需求文档上传 / 解析 / 评审
│           ├── llm/            # LLM Provider 配置 + 对话 + 意图识别
│           ├── prompts/        # 提示词模板（系统/自定义/版本）
│           ├── testcases/      # 用例 + 模块树 + AI 生成
│           ├── dashboard/      # 项目维度统计（含 UI 双视图通过率）
│           ├── ui_automation/  # 二期：执行引擎 / 环境 / cleanup cron
│           ├── test_data/      # 二期：物料管理（6 种类型 × 5 级层级）
│           ├── api_testing/    # 三期：API 环境 / API 列表 / 批量执行 / API 自动化
│           ├── skills/         # 三期：Skill 管理 / 导入 / 安全扫描 / 用量统计
│           └── admin/          # 二期：超管 API（手动触发清理等）
└── frontend/                   # Vue 3 SPA
    ├── Dockerfile              # multi-stage：node 构建 → nginx 部署
    ├── nginx.conf              # SPA + /api/ 反代 + /novnc/ 反代 + 静态缓存
    ├── package.json / pnpm-lock.yaml
    └── src/
        ├── views/              # 页面（按业务域分组）
        ├── components/         # 组件
        ├── stores/             # Pinia
        ├── services/           # API 客户端
        ├── composables/        # useChat / useExecutionSSE / usePermission
        ├── router/             # 路由 + 守卫
        └── theme/              # NaiveUI 主题覆盖
```

---

## 🎨 界面展示

> 📸 **截图陆续补充中**。如果你已经在使用本项目，欢迎 PR 截图到 `docs/screenshots/` 目录帮助新用户快速了解产品。

期望补齐的截图清单：

- 登录页（`/login`）
![项目截图](./image/login_image.png)
- 数据仪表盘（项目维度统计 / 双视图通过率）
![项目截图](./image/yibiao_image.png)
- 测试用例管理（模块树 + AI 生成）
![项目截图](./image/testcases_image.png)
- 需求管理（文档上传 + AI 评审）
![项目截图](./image/requirements_image.png)
- AI 智能对话（流式 SSE）
![项目截图](./image/ai_image.png)
- UI 自动化执行监控（SSE 时间线 + noVNC 观察）
![项目截图](./image/uiTest_image.png)
- 执行报告详情（视频 / trace / 截图回放）
![项目截图](./image/uiBaogao_image.png)
- API 管理（环境配置 / API 列表 / API 自动化）
- 测试物料管理（6 种类型 × 5 级层级）
![项目截图](./image/wuliao_image.png)
- 项目管理
![项目截图](./image/project_image.png)
- LLM Provider 配置
![项目截图](./image/llm_image.png)

---

## 🚀 快速开始

### 在线体验

> 🌐 http://49.232.246.119:7080/login
>    ps:admin/admin123

### 环境要求

| 部署方式 | 必需 | 推荐版本 |
|---|---|---|
| **本地开发** | Docker（仅 DB） + Python 3.11 + Node 18+ + uv + pnpm | Docker Desktop 最新；Python 3.11；Node 20 LTS |
| **Docker 本地部署** | Docker 20.10+ + Compose v2 | Docker Desktop 4.30+ |
| **Linux 服务器部署** | Docker 20.10+ + Compose v2 | Ubuntu 22.04 / Debian 12 / RHEL 9 |
| **GHCR 拉取部署** | Docker 20.10+ + Compose v2 + 公网（或 GHCR mirror） | 见 [`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md) |
| **VPN 场景（D-1）** | 上面任一 + 宿主机已连接公司 VPN + 一个 HTTP 代理工具（pproxy / mitmproxy / tinyproxy 任一） | — |
| **VPN 场景（D-2）** | Linux 主机 + WireGuard 或 OpenVPN 配置文件 | Ubuntu 22.04+ |

最低硬件：

- CPU：2 核
- 内存：4 GB（Chromium + Node MCP 子进程吃 1-1.5 GB）
- 磁盘：10 GB（基础镜像 ~4 GB；视频 / trace 按 `UI_MEDIA_RETENTION_DAYS` 滚动）

### 路径 A：本地体验（5 分钟）

```bash
# 1. 克隆代码
git clone <repo-url> && cd AITestPlatform

# 2. 一键初始化（自动 .env / build / up / 健康检查；首次约 10 分钟含 Chromium）
bash scripts/init.sh

# 3. 浏览器访问
# 前端：http://localhost                     ← 默认 80 端口，URL 里不需要写
# 若 .env 改了 FRONTEND_PORT=8080：http://localhost:8080
# 后端 Swagger：http://localhost:8000/docs    ← DEBUG=true 时

# 4. 登录默认账号
# 用户名：admin
# 密码：admin123 （首次登录后立即修改！）

# 5. 配一个 LLM Provider
# 进入「系统设置 → LLM 配置」，新增一个 OpenAI 协议兼容的 Provider
# （DeepSeek / 通义 / Ollama / GPT 等任选）即可开始使用 AI 功能
```

### 路径 B：服务器生产部署（3-5 分钟，⭐ 推荐）

不用 git clone 整个仓库，不用本地 build，直接拉 GitHub Actions 预构建好的镜像：

```bash
# 1. 服务器上准备目录 + 下载部署文件（不是整个仓库！）
mkdir -p ~/aitestplatform && cd ~/aitestplatform
curl -fsSL -o docker-compose.prod.yml \
  https://raw.githubusercontent.com/<your-username>/AITestPlatform/main/docker-compose.prod.yml
curl -fsSL -o .env.example \
  https://raw.githubusercontent.com/<your-username>/AITestPlatform/main/.env.example
cp .env.example .env

# 2. 编辑 .env：填 GHCR_OWNER / SECRET_KEY / ENCRYPT_KEY / ADMIN_PASSWORD / POSTGRES_PASSWORD
nano .env

# 3. 拉镜像 + 启动
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d

# 4. 验证 + 浏览器访问
curl --noproxy "*" http://localhost/api/health
# 期望：{"status":"ok"}
```

完整 10 步详细教程（含装 Docker、生成密钥、防火墙开端口、HTTPS 反代、开机自启、升级、回滚、首次部署常见坑）：→ [§方案 E：GHCR 拉取预构建镜像](#方案-eghcr-拉取预构建镜像最快3-5-分钟部署--生产首次部署推荐)

### 想看其它部署方式？

→ [📦 部署方式](#-部署方式)（共 5 种方案：本地开发 / Docker 本地 / 服务器自 build / VPN 内网 / GHCR 拉取）

---

## 📦 部署方式

提供五种部署模式，覆盖从本地开发到生产环境的所有场景：

| 方案 | 适用场景 | 启动方式 | 首次耗时 |
|---|---|---|---|
| **A** | 本地开发联调（前后端热更新） | `./run.sh dev` | 5 分钟 |
| **B** | 本地或测试环境 Docker 一键 | `bash scripts/init.sh` | 10-15 分钟（含本地 build） |
| **C** | Linux 服务器自己 build 部署 | 同 B + 生产化清单 | 10-15 分钟 |
| **D** | 被测系统在公司内网 / 需 VPN | D-1 宿主机代理 / D-2 容器内 VPN | 同 B/C |
| **⭐ E** | **生产服务器首选**：拉 GHCR 预构建镜像，无需本地 build | 见 [§方案 E](#方案-eghcr-拉取预构建镜像最快3-5-分钟部署--生产首次部署推荐) | **3-5 分钟** |

> 💡 **第一次在服务器上部署？** 强烈推荐**方案 E**：跳过本地 build（节省 10 分钟），直接拉 GitHub Actions 预构建好的镜像，几行命令搞定。

### 方案 A：本地开发（前后端热更新）

适合本地开发联调。数据库在容器里，前后端跑在宿主机。

```bash
# 1. 安装工具链
brew install uv node pnpm                # macOS
# Linux: curl -LsSf https://astral.sh/uv/install.sh | sh && nvm install 20 && npm i -g pnpm

# 2. 克隆 + 准备 env
git clone <repo-url> && cd AITestPlatform
cp .env.example .env

# 3. 安装依赖（首次执行）
./run.sh install
# 等价：cd backend && uv sync && cd ../frontend && pnpm install

# 4. 一键启动开发环境
./run.sh dev
# 自动完成：
#   - docker compose -f docker-compose.dev.yml up -d db   # 仅起 PostgreSQL
#   - 后端：uv run uvicorn app.main:app --reload  → :8000
#   - 前端：pnpm dev                              → :5173
```

访问：

| 服务 | 地址 |
|---|---|
| 前端（热更新） | http://localhost:5173 |
| 后端 API + Swagger | http://localhost:8000/docs |

> 默认管理员：`admin / admin123`，由 `backend/entrypoint.sh` 在容器**首次**启动时通过 inline Python 脚本创建（DB 中已存在 admin 时跳过）。本地开发模式下后端跑在宿主机、不走 entrypoint，**所以本地首次启动需要先建表 + 建管理员**：
>
> ```bash
> cd backend
>
> # 1. 建表（应用全部 alembic 迁移）
> uv run alembic upgrade head
>
> # 2. 建系统角色 + 默认 admin 用户
> #    复用 entrypoint.sh 里的同一段 Python；只在 admin 不存在时才插入
> uv run python -c "
> import asyncio, os
> from sqlalchemy import select, or_, insert
> from app.database import async_session_factory
> from app.modules.auth.models import User, Role, user_roles
> from app.modules.auth.init_data import init_roles
> from app.core.security import hash_password
>
> async def main():
>     await init_roles()
>     async with async_session_factory() as db:
>         exists = (await db.execute(
>             select(User).where(or_(User.username == 'admin', User.email == 'admin@aitest.local'))
>         )).scalar_one_or_none()
>         if exists:
>             print('admin already exists'); return
>         u = User(username='admin', email='admin@aitest.local',
>                  hashed_password=hash_password('admin123'),
>                  display_name='系统管理员', is_superuser=True, is_active=True)
>         db.add(u); await db.flush()
>         ar = (await db.execute(select(Role).where(Role.name == 'admin'))).scalar_one_or_none()
>         if ar:
>             await db.execute(insert(user_roles).values(user_id=u.id, role_id=ar.id))
>         await db.commit()
>         print('admin created: admin / admin123')
>
> asyncio.run(main())
> "
> ```
>
> 注意：`docker-compose.dev.yml`（开发用）与 `docker-compose.yml`（生产用）使用**不同的 PG named volume**（`pgdata_dev` vs `pgdata`），数据**不互通**。所以方案 A 模式下永远是从 `pgdata_dev` 起步的，第一次必须手动跑上面的两步。

数据库管理：

```bash
./run.sh db-migrate "add foo column"  # 生成迁移
./run.sh db-upgrade                    # 应用迁移
./run.sh db-reset                      # 重置（开发用，会清数据！）
```

### 方案 B：Docker 本地一键部署（推荐）

最常用方式。三个容器（db / backend / frontend），一行命令启动。

#### B-1：自动化（推荐首次部署）

```bash
git clone <repo-url> && cd AITestPlatform

bash scripts/init.sh
# 脚本会自动完成：
#   1. 检查 docker / docker compose 可用
#   2. 从 .env.example 复制 .env，并生成随机 SECRET_KEY
#   3. docker compose build         （首次约 5–10 分钟，含 Chromium）
#   4. docker compose up -d
#   5. 健康检查 /api/health 直到就绪
```

完成后：

| 服务 | 地址 |
|---|---|
| 前端 | http://localhost（端口默认 80，由 `.env` 的 `FRONTEND_PORT` 控制；80 是 HTTP 默认端口，URL 不需要写） |
| 后端 Swagger | http://localhost:8000/docs（端口默认 8000，由 `.env` 的 `BACKEND_PORT` 控制） |

默认管理员：`admin / admin123`，**首次登录后立即修改！**

> **服务器上 80 / 8000 被其它项目占用？** 在 `.env` 里加：
> ```bash
> FRONTEND_PORT=8080      # 浏览器访问端口（改了之后访问要带端口）
> BACKEND_PORT=7008       # API 端口
> ```
> 然后 `docker compose up -d` 重建即可。容器内 nginx / uvicorn 仍是 80 / 8000，
> 前端反代不受宿主端口影响（详见上文 [端口](#端口) 章节）。

#### B-2：手动逐步（看清楚每一步）

```bash
git clone <repo-url> && cd AITestPlatform

# 1. 准备 .env
cp .env.example .env
# 修改：SECRET_KEY / POSTGRES_PASSWORD / ADMIN_PASSWORD

# 2. （可选）生成 ENCRYPT_KEY；不设置则用 config.py 的开发默认值
python -c "from cryptography.fernet import Fernet; print('ENCRYPT_KEY=' + Fernet.generate_key().decode())" >> .env

# 3. 构建镜像
docker compose build

# 4. 启动
docker compose up -d

# 5. 看日志确认 backend 就绪
docker compose logs -f backend
# 看到 "Uvicorn running on http://0.0.0.0:8000" 即可（这是容器内端口，不变）

# 6. 健康检查（宿主机端口默认 8000；若 .env 里改了 BACKEND_PORT 就用新端口）
curl --noproxy "*" http://localhost:${BACKEND_PORT:-8000}/api/health
# {"status":"ok","service":"AITestPlatform"}
```

#### B-3：升级与重启

```bash
git pull
docker compose build                  # 重新构建
docker compose up -d                  # 增量重启（仅变化的服务）

# 仅重建 frontend（改 nginx.conf / Vue 代码常用）
docker compose up -d --build frontend

# 仅重建 backend（改 Python 代码常用）
docker compose up -d --build backend
```

> **关键坑**：`docker compose up -d --build frontend` 也会顺便 recreate 它依赖的 backend 容器（`depends_on`）。如果你刚刚通过 vpn override 启动过 backend，这次普通命令会把 vpn override 的环境变量清空。带 override 时**每次都要带全文件参数**：
> ```bash
> docker compose -f docker-compose.yml -f docker-compose.vpn.yml up -d backend
> ```

#### B-4：本地 Docker 热更新验收（三期 13.4-13.8）

当前三期已完成的物料语义化、环境风险等级、即席用例、`runtime_data` /
`{{runtime.xxx}}`、`failure_diagnosis` 独立 skill 都通过 **数据库迁移 + 后端
内置 skill 同步 + 前端静态产物** 生效；不需要新增容器或额外服务。

本地已经有容器时，日常验收推荐：

```bash
# 首次或依赖/Dockerfile/nginx/entrypoint 变更后：完整重建
./run.sh up

# VPN / 公司内网被测系统场景：保留 docker-compose.vpn.yml override
./run.sh up-vpn
# 等价：
# docker compose -f docker-compose.yml -f docker-compose.vpn.yml up -d --build

# 只改 Python / alembic / Vue 业务代码时：走热更新
./run.sh redeploy backend       # 同步 backend/app + alembic，重启后自动 upgrade head
./run.sh redeploy frontend      # 本地 pnpm build 后同步 dist 到 nginx

# VPN 场景热更新必须用 vpn 版本，避免普通 compose 覆盖 backend 代理环境
./run.sh redeploy-vpn backend
./run.sh redeploy-vpn frontend

# 启动或热更新后做验收前检查
./run.sh docker-smoke
./run.sh docker-smoke-vpn        # VPN 场景使用
```

`run.sh` 的本地探活会显式绕过宿主机代理；如果你手动 `curl localhost`
验证，也建议加 `--noproxy "*"`，避免本机 `HTTP_PROXY/ALL_PROXY` 把请求送到代理端口。

`docker-smoke` 会检查：

- `GET /api/health` 是否可访问；
- 前端 nginx 页面是否可访问；
- 容器内 `alembic current` 是否能读取当前迁移；
- 三期 `failure_diagnosis` 的 4 个 `system__failure_diagnosis__*` 工具是否注册到
  backend 运行时。

三期功能验收入口：

- 物料语义化：测试物料集编辑页，检查字段 `purpose / semantic / source_type`
  与 CSV 导入的 `semantic` 列。
- 风险环境：UI 环境列表/编辑页，检查 `risk_level` 与严格确认文案。
- 即席用例：聊天里说“帮我测试 xxx 流程”，无匹配用例时应出现可编辑的即席步骤确认卡。
- runtime_data：多用例编排中先保存 `runtime_data`，后续步骤使用 `{{runtime.xxx}}`。
- 失败诊断：失败执行事件卡点击“失败诊断”，或直接说“请诊断任务 <task_id> 为什么失败”，应输出 FixActionCard。

### 方案 C：Linux 服务器部署

与方案 B 几乎相同，但有几个生产化要点。

#### 生产化清单

```bash
# 1. 安装 Docker（Ubuntu / Debian）
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. 拷贝项目
scp -r AITestPlatform user@server:/opt/
ssh user@server
cd /opt/AITestPlatform

# 3. 准备生产 .env（强密码、关 DEBUG）
cp .env.example .env
vi .env
# 必改：
#   SECRET_KEY=$(openssl rand -base64 48)
#   ENCRYPT_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
#   POSTGRES_PASSWORD=<强密码>
#   ADMIN_PASSWORD=<强密码>
#   DEBUG=false

# 4. 启动
docker compose up -d --build

# 5. （可选）反向代理：在 nginx 前再套一层 Caddy / Traefik 加 HTTPS
```

#### 关闭对外 5432 端口（生产建议）

`docker-compose.yml` 默认把 PostgreSQL 5432 暴露到宿主机，方便本地连数据库排查。生产环境建议关掉：

```yaml
# docker-compose.yml
services:
  db:
    ports: []         # ← 注释或删除原 5432 行；不写 ports 即不对外
```

backend 容器仍可经容器网络访问 `db:5432`，无影响。

#### 系统服务化（开机自启）

`docker compose up -d` 加 `restart: unless-stopped` 已能自动重启。如要更严格的开机启动，写一份 systemd unit：

```ini
# /etc/systemd/system/aitest.service
[Unit]
Description=AITestPlatform
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/AITestPlatform
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now aitest
```

#### 资源约束

如服务器同时跑别的服务，给 backend 容器加资源上限（chromium 偶发吃内存）：

```yaml
# docker-compose.override.yml（与 docker-compose.yml 自动叠加）
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: "2.0"
          memory: 3G
```

### 方案 D：被测系统在公司内网（VPN 场景）

> **现象**：宿主机 `curl https://你的内网/login` HTTP=200，但 `docker exec backend curl ...` 直接 ConnectTimeout。
>
> **根因**：被测域名解析到 RFC1918 内网地址（如 `172.17.x.x`），而 macOS Docker Desktop / Windows WSL 的容器跑在独立的 Linux VM 里，**这个 VM 不共享宿主的 VPN 路由表**。Linux 原生 Docker 在 `network_mode: host` 下没这个问题。

提供两种解法：D-1 让容器借宿主机 VPN（最常用），D-2 让容器自己建 VPN（最干净）。

#### D-1：宿主机代理模式（macOS / Windows Docker Desktop）

让容器把所有"访问内网"的流量经一个**跑在宿主机上的 HTTP 代理**出去；该代理进程持有宿主机的 VPN 路由，自然能命中内网。

```
┌─ container ─┐    ┌─── macOS host ───┐     ┌─ 公司 VPN ─┐
│ chromium    │───>│ pproxy:8118      │────>│ utun ...   │───> 内网
│ httpx       │    │ (持有 utun 路由) │     └────────────┘
└─────────────┘    └──────────────────┘
   通过 host.docker.internal:8118
```

**步骤一：在宿主机起一个 HTTP 代理（任选其一）**

```bash
# 方案 1：pproxy（一行 pip，零配置，推荐）
pip install pproxy
pproxy -l http://0.0.0.0:8118 &

# 方案 2：mitmproxy（功能多，能抓包）
pip install mitmproxy
mitmdump --listen-host 0.0.0.0 --listen-port 8118 &

# 方案 3：tinyproxy（brew 装，配置简单）
brew install tinyproxy
cat >/tmp/tinyproxy.conf <<EOF
Listen 0.0.0.0
Port 8118
Allow 127.0.0.1
Allow 192.168.65.0/24
EOF
tinyproxy -c /tmp/tinyproxy.conf
```

**步骤二：宿主机自验证（一定要做）**

```bash
curl --proxy http://localhost:8118 -sSI https://你的内网域名/api/health
# 必须返回 200；否则代理本身就不通，下面没意义
```

**步骤三：启动 backend 时叠加 vpn override**

```bash
docker compose -f docker-compose.yml -f docker-compose.vpn.yml up -d backend
```

`docker-compose.vpn.yml` 自动注入：

```yaml
UI_HTTP_LOGIN_PROXY=http://host.docker.internal:8118    # backend 走 http_login 时的专用代理
UI_BROWSER_PROXY=http://host.docker.internal:8118       # chromium 启动时透传给 --proxy-server
HTTP_PROXY=http://host.docker.internal:8118             # backend 其它出口（含 LLM）也走这条
HTTPS_PROXY=http://host.docker.internal:8118
NO_PROXY=localhost,127.0.0.1,host.docker.internal,db,backend,frontend
```

> **关键坑 1**：`UI_HTTP_LOGIN_PROXY` 是必填项，不能只设 `HTTP_PROXY` —— backend 的 http_login 模块用 `httpx(trust_env=False)` 主动忽略 `HTTP_PROXY`（避免污染 LLM 调用），必须显式声明。
>
> **关键坑 2**：`UI_BROWSER_PROXY_BYPASS` 必须包含 `localhost,127.0.0.1,host.docker.internal,db,backend,frontend`，否则 chromium 经代理回访自身 / 数据库时会断。
>
> **关键坑 3**：split-tunnel VPN（公网不走 VPN）下，`HTTP_PROXY=` / `HTTPS_PROXY=` 这两行可能让 LLM 调用变慢甚至失败 —— 因为 LLM 在公网，反而被代理回旋。这种情况下：删掉 `docker-compose.vpn.yml` 里的 `HTTP_PROXY/HTTPS_PROXY`，只保留 `UI_HTTP_LOGIN_PROXY` + `UI_BROWSER_PROXY`。

**步骤四：容器内自验证**

```bash
docker compose exec backend python -c "
import httpx, time, os
url = 'https://你的内网域名/api/health'
t = time.time()
r = httpx.get(url, timeout=8, proxy=os.getenv('UI_HTTP_LOGIN_PROXY'), trust_env=False)
print('OK', r.status_code, 'in', round(time.time()-t,2), 's')
"
# 期望：OK 200 in 0.3 s
```

**切回非 VPN 模式**

```bash
docker compose up -d backend     # 不带 -f vpn 即可，env 自动清空
```

> Linux 原生 Docker 不需要 D-1，直接用 `network_mode: host` 即可（宿主和容器共享网络栈）。在 `docker-compose.yml` 加 `network_mode: host` 给 backend 即生效（同时 db 和 frontend 互通方式略变，详细配置自行评估）。

#### D-2：容器内 VPN sidecar 模式（不依赖宿主 VPN）

服务器场景或希望"容器自带 VPN，不依赖宿主 OS 配置"时的方案。把 VPN 客户端跑在一个独立容器里，让 backend 容器**完全使用 VPN 容器的网络栈**。

```
┌───── docker network ─────┐
│                          │
│  ┌──────── vpn ────────┐ │     ┌─ 公司 VPN 服务端 ─┐
│  │ wireguard / openvpn │─┼───>│  (.conf / .ovpn) │
│  └─────────────────────┘ │     └──────────────────┘
│           ▲              │
│ network_mode: container:vpn
│           │              │
│  ┌──── backend ─────┐    │
│  │ chromium / httpx │    │   ← 出方向流量被 vpn 容器接管
│  └──────────────────┘    │
└──────────────────────────┘
```

**步骤一：准备 VPN 配置**

得到管理员发的 `.conf`（WireGuard）或 `.ovpn`（OpenVPN）配置文件，放到 `vpn/` 目录。

**步骤二：在项目根目录新增 `docker-compose.sidecar-vpn.yml`**

WireGuard 版本（最简）：

```yaml
# docker-compose.sidecar-vpn.yml —— 与 docker-compose.yml 叠加使用
services:
  vpn:
    image: lscr.io/linuxserver/wireguard:latest
    cap_add:
      - NET_ADMIN
      - SYS_MODULE
    sysctls:
      - net.ipv4.conf.all.src_valid_mark=1
    volumes:
      - ./vpn:/config             # 把 .conf 放在 ./vpn/wg_confs/
      - /lib/modules:/lib/modules:ro
    environment:
      - PUID=1000
      - PGID=1000
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "wg", "show"]
      interval: 30s

  backend:
    network_mode: "service:vpn"   # ← 关键：完全共享 vpn 容器的网络命名空间
    depends_on:
      vpn:
        condition: service_started
      db:
        condition: service_healthy
    # 注意：当使用 network_mode: service:xxx 时，本服务自身不能再声明 ports。
    # backend 的 8000 端口要由 vpn 容器代为暴露：
    ports: !reset []
  
  vpn:
    ports:
      - "${BACKEND_PORT:-8000}:8000"   # backend 的 API 端口（宿主机端口随 .env 走）
      # 6080 不暴露（前端经容器网络反代）
```

> 注意：`network_mode: service:vpn` 让 backend 完全没有自己的网络栈，**它的 `ports`、`networks`、`extra_hosts` 都不能再写，要写在 vpn 容器上**。

OpenVPN 版本（用 `kylemanna/openvpn` 或 `dperson/openvpn-client`）：

```yaml
services:
  vpn:
    image: dperson/openvpn-client:latest
    cap_add: [NET_ADMIN]
    devices: ["/dev/net/tun"]
    volumes:
      - ./vpn/client.ovpn:/vpn/client.ovpn:ro
    command: -f "" -r 192.168.0.0/16 -r 10.0.0.0/8 -r 172.16.0.0/12   # 推送内网网段路由
    restart: unless-stopped
    ports:
      - "8000:8000"

  backend:
    network_mode: "service:vpn"
    ports: !reset []
    depends_on: [vpn, db]
```

**步骤三：启动**

```bash
docker compose -f docker-compose.yml -f docker-compose.sidecar-vpn.yml up -d
```

**步骤四：验证 VPN 隧道与连通性**

```bash
# 1. VPN 容器握手
docker compose logs vpn | tail
# WireGuard 看到 "interface created"；OpenVPN 看到 "Initialization Sequence Completed"

# 2. backend 容器（实际是 vpn 容器的网络栈）能否访问内网
docker compose exec backend curl -sS -o /dev/null -w 'HTTP=%{http_code}\n' \
    --max-time 8 https://你的内网域名/api/health
# 期望：HTTP=200
```

**取舍**

| 维度 | D-1 宿主机代理 | D-2 容器内 VPN |
|---|---|---|
| 适用平台 | macOS Docker Desktop、Windows WSL | Linux 原生 Docker |
| VPN 客户端在哪 | 宿主机 OS 已经连接 | 容器里跑 wireguard/openvpn-client |
| 是否需要 cap_add | 否 | 是（NET_ADMIN / SYS_MODULE / /dev/net/tun） |
| 容器走 VPN 范围 | 通过 `UI_*_PROXY` 精细控制 | 全部出方向流量都走 VPN |
| LLM 是否被影响 | 可控（只让 UI 部分走代理） | 默认全走，需要配 split-tunnel |
| 复杂度 | 低 | 中 |
| 推荐场景 | 个人开发联调内网应用 | 服务器长期运行、不依赖宿主 |

### 方案 E：GHCR 拉取预构建镜像（最快，3-5 分钟部署）⭐ 生产首次部署推荐

**适用场景**：服务器已装 Docker、希望跳过 5-10 分钟本地 build 的所有部署；首次部署、生产环境、CI/CD 自动化都强烈推荐这种方式。

GitHub Actions 已在仓库 push / tag 时自动构建并推送镜像到 GHCR（GitHub Container Registry），服务器只需 pull 即用，**无需 git clone 整个仓库**。

镜像地址（假设你的 GitHub 用户名是 `your-username`）：

```
ghcr.io/your-username/aitestplatform-backend:latest
ghcr.io/your-username/aitestplatform-frontend:latest
```

#### E-1：服务器首次部署（10 步照抄即可）

##### 步骤 1：装 Docker（一次性）

```bash
# Ubuntu 22.04+ / Debian 12 / CentOS 7+ / RHEL 9 通用
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker          # 让组权限立即生效（不需要重新登录）

# 验证
docker --version
docker compose version
```

##### 步骤 2：准备部署目录

```bash
mkdir -p ~/aitestplatform && cd ~/aitestplatform

# 下载部署所需的 2 个文件（不是整个仓库！）
curl -fsSL -o docker-compose.prod.yml \
  https://raw.githubusercontent.com/<your-username>/AITestPlatform/main/docker-compose.prod.yml

curl -fsSL -o .env.example \
  https://raw.githubusercontent.com/<your-username>/AITestPlatform/main/.env.example

cp .env.example .env
```

##### 步骤 3：编辑 `.env`（必填，少一个启动不了）

打开编辑器：

```bash
nano .env       # 或 vi .env / vim .env
```

**关键变量**（生产环境每一项都要改！）：

```bash
# ── GHCR 镜像源 ──
GHCR_OWNER=your-github-username     # 改成你的 GitHub 用户名（小写）
IMAGE_TAG=latest                     # 跟随 main 最新；或锁定到 v1.0.0

# ── 安全密钥（生产必随机化） ──
SECRET_KEY=<下面命令生成>
ENCRYPT_KEY=<下面命令生成>

# ── 强密码 ──
POSTGRES_PASSWORD=<强密码>
ADMIN_PASSWORD=<强密码>             # 首次登录后建议在前端再改一次

# ── 端口冲突时改（可选） ──
# FRONTEND_PORT=7080                 # 服务器 80 被占用 → 改非 80 端口
# BACKEND_PORT=7008                  # 服务器 8000 被占用 → 改非 8000 端口

# ── 调试（生产强烈建议保持 false） ──
DEBUG=false                          # true 会暴露 /docs Swagger UI
```

**生成密钥的两条命令**（复制粘贴即可执行，**`ENCRYPT_KEY` 务必备份**！）：

```bash
# 生成 SECRET_KEY（JWT 签名）
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))" >> .env

# 生成 ENCRYPT_KEY（物料 secret / API key 加密；丢了等于丢失所有 secret 数据）
python3 -c "from cryptography.fernet import Fernet; print('ENCRYPT_KEY=' + Fernet.generate_key().decode())" >> .env
```

服务器没有 python3 时，用 openssl 替代：

```bash
echo "SECRET_KEY=$(openssl rand -base64 48 | tr -d '\n')" >> .env
echo "ENCRYPT_KEY=$(openssl rand -base64 32 | head -c 44 | tr '+/' '-_')=" >> .env
```

##### 步骤 4：（仅 private 包需要）登录 GHCR

GitHub 上每个 GHCR 包默认是 **private**，需要先在 GitHub 上把包改成 public（推荐）或 docker login。

**推荐：把包改 public**（一次性操作）：

> GitHub → 你的头像 → Packages → 选中 `aitestplatform-backend` / `aitestplatform-frontend` → 右侧 `Package settings` → 滚到底 `Change visibility` → `Public`

如果坚持 private，则需要在服务器上登录：

```bash
# 1. 创建 GitHub PAT（个人访问令牌）
#    GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
#    权限勾选：read:packages
#    生成后复制 token（只显示一次）

# 2. 服务器上登录
echo <YOUR_PAT> | docker login ghcr.io -u <YOUR_GITHUB_USERNAME> --password-stdin
```

##### 步骤 5：拉镜像 + 启动

```bash
cd ~/aitestplatform

# 拉镜像（首次约 4-5 分钟，~4 GB；之后增量更新只 1-2 分钟）
docker compose -f docker-compose.prod.yml --env-file .env pull

# 启动（DB 迁移 + 创建 admin 自动完成）
docker compose -f docker-compose.prod.yml --env-file .env up -d

# 跟随 backend 日志确认就绪（看到 "Uvicorn running" 即可 Ctrl+C 退出）
docker compose -f docker-compose.prod.yml --env-file .env logs -f backend
```

##### 步骤 6：本机验证（在服务器上）

```bash
# 容器状态：db / backend / frontend 都应 Up
docker compose -f docker-compose.prod.yml --env-file .env ps

# 后端健康
curl --noproxy "*" http://localhost:${BACKEND_PORT:-8000}/api/health
# 期望：{"status":"ok","service":"AITestPlatform"}

# 前端
curl --noproxy "*" -I http://localhost:${FRONTEND_PORT:-80}
# 期望：HTTP/1.1 200 OK

# 前端 → 后端反代链路（这就是浏览器登录时的实际链路）
curl --noproxy "*" http://localhost:${FRONTEND_PORT:-80}/api/health
# 期望：{"status":"ok","service":"AITestPlatform"}
```

##### 步骤 7：开放云服务商防火墙端口（**关键，新手必踩坑**）

绝大多数云服务器（阿里云 / 腾讯云 / AWS / 华为云 / DigitalOcean 等）默认拦截入向流量。需要在云控制台**安全组 / 防火墙**里放行：

| 端口 | 用途 | 建议来源 |
|---|---|---|
| `${FRONTEND_PORT}`（默认 80） | 用户浏览器访问平台 | `0.0.0.0/0`（任意） |
| `${BACKEND_PORT}`（默认 8000） | 直接调 API（开发期可放，生产不建议公网开） | 你的办公网 IP |
| `22` (SSH) | 远程登录 | 你的办公网 IP |

> **阿里云**：ECS 控制台 → 实例 → 安全组 → 配置规则 → 添加入向规则
> **腾讯云**：CVM 控制台 → 实例 → 安全组 → 添加规则
> **AWS**：EC2 → 实例 → Security Groups → Inbound rules → Edit
> **华为云**：ECS → 安全组 → 入方向规则 → 添加规则

##### 步骤 8：浏览器访问

| 入口 | 地址 |
|---|---|
| **平台主入口** | `http://your-server-ip:${FRONTEND_PORT}`（默认 80 时不带端口直接 `http://your-server-ip`） |
| 后端 Swagger（仅 DEBUG=true） | `http://your-server-ip:${BACKEND_PORT}/docs` |

登录默认账号：`admin` / `<你 .env 设的 ADMIN_PASSWORD>` —— 首次登录后建议在「系统设置 → 用户管理」再改一次密码。

##### 步骤 9：（可选）开机自启 systemd unit

`docker-compose.prod.yml` 已自带 `restart: unless-stopped`，docker 守护进程启动时自动起容器。只要确保 docker 自身开机自启即可：

```bash
sudo systemctl enable docker
```

更严格的系统级服务化（可选）：

```bash
sudo tee /etc/systemd/system/aitest.service > /dev/null <<EOF
[Unit]
Description=AITestPlatform
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$HOME/aitestplatform
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml --env-file .env up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml --env-file .env down

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now aitest
```

##### 步骤 10：（可选）HTTPS 反代（生产域名场景）

最简方案用 [Caddy](https://caddyserver.com/)（自动 Let's Encrypt 证书）：

```bash
# 1. 装 Caddy
sudo apt install -y caddy            # Debian/Ubuntu
# CentOS/RHEL：sudo dnf install caddy

# 2. 配置反代
sudo tee /etc/caddy/Caddyfile > /dev/null <<EOF
your-domain.com {
    reverse_proxy localhost:${FRONTEND_PORT:-80}
}
EOF

sudo systemctl restart caddy
```

→ 浏览器访问 `https://your-domain.com`（Caddy 自动申请证书 + 续签）。

**前提**：
- 域名 A 记录已指向服务器公网 IP
- 防火墙放行 80 + 443 端口（80 用于 ACME challenge）

#### E-2：服务器日常升级（已有部署 → 拉新镜像）

每次本地 `git push origin main` 后，GitHub Actions 自动构建新镜像并打 `:latest` tag。服务器升级只需 3 行命令：

```bash
cd ~/aitestplatform

# 拉新镜像（只下变化的层，2-5 分钟）
docker compose -f docker-compose.prod.yml --env-file .env pull

# Recreate 受影响的容器（数据 volume 全部保留，无丢失风险）
docker compose -f docker-compose.prod.yml --env-file .env up -d

# 验证
curl --noproxy "*" http://localhost:${BACKEND_PORT:-8000}/api/health
```

升级到指定正式版本（`v1.2.0` 等）：

```bash
# 改 .env 锁定版本
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.2.0/' .env

# 拉 + 重启
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

#### E-3：回滚到旧版本

```bash
# 假设当前 v1.2.0 出 bug，回滚到 v1.1.0
sed -i 's/^IMAGE_TAG=.*/IMAGE_TAG=v1.1.0/' .env
docker compose -f docker-compose.prod.yml --env-file .env pull
docker compose -f docker-compose.prod.yml --env-file .env up -d
```

> ⚠️ **跨数据库 schema 版本不能简单回滚**！如果新版本跑过 alembic 迁移，旧版本镜像启动时模型与表结构不匹配，会报错。需要先 `pg_dump` 备份当前数据，再 `alembic downgrade <revision>` 把表结构回滚到匹配的版本。详见 [`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md)。

#### E-4：首次部署常见问题

| 现象 | 根因 | 解法 |
|---|---|---|
| `pull` 报 `denied: requested access to the resource is denied` | GHCR 镜像是 private 但服务器没登录 | 步骤 4 登录，或把 GHCR 包改 public（推荐） |
| `pull` 报 `manifest unknown` 或 `not found` | `GHCR_OWNER` 拼错 / GHA 还没构建完 | 检查 `.env` 的 `GHCR_OWNER` 是否小写；查 GHA 进度：`https://github.com/<owner>/AITestPlatform/actions` |
| `pull` 卡在 50% 速度极慢 | GHCR 国内服务器拉取慢 | 配 docker 镜像加速器（dockerproxy / ACR 同步），见 [`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md) §镜像加速 |
| `Bind for 0.0.0.0:80 failed: port is already allocated` | 服务器 80 已被其它项目占用 | `.env` 加 `FRONTEND_PORT=7080`，重新 up |
| 三个容器全 `Up` 但浏览器 `连接被拒绝 / 超时` | 云防火墙 / 安全组没放行端口 | 步骤 7 在云控制台放行 |
| 浏览器登录页一直转圈不响应 | 前端能开但 `/api/*` 反代不通；通常是 backend 容器没起来 | `docker compose ... logs backend` 看错误；常见是 `.env` 缺 `SECRET_KEY` / `ENCRYPT_KEY` |
| `docker compose pull` 报 `KeyError: 'ContainerConfig'` | docker compose v1（已停止维护） | 升级到 docker compose v2：`docker compose version` 应输出 v2.x |

更多细节（镜像 tag 策略 / ARM 跨架构 / ACR 加速 / GHA 工作流配置 / 自定义 push 触发等）：→ **[`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md)**

---

## ⚙️ 配置详解

`.env`（基于 `.env.example`）所有变量按域分组：

### 数据库

```bash
POSTGRES_HOST=localhost              # 本地开发；docker 部署不要改（compose 自动覆盖）
POSTGRES_PORT=5432
POSTGRES_USER=aitest
POSTGRES_PASSWORD=aitest123          # 生产必改
POSTGRES_DB=aitest_platform
```

### 后端

```bash
SECRET_KEY=...                       # JWT 签名；生产必随机化（>=32 字节）
ENCRYPT_KEY=...                      # Fernet 32-byte url-safe base64 key；用于 secret 物料 / API key 加密
DEBUG=false                          # 生产 false：关闭 /docs，并禁用 LLM trace
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000                    # 宿主机映射端口（用户访问端口）；容器内 uvicorn 始终 8000
                                     # 服务器 8000 被占用时：BACKEND_PORT=7008
```

> **`ENCRYPT_KEY` 跨环境必须一致**。一旦换掉，所有已加密的物料 secret / LLM provider API key 将无法解密。生成命令：
> ```bash
> python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
> ```

### 初始管理员

```bash
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin123              # 生产必改
ADMIN_EMAIL=admin@aitest.local
```

> 仅在 `entrypoint.sh` 第一次运行（DB 中无 admin）时创建。改这些变量再启动**不会**修改已有用户密码 —— 改密码要从前端登录后操作。

### UI 自动化（二期）

```bash
# 物料文件 / 介质 / state 路径与上限
UI_STATE_DIR=uploads/ui_state
TEST_DATA_UPLOAD_DIR=uploads/test-data
TEST_DATA_MAX_FILE_SIZE=52428800     # 50 MB
UI_ARTIFACTS_DIR=uploads/ui_artifacts
UI_STEP_SCREENSHOT_TYPE=png          # png 清晰大 / jpeg 小失真

# Snapshot 裁剪（大 → LLM 看更全；小 → 省 token）
UI_SNAPSHOT_MAX_CHARS=3000
UI_SNAPSHOT_DIFF_CONTEXT=2

# 内网代理（VPN 场景；详见 §部署方式 D-1）
UI_HTTP_LOGIN_PROXY=                 # 仅 http_login 走它；空 = 关闭
UI_BROWSER_PROXY=                    # chromium 启动时透传给 --proxy-server
UI_BROWSER_PROXY_BYPASS=localhost,127.0.0.1,host.docker.internal,db,backend,frontend
SKILL_HTTP_PROXY=                    # 三期 Skill 包 http_get_json/http_post_json 走它；空 = 回退到 UI_HTTP_LOGIN_PROXY → HTTP_PROXY

# noVNC 远程观察
UI_NOVNC_ENABLED=true                # false 仅启 Xvfb（headed 仍可跑，但看不到画面）
UI_NOVNC_PORT=6080                   # 容器内端口；前端 nginx /novnc/ 反代过来
UI_VNC_DISPLAY=:99                   # Xvfb 显示器编号；改这条同步影响 chromium DISPLAY
```

### 清理 cron（Task 11.2）

```bash
CLEANUP_INTERVAL_HOURS=24            # 0 = 关闭周期清理（仅保留手动触发）
CLEANUP_RUN_ON_STARTUP=false         # 启动时是否立即跑一次

UI_MEDIA_RETENTION_DAYS=30           # 视频 / trace / 截图 / step screenshot
UI_STATE_RETENTION_DAYS=7            # 孤立 storage_state 文件
UI_SNAPSHOT_RETENTION_DAYS=7         # step 大字段（仅清空字段，行还在）
TEST_DATA_FILE_RETENTION_DAYS=90     # 物料 file 类型的孤立物理文件
TEST_DATA_AUDIT_RETENTION_DAYS=180   # 审计日志（预留）
```

### 前端

`.env.example` 里的 `VITE_API_BASE_URL` 是历史残留，**当前版本前端代码并不读它**：

- 本地开发模式：`vite.config.ts` 的 `server.proxy["/api"]` 把 `/api/*` 反代到 `http://localhost:8000`
  - 若本地把 `BACKEND_PORT` 改成了别的端口，需要同步修改 `vite.config.ts` 的 target，
    或临时把 `vite.config.ts` 改成读 env：`target: process.env.VITE_API_BASE_URL || 'http://localhost:8000'`
- 容器部署模式：`frontend/nginx.conf` 的 `location /api/` 反代到 `http://backend:8000/api/`
  - 这是 docker 内部网络，**不受 `BACKEND_PORT`（宿主机端口）影响**，无需修改

所以前端只调用相对路径 `/api/...`，不需要任何 env。

---

## 📞 交流与反馈

- **GitHub Issues**：Bug / 功能请求 / 部署问题 → 直接提 issue
- **GitHub Discussions**：架构讨论 / 用法咨询 / 经验分享
- **PR 欢迎**：bug 修复 / 文档改进 / 截图补充 / 国际化等都欢迎

## 📷 微信交流群 / QQ 群暂未建立。如果项目积累一定用户后会在此处补充入群方式，下方添加作者，来源请备注 gitHub。
![项目截图](./image/wechat.jpg)


## 支持本项目‌，您的鼓励是对作者更新最大的动力！
本项目通过开源代码免费为大家提供服务。然而，其持续的开发、维护和服务器运营需要投入大量时间和资源。
![项目截图](./image/pay.jpg)


---

## 📚 进一步阅读

| 文档 | 内容 |
|---|---|
| [`docs/DEPLOYMENT_GHCR.md`](docs/DEPLOYMENT_GHCR.md) | GHCR 镜像构建 / 拉取部署完整教程 |
| [`docs/PHASE3_DOCKER_VALIDATION.md`](docs/PHASE3_DOCKER_VALIDATION.md) | 三期 13.4-13.8 本地 Docker 启动与功能验收清单 |

---

## 🙏 致谢

本项目基于以下优秀开源项目构建，致谢：

- [FastAPI](https://fastapi.tiangolo.com/) — 现代异步 Python web 框架
- [Vue.js](https://vuejs.org/) — 渐进式 JavaScript 框架
- [Naive UI](https://www.naiveui.com/) — Vue 3 组件库（轻量、TS 原生）
- [SQLAlchemy](https://www.sqlalchemy.org/) + [Alembic](https://alembic.sqlalchemy.org/) — Python ORM 与迁移
- [Playwright](https://playwright.dev/) + [`@playwright/mcp`](https://github.com/microsoft/playwright-mcp) — 浏览器自动化与 MCP 协议
- [OpenAI Python SDK](https://github.com/openai/openai-python) — LLM 调用
- [uv](https://github.com/astral-sh/uv) — 极速 Python 包管理
- [pnpm](https://pnpm.io/) — 高效 Node.js 包管理
- [noVNC](https://novnc.com/) + [websockify](https://github.com/novnc/websockify) — 浏览器内 VNC 客户端
- [PostgreSQL](https://www.postgresql.org/) — 可靠成熟的关系型数据库

---

## 📄 License

本项目采用 [MIT 许可证](LICENSE)。

---

<div align="center">

**如果这个项目对你有帮助，请点击 ⭐ Star 支持一下！**

Made with ❤️ by AITestPlatform Contributors

</div>

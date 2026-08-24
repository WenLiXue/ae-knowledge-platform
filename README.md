# AE Knowledge Platform

面向产品团队的知识智能平台，V1 聚焦知识查询与文档入库治理。

## 当前状态

仓库已完成初始化，并已建立 FastAPI 后端与 React 前端的最小可运行骨架；业务功能尚未开始接入。

当前需求、概要设计、详细设计与原型资料仍以分析工作区为准：

`C:\Users\23882\Documents\Codex\2026-08-12\v1-context-md-seg-pm-pmm`

## 计划技术栈

- 后端：Python / FastAPI
- 前端：React / TypeScript / Material UI
- 部署形态：公司内网单体应用
- 大模型：通过 HTTP 接入，可配置本地或外部服务

## V1 重点

- 飞书文档选择与导入
- 文档解析、去重、分类 Agent 处理
- 知识查询、产品/版本/文档类型筛选
- 混合检索、答案与来源依据展示
- 对话持久化与基础管理能力

## 本地启动（骨架）

后端：

```powershell
cd D:\Projects\ae-knowledge-platform\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

前端：

```powershell
cd D:\Projects\ae-knowledge-platform\frontend
npm install
npm run dev
```

后端健康检查地址：`http://127.0.0.1:8000/health`

## 现有工程边界

`D:\Projects\ae-seg` 是已有业务工程。本仓库独立建设，不直接覆盖或改造其代码。

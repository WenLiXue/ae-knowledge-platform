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

## 容器化部署

完整部署包含 Nginx、FastAPI、Worker 和带 pgvector 扩展的 PostgreSQL。向量和全文检索数据统一落在 PostgreSQL；Nginx 对外提供统一入口：

```bash
cp deploy/.env.prod.example .env
# 编辑根目录 .env，至少修改 POSTGRES_PASSWORD、TOKEN_ENC_KEY、AUDIT_HMAC_KEY
# 如需真实飞书登录，再在 backend/.env 填写 FEISHU_PROVIDER、FEISHU_APP_ID、FEISHU_APP_SECRET
docker compose -f docker-compose.prod.yml up -d --build
```

访问 `http://localhost`，健康检查为 `http://localhost/health`。前端使用同源 `/api`，Nginx 会将 API、登录回调和 SSE 请求转发给后端；数据库和对象存储数据都位于项目目录下的 `data/`。

停止服务：

```bash
docker compose -f docker-compose.prod.yml down
```

## Jenkins + GitLab push 自动 CI/CD

仓库根目录的 `Jenkinsfile` 已配置为：GitLab push webhook 触发 → 检查 Compose 配置 → 构建前后端镜像 →（可选）推送镜像 → 在这台部署机执行 `docker compose up -d` → 等待后端 `/health` 通过。流水线使用 commit short SHA 作为镜像标签，并禁止并发部署。GitLab、Jenkins 和部署服务都可以只放在内网，不需要 GitHub 或公网入口。

部署机需要安装 Git、Docker Engine（Jenkins 用户能访问 `/var/run/docker.sock`）和 Docker Compose v2。将当前机器注册为 Jenkins 节点，并设置节点 label 为 `ae-deploy-host`；Jenkinsfile 已固定使用这个 label，保证构建和部署使用本机 Docker。Jenkins 运行在容器中时，需要把 Docker socket 和 Docker CLI/Compose 一并提供给 Jenkins 容器。

Ubuntu 主机上若 Jenkins 以系统服务运行，通常需要将它加入 Docker 用户组，并让它能够读取外置密钥文件：

```bash
sudo bash deploy/install-jenkins-ubuntu.sh
```

该脚本会安装 Docker、Compose、Java 21 和 Jenkins，并完成 Docker 权限及生产 `.env` 目录初始化。
如果机器无法访问 Docker 官方源，脚本会自动尝试 Ubuntu 软件源的 `docker.io` 和 `docker-compose-v2`；如果 Jenkins 官方源也无法访问，可先把 Jenkins `.deb` 传到本机，再执行 `sudo env JENKINS_DEB_PATH=/path/to/jenkins.deb bash deploy/install-jenkins-ubuntu.sh`。

安装时可通过环境变量修改 Jenkins 端口，例如：`sudo env JENKINS_HTTP_PORT=8090 bash deploy/install-jenkins-ubuntu.sh`。默认端口为 `8080`。

随后编辑 `/opt/ae-knowledge-platform/.env` 中的生产配置。若 Jenkins 使用容器运行，请用容器内 Jenkins 用户可读的路径替换上面的外置文件路径。

首次配置：

1. Jenkins 安装并启用 `GitLab Plugin`、`Git Plugin` 和 Pipeline 相关插件。在 Jenkins 新建 Pipeline 任务，选择“Pipeline script from SCM”，SCM 选择 Git，仓库填你的内网 GitLab 地址（例如 `http://gitlab.intra/group/ae-knowledge-platform.git`），分支填 `*/main`，脚本路径填 `Jenkinsfile`。私有仓库需要配置 GitLab SSH key 或 PAT 凭据。
2. 在任务的 Build Triggers 中启用 `Build when a change is pushed to GitLab`，勾选 Push Events，分支过滤设为 `main`，生成或填写一个 webhook Secret Token（不要写入仓库）。在 GitLab 项目 `Settings → Webhooks` 新建 webhook：URL 填 `http://<Jenkins内网地址>/project/<Jenkins任务名>`，Secret Token 填同一个值，触发事件选择 `Push events`，分支过滤可填 `main`。点击 GitLab 的 `Test` 验证返回 200。
3. 在 Jenkins 节点准备生产 `.env`，权限设为 `600`。推荐将它放在工作区外，例如 `/opt/ae-knowledge-platform/.env`，并将需要注入容器的后端配置（包括真实飞书凭据）一并写入；首次手工构建时把 `DEPLOY_ENV_FILE` 参数设为该绝对路径。流水线会通过 Compose 直接读取，不会把密钥复制到工作区。留空时使用工作区内的 `.env`。不要把生产密钥提交到 Git。
4. 手工构建一次确认 Docker 权限、端口和密钥配置均正常；之后每次 `git push origin main` 都会自动部署。

内网连通性要求：GitLab 服务器必须能访问 Jenkins 的 webhook 地址，Jenkins 节点必须能访问 GitLab 仓库和所需的镜像/Python/Node 基础镜像源。若 Jenkins 只监听 `127.0.0.1`，GitLab 无法回调；应监听内网网卡或通过内网反向代理暴露。

流水线参数：

- `IMAGE_REGISTRY`：镜像仓库前缀；本机部署可保持默认的 `ae-knowledge`，需要推送到内网 Harbor 或 GitLab Container Registry 时改为对应地址。
- `IMAGE_TAG`：镜像标签，留空则使用 Git commit short SHA。
- `PUSH_IMAGES`：是否推送镜像，默认关闭；打开前先在 Jenkins 节点执行目标仓库 `docker login`。
- `DEPLOY`：是否更新本机服务，默认开启；只构建/验证时可关闭。
- `DEPLOY_ENV_FILE`：生产 `.env` 的绝对路径，留空使用工作区 `.env`。

查看部署状态和日志：

```bash
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend worker frontend
```

生产环境的任务队列支持横向扩展 Worker。任务通过 PostgreSQL 任务表和
`FOR UPDATE SKIP LOCKED` 分摊，同一任务只会被一个实例持有租约。扩容时不要设置
固定的 `WORKER_ID`，Worker 会自动使用容器 hostname 生成唯一标识：

```bash
docker compose -f docker-compose.prod.yml up -d --scale worker=3 worker
docker compose -f docker-compose.prod.yml ps worker
```

缩容或升级时可重新执行同一命令调整副本数，例如 `--scale worker=1`。正在执行的任务
由租约保护；实例异常退出后，租约过期会被其他 Worker 自动回收并重试。

## 现有工程边界

`D:\Projects\ae-seg` 是已有业务工程。本仓库独立建设，不直接覆盖或改造其代码。

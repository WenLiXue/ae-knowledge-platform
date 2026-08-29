pipeline {
    // 当前 Jenkins 仅配置一台可执行节点，使用该节点运行构建和部署。
    agent any

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timestamps()
        timeout(time: 45, unit: 'MINUTES')
    }

    // GitLab push webhook 会调用这个流水线；也可在 Jenkins 页面手工构建。
    // 需要安装 Jenkins GitLab Plugin，并在任务中配置 webhook secret token。
    triggers {
        gitlab(
            triggerOnPush: true,
            triggerOnMergeRequest: false,
            branchFilterType: 'NameBasedFilter',
            includeBranchesSpec: 'main'
        )
    }

    parameters {
        string(name: 'IMAGE_REGISTRY', defaultValue: 'ae-knowledge', description: '镜像仓库前缀；例如 harbor.example.com/ae/knowledge')
        string(name: 'IMAGE_TAG', defaultValue: '', description: '留空时使用 Git commit short SHA')
        booleanParam(name: 'PUSH_IMAGES', defaultValue: false, description: '是否推送镜像到仓库')
        booleanParam(name: 'DEPLOY', defaultValue: true, description: '构建成功后在本机用生产 Compose 更新服务')
        string(name: 'DEPLOY_ENV_FILE', defaultValue: '', description: '可选：生产 .env 的绝对路径；留空时使用 DEPLOY_DIR/.env')
        string(name: 'DEPLOY_DIR', defaultValue: '/opt/ae-knowledge-platform', description: '生产 Compose 项目目录；用于持久化数据和固定服务项目名')
    }

    environment {
        DOCKER_BUILDKIT = '1'
        COMPOSE_DOCKER_CLI_BUILD = '1'
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Static checks') {
            steps {
                sh 'git diff --check'
            }
        }

        stage('Validate deployment config') {
            steps {
                // 使用非生产占位值解析完整编排，避免在 CI 中读取生产密钥。
                sh '''
                    POSTGRES_PASSWORD=ci-password \\
                    TOKEN_ENC_KEY=ZGV2LW9ubHktdG9rZW4tZW5jLWtleS0zMi1ieXRlcyE= \\
                    AUDIT_HMAC_KEY=ci-audit \\
                    docker compose -f docker-compose.prod.yml config --quiet
                '''
            }
        }

        stage('Build images') {
            steps {
                script {
                    def registry = params.IMAGE_REGISTRY?.trim()
                    def tag = params.IMAGE_TAG?.trim() ?: sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    if (!(registry ==~ /^[A-Za-z0-9][A-Za-z0-9._\/-]*$/)) {
                        error('IMAGE_REGISTRY 只能包含镜像仓库允许的字符')
                    }
                    if (!(tag ==~ /^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/)) {
                        error('IMAGE_TAG 不是合法的 Docker tag')
                    }
                    env.BUILD_TAG_VALUE = tag
                    env.BACKEND_IMAGE = "${registry}/backend"
                    env.FRONTEND_IMAGE = "${registry}/frontend"
                }
                sh '''
                    # Compose 在构建阶段也会解析 postgres 的必填变量；这里仅使用 CI 占位值，
                    # 不读取或覆盖生产密钥。部署阶段再通过 DEPLOY_ENV_FILE 注入真实配置。
                    export POSTGRES_PASSWORD=ci-password
                    export TOKEN_ENC_KEY=ZGV2LW9ubHktdG9rZW4tZW5jLWtleS0zMi1ieXRlcyE=
                    export AUDIT_HMAC_KEY=ci-audit
                    export IMAGE_TAG="$BUILD_TAG_VALUE"
                    export BACKEND_IMAGE="$BACKEND_IMAGE"
                    export FRONTEND_IMAGE="$FRONTEND_IMAGE"
                    docker compose -f docker-compose.prod.yml build backend frontend
                '''
            }
        }

        stage('Push images') {
            when { expression { return params.PUSH_IMAGES } }
            steps {
                sh "docker push ${params.IMAGE_REGISTRY}/backend:${env.BUILD_TAG_VALUE}"
                sh "docker push ${params.IMAGE_REGISTRY}/frontend:${env.BUILD_TAG_VALUE}"
            }
        }

        stage('Deploy on this host') {
            when { expression { return params.DEPLOY } }
            steps {
                sh '''
                    set -eu

                    # 生产密钥和持久化数据放在固定部署目录，不使用 Jenkins workspace。
                    export DEPLOY_DIR_VALUE="${DEPLOY_DIR:-/opt/ae-knowledge-platform}"
                    export APP_ENV_FILE="${DEPLOY_ENV_FILE:-$DEPLOY_DIR_VALUE/.env}"
                    test -d "$DEPLOY_DIR_VALUE" || {
                        echo "生产 Compose 目录不存在：$DEPLOY_DIR_VALUE" >&2
                        exit 1
                    }
                    test -r "$APP_ENV_FILE" || {
                        echo '缺少生产 .env：请配置 DEPLOY_ENV_FILE，或放在 DEPLOY_DIR 下' >&2
                        exit 1
                    }

                    mkdir -p "$DEPLOY_DIR_VALUE"/data/postgres "$DEPLOY_DIR_VALUE"/data/storage "$DEPLOY_DIR_VALUE"/data/exports \
                        "$DEPLOY_DIR_VALUE"/data/logs/backend "$DEPLOY_DIR_VALUE"/data/logs/worker "$DEPLOY_DIR_VALUE"/data/logs/frontend
                    export IMAGE_TAG="$BUILD_TAG_VALUE"
                    export BACKEND_IMAGE="$BACKEND_IMAGE"
                    export FRONTEND_IMAGE="$FRONTEND_IMAGE"
                    export COMPOSE_PROJECT_NAME=ae-knowledge-platform
                    COMPOSE_ARGS="--project-directory $DEPLOY_DIR_VALUE --env-file $APP_ENV_FILE -f $WORKSPACE/docker-compose.prod.yml"
                    docker compose $COMPOSE_ARGS up -d --remove-orphans

                    # 等待迁移和 FastAPI 启动完成；失败时打印服务日志方便定位。
                    ready=0
                    for attempt in $(seq 1 30); do
                        if docker compose $COMPOSE_ARGS exec -T backend \\
                            python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"; then
                            ready=1
                            break
                        fi
                        sleep 2
                    done
                    if [ "$ready" -ne 1 ]; then
                        docker compose $COMPOSE_ARGS ps
                        docker compose $COMPOSE_ARGS logs --tail=120 backend worker
                        exit 1
                    fi
                    worker_total=$(docker compose $COMPOSE_ARGS ps -a -q worker | wc -l)
                    worker_running=$(docker compose $COMPOSE_ARGS ps -q worker | wc -l)
                    if [ "$worker_total" -eq 0 ] || [ "$worker_running" -ne "$worker_total" ]; then
                        echo "worker 服务未全部运行：$worker_running/$worker_total" >&2
                        docker compose $COMPOSE_ARGS ps
                        docker compose $COMPOSE_ARGS logs --tail=120 worker
                        exit 1
                    fi
                    docker compose $COMPOSE_ARGS ps
                '''
            }
        }
    }
}

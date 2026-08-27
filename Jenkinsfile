pipeline {
    agent any

    parameters {
        string(name: 'IMAGE_REGISTRY', defaultValue: 'registry.example.com/ae-knowledge', description: '镜像仓库前缀')
        string(name: 'IMAGE_TAG', defaultValue: '', description: '留空时使用 Git commit short SHA')
        booleanParam(name: 'PUSH_IMAGES', defaultValue: false, description: '是否推送镜像到仓库')
    }

    environment { DOCKER_BUILDKIT = '1' }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Validate deployment config') {
            steps {
                // 使用非生产占位值解析完整编排，确保 pgvector Compose 配置有效。
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
                    env.BUILD_TAG_VALUE = params.IMAGE_TAG?.trim() ?: sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    sh "docker build -f backend/Dockerfile -t ${params.IMAGE_REGISTRY}/backend:${env.BUILD_TAG_VALUE} ."
                    sh "docker build -f frontend/Dockerfile -t ${params.IMAGE_REGISTRY}/frontend:${env.BUILD_TAG_VALUE} ."
                }
            }
        }

        stage('Push images') {
            when { expression { return params.PUSH_IMAGES } }
            steps {
                // Jenkins 节点需预先完成 docker login，或在此处接入 credentialsId。
                sh "docker push ${params.IMAGE_REGISTRY}/backend:${env.BUILD_TAG_VALUE}"
                sh "docker push ${params.IMAGE_REGISTRY}/frontend:${env.BUILD_TAG_VALUE}"
            }
        }
    }

    post {
        always { sh 'docker image prune -f || true' }
    }
}

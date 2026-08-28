#!/usr/bin/env bash

# 在 Ubuntu 22.04/24.04 部署机上安装 Docker、Compose、Java 21 和 Jenkins。
# 用法：sudo bash deploy/install-jenkins-ubuntu.sh

set -Eeuo pipefail

if [[ "${EUID}" -ne 0 ]]; then
    echo "请使用 root 权限运行：sudo bash deploy/install-jenkins-ubuntu.sh" >&2
    exit 1
fi

if [[ ! -r /etc/os-release ]]; then
    echo "无法识别当前 Linux 发行版。" >&2
    exit 1
fi

# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "此脚本只支持 Ubuntu，当前系统为：${PRETTY_NAME:-unknown}" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
ENV_DIR="${AE_DEPLOY_CONFIG_DIR:-/opt/ae-knowledge-platform}"
ENV_FILE="${ENV_DIR}/.env"
JENKINS_HTTP_PORT="${JENKINS_HTTP_PORT:-8080}"

if [[ ! "${JENKINS_HTTP_PORT}" =~ ^[0-9]+$ ]] || (( JENKINS_HTTP_PORT < 1 || JENKINS_HTTP_PORT > 65535 )); then
    echo "JENKINS_HTTP_PORT 必须是 1-65535 之间的端口号。" >&2
    exit 1
fi

echo "==> 安装基础依赖和 Java 21"
apt-get update
apt-get install -y ca-certificates curl fontconfig openjdk-21-jre

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "==> 已检测到 Docker 和 Compose，跳过 Docker 安装"
else
    echo "==> 配置 Docker 官方 apt 源"
    install -m 0755 -d /etc/apt/keyrings
    if ! curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        -o /etc/apt/keyrings/docker.asc; then
        echo "无法访问 download.docker.com，尝试使用 Ubuntu 软件源安装 Docker。"
        apt-get update
        apt-get install -y docker.io docker-compose-v2
    else
        chmod a+r /etc/apt/keyrings/docker.asc

        cat > /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-${VERSION_CODENAME}}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

        apt-get update
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    fi
fi
systemctl enable --now docker

if dpkg-query -W -f='${Status}' jenkins 2>/dev/null | grep -q 'install ok installed'; then
    echo "==> 已检测到 Jenkins，跳过 Jenkins 安装"
else
    echo "==> 配置 Jenkins LTS apt 源"
    install -m 0755 -d /etc/apt/keyrings
    JENKINS_DEB_PATH="${JENKINS_DEB_PATH:-}"
    if [[ -n "${JENKINS_DEB_PATH}" ]]; then
        test -f "${JENKINS_DEB_PATH}" || {
            echo "JENKINS_DEB_PATH 文件不存在：${JENKINS_DEB_PATH}" >&2
            exit 1
        }
        apt-get install -y "${JENKINS_DEB_PATH}"
    elif curl -fsSL https://pkg.jenkins.io/debian-stable/jenkins.io-2026.key \
        -o /etc/apt/keyrings/jenkins-keyring.asc; then
        chmod a+r /etc/apt/keyrings/jenkins-keyring.asc

        cat > /etc/apt/sources.list.d/jenkins.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/
EOF

        apt-get update
        apt-get install -y jenkins
    else
        echo "无法访问 pkg.jenkins.io，无法自动下载 Jenkins。" >&2
        echo "请在可访问 Jenkins 仓库的机器下载 .deb 后传到本机，再执行：" >&2
        echo "sudo env JENKINS_DEB_PATH=/path/to/jenkins.deb bash deploy/install-jenkins-ubuntu.sh" >&2
        exit 1
    fi
fi

if [[ "${JENKINS_HTTP_PORT}" != "8080" ]]; then
    echo "==> 配置 Jenkins HTTP 端口：${JENKINS_HTTP_PORT}"
    install -d -m 0755 /etc/systemd/system/jenkins.service.d
    cat > /etc/systemd/system/jenkins.service.d/port.conf <<EOF
[Service]
Environment="JENKINS_PORT=${JENKINS_HTTP_PORT}"
EOF
    systemctl daemon-reload
fi
systemctl enable --now jenkins

echo "==> 授予 Jenkins 使用本机 Docker 的权限"
usermod -aG docker jenkins
systemctl restart jenkins

echo "==> 准备生产环境文件"
install -d -o jenkins -g jenkins -m 0700 "${ENV_DIR}"
if [[ ! -e "${ENV_FILE}" ]]; then
    install -o jenkins -g jenkins -m 0600 \
        "${REPO_ROOT}/deploy/.env.prod.example" "${ENV_FILE}"
    echo "已创建 ${ENV_FILE}，请修改其中的生产密钥和地址。"
else
    chmod 0600 "${ENV_FILE}"
    chown jenkins:jenkins "${ENV_FILE}"
    echo "保留已有 ${ENV_FILE}，未覆盖生产配置。"
fi

echo
echo "安装完成。版本信息："
docker --version
docker compose version
java -version 2>&1 | head -1
systemctl --no-pager --full status jenkins | sed -n '1,12p'

echo
echo "Jenkins 初始密码："
cat /var/lib/jenkins/secrets/initialAdminPassword

echo
echo "下一步："
echo "1. 浏览器访问 http://<本机内网IP>:${JENKINS_HTTP_PORT} 完成 Jenkins 初始化。"
echo "2. 给当前 Jenkins 节点添加 label：ae-deploy-host。"
echo "3. Jenkins 任务参数 DEPLOY_ENV_FILE 设置为：${ENV_FILE}"
echo "4. 安装 GitLab Plugin，并配置 GitLab Webhook。"
echo
echo "验证 Jenkins Docker 权限："
runuser -u jenkins -- docker version >/dev/null
runuser -u jenkins -- docker compose version

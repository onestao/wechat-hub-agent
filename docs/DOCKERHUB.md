# DockerHub 发布说明

项目服务镜像用于运行：

- `wechat-memory-sync`
- `wechat-ai-memory`
- `wechat-agent-console`

它不包含：

- 微信登录数据
- 微信数据库
- 解密 key
- 运行记忆库
- 模型 API Key
- Tavily Key

这些私有数据都来自部署机器的 `.env`、`config/`、`runtime/`。

## 登录 DockerHub

```bash
docker login
```

如果镜像名不是默认的 `xiaoguiwucan/linux-wechat-agent`，先确定你的 DockerHub 用户名和仓库名，例如：

```text
docker.io/你的用户名/linux-wechat-agent
```

## 构建并推送

默认版本来自 `VERSION` 文件：

```bash
./scripts/publish-dockerhub.sh docker.io/xiaoguiwucan/linux-wechat-agent
```

指定版本：

```bash
./scripts/publish-dockerhub.sh docker.io/xiaoguiwucan/linux-wechat-agent 0.2.0
```

脚本会推送：

```text
docker.io/xiaoguiwucan/linux-wechat-agent:0.2.0
docker.io/xiaoguiwucan/linux-wechat-agent:latest
```

## 多架构发布

如果需要同时发布 amd64 和 arm64，可改用 buildx：

```bash
docker buildx create --use --name wechatagent-builder
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t docker.io/xiaoguiwucan/linux-wechat-agent:0.2.0 \
  -t docker.io/xiaoguiwucan/linux-wechat-agent:latest \
  --push .
```

注意：项目服务镜像可以多架构，但 `wechat-selkies` 微信 GUI 镜像是否能在对应架构运行，取决于上游镜像。

## 部署机器如何使用镜像

`.env` 中配置：

```env
WECHAT_AGENT_IMAGE=docker.io/xiaoguiwucan/linux-wechat-agent:latest
```

启动：

```bash
docker compose pull
docker compose up -d
```

升级：

```bash
./scripts/backup.sh
docker compose pull
docker compose up -d
```

## DockerHub 页面建议描述

可在 DockerHub 仓库描述中写：

```text
WeChatAgent packages Linux WeChat GUI automation, read-only message sync, long-term memory, AI auto reply, skill management, image understanding, meme sending, web search, and an agent console into a Docker Compose deployment.

Source and deployment guide:
https://github.com/xiaoguiwucan/linux-wechat-agent

Private runtime data is not included in the image. Users must scan-login to WeChat and configure their own LLM/API keys after deployment.
```

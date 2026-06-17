# NAS / 新电脑部署指南

这份文档面向“另一台 NAS 或电脑第一次部署”。核心原则是：代码和镜像可以复用，微信登录数据、数据库 key、模型配置必须在新机器上重新生成。

## 部署前检查

需要：

- Docker
- Docker Compose
- 至少 4GB 内存，建议 8GB+
- 能访问 DockerHub / GitHub
- 能用浏览器打开 NAS 的端口

默认端口：

| 端口 | 服务 |
| --- | --- |
| `3000` | 浏览器微信 |
| `3001` | 浏览器微信 HTTPS，可不用 |
| `8078` | WeChatAgent 控制台 |
| `8090` | AI 记忆 API |

## CPU 架构兼容

当前发布版按多架构部署设计：

- 项目服务镜像 `docker.io/xiaoguiwucan/linux-wechat-agent` 发布 `linux/amd64` 和 `linux/arm64`。
- 微信 GUI 镜像 `ghcr.io/nickrunning/wechat-selkies:0.0.12-minimal` 已验证包含 `linux/amd64` 和 `linux/arm64`。
- `.env.example` 默认 `WECHAT_SELKIES_PLATFORM=` 为空，让 Docker 自动按宿主机 CPU 架构选择镜像。

常见机器对应关系：

| 机器 | 推荐配置 |
| --- | --- |
| Intel/AMD x86 NAS、x86 Linux 服务器 | 保持 `WECHAT_SELKIES_PLATFORM=` 为空，自动拉 `linux/amd64` |
| Apple Silicon、ARM NAS | 保持 `WECHAT_SELKIES_PLATFORM=` 为空，自动拉 `linux/arm64` |
| 需要强制指定架构的特殊环境 | 手动写 `WECHAT_SELKIES_PLATFORM=linux/amd64` 或 `linux/arm64` |

如果旧版 `.env` 里还写着：

```env
WECHAT_SELKIES_PLATFORM=linux/arm64
```

x86 机器上请改成：

```env
WECHAT_SELKIES_PLATFORM=
```

## 从零部署

```bash
git clone https://github.com/xiaoguiwucan/linux-wechat-agent.git
cd linux-wechat-agent
cp .env.example .env
```

如果要局域网访问，在 `.env` 中改：

```env
HTTP_BIND=0.0.0.0
AGENT_CONSOLE_BIND=0.0.0.0
AI_MEMORY_BIND=0.0.0.0
PASSWORD=换成一个强密码
```

启动微信窗口：

```bash
docker compose up -d wechat-selkies
```

打开：

```text
http://NAS_IP:3000
```

扫码登录微信。登录后建议点开需要同步的群，等几十秒。

检测账号目录：

```bash
./scripts/detect-wechat-account.sh
```

提取 key：

```bash
./scripts/extract-wechat-keys.sh
```

启动完整服务：

```bash
docker compose up -d
```

打开控制台：

```text
http://NAS_IP:8078
```

## 模型配置

进入控制台“模型”页面配置 LLM。

如果模型服务跑在同一台 NAS 的宿主机上：

```text
Base URL: http://host.docker.internal:端口/v1
```

如果模型服务跑在另一台机器上：

```text
Base URL: http://模型机器IP:端口/v1
```

图片理解 skill 也在技能页单独配置模型。它可以使用云端视觉模型，也可以使用本地 OpenAI-compatible API。

## 自动回复上线建议

首次部署建议按这个顺序开：

1. 先只开聊天同步，确认消息能进库。
2. 配好模型，测试普通回复和总结。
3. 在控制台开启目标群自动回复。
4. 先低频观察实时状态和发送记录。
5. 再开启斗图、图片理解、网络搜索等 skill。

## 数据迁移

从旧机器迁移到新机器：

旧机器：

```bash
./scripts/backup.sh
```

把 `backups/wechat-agent-backup-*.tar.gz` 复制到新机器项目目录。

新机器：

```bash
./scripts/restore.sh backups/wechat-agent-backup-YYYYMMDD-HHMMSS.tar.gz
docker compose up -d
```

注意：微信登录态跨机器不一定稳定。若微信需要重新登录，登录后重新执行：

```bash
./scripts/detect-wechat-account.sh
./scripts/extract-wechat-keys.sh
docker compose restart wechat-memory-sync wechat-agent-console
```

## 排障

看服务状态：

```bash
docker compose ps
```

看控制台日志：

```bash
docker compose logs -f wechat-agent-console
```

看同步日志：

```bash
docker compose logs -f wechat-memory-sync
```

常见问题：

| 现象 | 处理 |
| --- | --- |
| 3000 打不开 | 检查 `HTTP_BIND`，局域网访问要用 `0.0.0.0` |
| 找不到账号目录 | 先登录微信并点开几个群，再跑 `detect-wechat-account.sh` |
| key 提取失败 | 保持微信在线，打开几个聊天窗口，再重试 |
| 控制台没有新消息 | 检查 key 是否存在、`WECHAT_ACCOUNT_DIR_NAME` 是否正确 |
| 模型连不上 | 宿主机模型不要填 `127.0.0.1`，改用 `host.docker.internal` 或局域网 IP |
| 自动回复发错群风险 | 只给白名单群开启，先观察实时状态和发送记录 |

# GitHub Release 流程

发布目标：

- GitHub 保存源码、Compose、脚本和完整教程。
- DockerHub 保存可直接拉取的项目服务镜像。
- 私有运行数据永远不进入 GitHub 和 DockerHub。

## 发布前检查

确认这些文件没有被 git 跟踪：

```bash
git status --short
git check-ignore .env config runtime backups || true
```

确认没有个人账号路径或密钥：

```bash
rg -n "ghp_|tvly-|sk-|wxid_your_private_account|all_keys|api_key" \
  -g '!runtime/**' \
  -g '!config/**' \
  -g '!.git/**' .
```

允许出现的内容：

- `.env.example` 里的空值或占位值
- 代码字段名 `api_key`
- 文档里的占位说明

## 本地校验

```bash
docker compose config >/tmp/wechat-agent-compose.yml
bash -n scripts/*.sh
```

如果本地开发构建：

```bash
docker compose -f docker-compose.yml -f docker-compose.build.yml build
```

## 提交代码

```bash
git add README.md docs .env.example docker-compose.yml docker-compose.build.yml scripts .gitignore
git commit -m "chore: prepare docker release packaging"
git push origin HEAD
```

## 发布 DockerHub 镜像

```bash
docker login
./scripts/publish-dockerhub.sh docker.io/xiaoguiwucan/linux-wechat-agent 0.2.0
```

## 创建 GitHub Release

用 GitHub CLI：

```bash
gh auth login
git tag v0.2.0
git push origin v0.2.0
gh release create v0.2.0 \
  --title "WeChatAgent v0.2.0" \
  --notes-file CHANGELOG.md
```

或在 GitHub 网页创建 Release，Tag 使用 `v0.2.0`。

## Release Notes 建议结构

```markdown
## Highlights
- Docker Compose one-command deployment.
- Browser WeChat, memory sync, AI memory, agent console.
- Auto reply with group switching and skill system.
- Image understanding, meme sending, web search, daily reports.

## Deploy
1. Clone the repo.
2. Copy .env.example to .env.
3. Start wechat-selkies and scan-login.
4. Run detect-wechat-account and extract-wechat-keys.
5. Start all services and configure models.

## Upgrade
- Run ./scripts/backup.sh
- Run docker compose pull
- Run docker compose up -d

## Security
- Runtime data, WeChat DBs, keys, and model tokens are not included.
```

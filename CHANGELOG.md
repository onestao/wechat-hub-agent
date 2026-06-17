# Changelog

## v0.3.1 - 2026-06-18

### Changed
- Published the project service image as a multi-architecture DockerHub manifest for `linux/amd64` and `linux/arm64`.
- Removed the default `linux/arm64` platform pin from the WeChat GUI service so x86 hosts can automatically pull `linux/amd64`.
- Updated deployment docs to describe x86 NAS, Intel/AMD servers, ARM NAS, and Apple Silicon compatibility.
- Updated DockerHub publishing script to use `docker buildx build --platform linux/amd64,linux/arm64 --push` by default.

### Verified
- Verified `ghcr.io/nickrunning/wechat-selkies:0.0.12-minimal` includes both `linux/amd64` and `linux/arm64` manifests.

## v0.3.0 - 2026-06-18

### Added
- Added production-oriented Docker Compose release packaging.
- Added `.env.example` for safe deployment configuration without leaking local runtime data.
- Added DockerHub image workflow and local development compose override.
- Added NAS/new-computer deployment guide, feature overview, DockerHub publishing guide, and GitHub release checklist.
- Added scripts for account directory detection, key extraction, runtime backup, restore, local development startup, and DockerHub publishing.

### Changed
- Replaced hardcoded local WeChat account paths with env-driven `WECHAT_ACCOUNT_DIR_NAME`.
- Updated agent console refresh logic to use configured or auto-discovered WeChat DB paths.
- Kept release deployments image-based while preserving a build override for local development.
- Added `host.docker.internal` mapping for model services running on the host.

### Security
- Confirmed `.env`, `config/`, `runtime/`, backups, WeChat keys, and private database files stay out of Git and Docker images.

## v0.2.0 - 2026-06-15

### Added
- Added automatic free-talk reply worker for group messages.
- Added threshold-based auto send mode using the existing talk scoring rules.
- Added per-chat watermarks so enabling auto reply does not reply to old history.
- Added automatic outbox metadata for score, threshold, decision, trigger, and send confirmation.
- Added auto reply status API and console controls for auto-send mode, allowed groups, poll interval, and random delays.

### Changed
- Auto replies reuse the verified WeChat UI sender: switch to target group, paste, validate input, then send.
- WeChat UI operations stay serialized while scoring and message scanning can cover multiple groups.
- Consecutive replies to the same group reuse the current WeChat chat instead of searching again, with forced reopen fallback on verification mismatch.

## v0.1.0 - 2026-06-15

### Added
- Added manual WeChat reply delivery from the agent console.
- Added automatic target group switching for `值班群` and `PT站看片狂魔小群`.
- Added short WeChat search keywords: `值班群` searches `值班`, and `PT站看片狂魔小群` searches `PT`.
- Added random delay support for group switching and send actions.
- Added reply outbox records for draft/send attempts.

### Fixed
- Fixed stale preview state causing replies to use the previous selected group.
- Fixed full group-name search opening WeChat global search instead of the local chat.
- Fixed small WeChat window detection after container restart.
- Fixed clipboard paste reliability under Selkies clipboard monitoring.
- Fixed false success by verifying pasted text through direct input-box copy-back.

### Notes
- Runtime data, decrypted databases, local config, certificates, and secrets are intentionally excluded from Git.
- Actual WeChat UI operations remain serialized to prevent two sends from fighting over the same input box.

# Changelog

## v0.4.2 - 2026-06-20

### Added
- Added a dedicated system log console with category, level, keyword search, live refresh, and detailed failure records.
- Added Top10 style-persona distillation for each group, including persona cards, evidence retrieval, manual persona switching, and optional LLM style rewriting.
- Added per-group auto-reply strategy settings for mode, threshold, meme probability, and switch/send delay overrides.
- Added a global style-rewrite toggle so auto replies can skip the extra rewrite model call when speed matters.

### Changed
- Auto-reply allowed chats now include enabled per-group settings, so a group with its own strategy is no longer silently ignored if the old whitelist is incomplete.
- WeChat group switching uses short stable search keywords, including `PT`, `值班`, and `测试`, with generic two-character fallback for other groups.
- Text and image sending now force target-chat verification instead of trusting stale cached active chat state, reducing wrong-group sends.
- Auto-reply no longer sends local fallback text when the LLM or memory evidence fails; failures are recorded in the log console instead.
- The v0.4.1 per-group excluded-member UI and backend guard are preserved alongside the new persona/logging features.

### Fixed
- Fixed a wrong-group send risk where replies could reuse a previous active chat after switching between groups.
- Fixed message scanning so multiple configured groups can be considered instead of only one active group.
- Fixed daily report live-status code that referenced an unset variable before image sending.
- Fixed WeChat memory sync instability caused by FTS auxiliary databases and added a REINDEX/integrity retry path for malformed SQLite reads.
- Fixed release branch reconciliation so v0.4.2 keeps v0.4.1 documentation, changelog, and release checks.

## v0.4.1 - 2026-06-19

### Added
- Added per-group auto-reply member exclusion lists.
- Added searchable group-member picker for exclusion settings.
- Added a visible excluded-member list with removable member chips in the auto-reply console.

### Changed
- Auto-reply scoring, candidate scanning, and final execution now all honor excluded members.
- Excluded member matching now checks member username, alias, group nickname, remark, nickname, and synced contact metadata.
- The auto-reply settings form no longer refreshes over the user while they are editing exclusion settings.

### Fixed
- Fixed the exclusion panel showing “waiting for group list” when chats loaded after the auto-reply form rendered.
- Fixed clearing all excluded members so old chat keys do not survive config deep-merge saves.
- Fixed filtered member selection so searching does not accidentally remove already excluded members hidden by the current search.

## v0.4.0 - 2026-06-19

### Added
- Added Clawbot-based WeChat login guard notifications with repeat reminders and manual check controls.
- Added visual WeChat UI state detection for `login_required`, `login_pending`, and active chat states.
- Added richer memory database management, grouped export/import entry points, and image memory gallery workflows.
- Added image understanding skill configuration, model connectivity checks, and image upload testing support.
- Added evidence-driven person profile rebuilding with progress state, profile tags, and relationship data improvements.

### Changed
- Improved overview universe layout, leaderboard responsiveness, rank styling, and high-density screen behavior.
- Improved auto-reply routing, mention handling, self-message filtering, meme trigger behavior, and real-time reply status.
- Improved summary/report generation templates, nickname mapping, and memory-backed chat summary behavior.
- Improved skill management and built-in skill behavior for search, memes, article cards, and image-only replies.

### Fixed
- Fixed WeChat login recovery false positives where fresh sync status could incorrectly send “restored online”.
- Fixed login guard auto-click coordinates for “我知道了” and “登录”, then waits for mobile confirmation instead of claiming recovery.
- Fixed several settings persistence issues where saved mode, limit, and skill parameters could revert after refresh.
- Fixed multiple UI clipping/overlap problems in leaderboards, profile cards, image gallery, and overview controls.

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

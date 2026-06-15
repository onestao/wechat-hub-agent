# Changelog

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

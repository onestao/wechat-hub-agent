---
name: web-search
description: 使用 Tavily 搜索网络资讯；有 Tavily 额度时优先联网搜索，没有额度或未配置时退回模型能力。
---

# Web Search

当用户明确要求搜索网络信息、查最新资讯、查新闻或查公开网页信息时触发。
优先使用 Tavily Search 获取实时搜索结果；没有 Tavily key、额度不足或搜索失败时，退回 LLM 的非联网回答，并明确说明没有实时搜索结果。
不要把网络搜索技能用于公众号文章正文读取。

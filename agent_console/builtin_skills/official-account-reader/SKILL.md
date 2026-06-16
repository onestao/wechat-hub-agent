---
name: official-account-reader
description: 识别微信群中的公众号文章卡片或链接，只读取标题、来源和链接，不抓取正文、不生成正文总结。
---

# Official Account Reader

当微信群出现公众号文章卡片、mp.weixin.qq.com 链接，或用户要求总结公众号文章时触发。
只读取并回复公众号/文章卡片的标题、来源和链接。
不抓取正文，不调用 Tavily，不生成正文总结。
如果用户要求总结正文，明确说明当前只能看到标题，不能读取正文。

# PRD: 可执行选品 + 内容策略引擎 (v2)

> **产品本质**：一个自增长的达人监控网络 — 从 hashtag 冷启动，逐步构建高价值带货达人池，最终实现24小时内捕捉全品类爆款带货视频。

---

## 1. 核心认知升级（v1 → v2）

| | v1 | v2 |
|---|---|---|
| 数据来源 | hashtag 搜索 | **达人池（profile pool）** 为主 |
| 爆款发现 | 靠 hashtag 碰运气 | 直接监控已验证的带货达人 |
| 信噪比 | 低（大量娱乐内容混入） | 高（池内全是已验证带货号） |
| 可扩展性 | 固定 hashtag 列表 | **自动增长**：爆款 → 新作者 → 进池 |
| 产品链接 | 无法从网页获取 | 通过 profile bioLink 获取 |

**关键认知**：你不是在找"所有达人"，而是在找**最早能打出爆款的那一小撮人**。他们反复测试新产品、反复出爆款，是最有价值的数据源。

---

## 2. 三层信号模型（不变）

```
Layer 1：内容信号        爆款带货视频 + 24h内 + 播放增速高
         ↓
Layer 2：商品信号        SKU识别 + 多达人验证 + bioLink商品链接
         ↓
Layer 3：可执行行动包    内容模板 + 商品信息 + 复刻难度 + 优先级
```

---

## 3. Apify 抓取策略（预算分配）

### 80% — Profiles（主力）
**用途**：抓"谁在带货 + 最新视频"，数据密度远高于 hashtag
```json
{
  "profiles": ["creator1", "creator2", "..."],
  "profileScrapeSections": ["videos"],
  "profileSorting": "latest",
  "resultsPerPage": 5,
  "excludePinnedPosts": true,
  "shouldDownloadVideos": false
}
```
- 初始种子：200–1000 个达人
- 抓取频率：每 30–60 分钟
- 优势：达人已被验证会出爆款，数据密度高，可做早期信号

### 15% — Hashtags（补充）
**用途**：发现新趋势、拓展种子达人、找新类目
```json
{
  "hashtags": ["tiktokmademebuyit", "amazonfinds", "tiktokshop",
               "tiktokfinds", "musthave", "productreview"],
  "resultsPerPage": 10,
  "excludePinnedPosts": true
}
```
- 问题：噪音大，大量娱乐内容混入
- 只用于：冷启动 + 每日一次新品类探索

### 5% — Search（慎用）
**用途**：锁定特定类目后的精准补充
```json
{
  "searchQueries": ["kitchen gadget", "portable blender tiktok shop"],
  "resultsPerPage": 5
}
```
- 问题：结果不稳定，irrelevant 内容多
- 只在明确锁定品类后启用

---

## 4. 系统架构（v2）

```
【冷启动 Day 1】
  hashtags 抓取（bootstrap）
        ↓
  爆款视频过滤 + 作者提取
        ↓
  写入 profile 池（目标 50~200 个种子）

【稳态 Day 3+】
  profile 池（核心资产，80%预算）
        ↓
  每30~60分钟：抓池内达人最新5条视频
        ↓
  爆款判定 + 行动包生成
        ↓
  新爆款作者 → 自动加入 profile 池（自增长）
        ↓
  每日一次：hashtag 补充（15%预算）发现新达人

【Pipeline 路由逻辑】
  if profile_pool < 20个:
      → hashtag 模式（bootstrap）
  else:
      → profile 模式（主循环）
      → 附加小规模 hashtag 补充
```

---

## 5. Profile 池数据结构

```json
{
  "7349977896141718533": {
    "id": "7349977896141718533",
    "username": "crazyfinds456",
    "followers": 11300,
    "category": "gadgets",
    "viral_count": 3,
    "last_viral_at": "2026-05-01T18:00:00Z",
    "bio_link": "https://amzn.to/shop/crazyfinds456",
    "added_at": "2026-05-01T10:00:00Z",
    "source": "hashtag_bootstrap",
    "consecutive_misses": 0
  }
}
```

### 加入规则（满足任一）
1. 24h内出现爆款视频（views ≥ 500K 或 velocity ≥ 50K/h）
2. bioLink 包含 shopify / amazon / linktree（高概率带货号）

### 删除规则
- 超过 14 天无新视频
- 连续 5 次抓取无任何爆款（`consecutive_misses ≥ 5`）
- 内容明显偏娱乐（非商品类 hashtag 占比 > 80%）

### 品类标签（自动打标）
```
beauty | home_kitchen | fitness | pets | gadgets | fashion | other
```

---

## 6. 爆款判定标准

| 指标 | 权重 | 说明 |
|------|------|------|
| 播放量 | 40% | ≥ 500K 为强信号 |
| 播放增速 | 30% | ≥ 50K/h = 正在爆 |
| 互动率 | 20% | (likes + comments×2 + shares×3) / views |
| 新鲜度 | 10% | 发布越近权重越高，>48h 降权 |

---

## 7. 里程碑

| 版本 | 交付 |
|------|------|
| V2.0 | profile_store + profile_manager + pipeline 三模式路由 |
| V2.1 | 每次运行后自动把新爆款作者加入池（自增长） |
| V2.2 | 品类分类 + 按品类筛选 |
| V2.3 | bioLink 提取 → 真实商品入口 |
| V3.0 | 飞书/邮件实时告警 |

---

## 8. 不做（Out of Scope）

- ❌ 自动发布视频
- ❌ 粉丝关系图谱（成本高噪音大）
- ❌ TikTok 官方 API 对接（需商业审批）

# 北京户外活动聚合平台

自动聚合绿野、微信公众号的北京户外活动，每天定时更新。

## 架构

```
GitHub Actions（每天08:00）
  → 爬取绿野 + 搜狗微信
  → 火山方舟LLM结构化提取
  → 写入 Supabase 数据库
  
GitHub Pages（静态前端）
  → 直接查询 Supabase REST API
  → 展示活动列表，支持筛选
```

## 部署步骤

### 1. 初始化 Supabase 数据库

1. 注册 [Supabase](https://supabase.com)，新建项目
2. 进入 SQL Editor，执行 `supabase_schema.sql`
3. 记录以下三个值：
   - Project URL → `SUPABASE_URL`
   - anon/public key → `SUPABASE_ANON_KEY`（前端用）
   - service_role key → `SUPABASE_SERVICE_KEY`（爬虫用，勿泄露）

### 2. 配置前端

编辑 `docs/index.html`，替换顶部两个配置项：

```js
const SUPABASE_URL  = 'https://xxxx.supabase.co';
const SUPABASE_ANON = 'eyJxxx...';
```

### 3. 推送到 GitHub

```bash
git init
git add .
git commit -m "init"
git remote add origin https://github.com/你的用户名/outdoor-beijing.git
git push -u origin main
```

### 4. 开启 GitHub Pages

仓库 Settings → Pages → Source 选 `main` 分支 `/docs` 目录 → Save

### 5. 配置 GitHub Secrets

仓库 Settings → Secrets and variables → Actions → New repository secret：

| 名称 | 值 |
|------|-----|
| `SUPABASE_URL` | Supabase Project URL |
| `SUPABASE_SERVICE_KEY` | service_role key |
| `VOLC_API_KEY` | 火山方舟 API Key |

### 6. 手动触发第一次爬取

Actions → Daily Outdoor Activity Crawl → Run workflow

### 7. 审核活动

爬取的活动默认 `status=pending`，需要在 Supabase Dashboard 中将确认无误的活动改为 `status=approved` 才会在前端显示。

可以在 Supabase Table Editor 中批量操作，或后续做一个简单的管理后台。

## 目录结构

```
outdoor-beijing/
├── crawler/
│   ├── main.py           # 主调度脚本
│   ├── crawl_lvye.py     # 绿野爬虫
│   ├── crawl_weixin.py   # 微信公众号爬虫
│   ├── llm_extract.py    # 火山方舟LLM提取
│   ├── save_to_db.py     # 入库模块
│   └── requirements.txt
├── docs/
│   └── index.html        # GitHub Pages 前端
├── .github/
│   └── workflows/
│       └── daily_crawl.yml
└── supabase_schema.sql
```

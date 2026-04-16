-- ============================================================
-- 北京户外活动聚合平台 - Supabase 数据库初始化脚本
-- 在 Supabase Dashboard > SQL Editor 中执行此脚本
-- ============================================================

-- 1. 组织方表
CREATE TABLE IF NOT EXISTS organizers (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,          -- 组织方名称
    platform    TEXT,                          -- 来源平台: lvye / weixin
    profile_url TEXT,                          -- 主页链接
    tags        TEXT[],                        -- 擅长类型标签
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 活动主表
CREATE TABLE IF NOT EXISTS activities (
    id               SERIAL PRIMARY KEY,
    activity_name    TEXT NOT NULL,            -- 活动名称
    activity_type    TEXT,                     -- 类型: 徒步/骑行/露营/攀岩/滑雪/皮划艇/其他
    difficulty       TEXT,                     -- 难度: 入门/进阶/挑战
    activity_date    DATE,                     -- 活动日期
    meeting_time     TEXT,                     -- 集合时间（文本，如"早7:00"）
    meeting_place    TEXT,                     -- 集合地点
    duration         TEXT,                     -- 活动时长（文本，如"1天"）
    price            TEXT,                     -- 费用描述（文本，如"AA制约80元"）
    price_min        INTEGER,                  -- 最低费用（数字，用于筛选）
    organizer_name   TEXT,                     -- 组织方名称
    organizer_id     INTEGER REFERENCES organizers(id),
    quota            TEXT,                     -- 名额描述
    destination      TEXT,                     -- 目的地/路线名称
    description      TEXT,                     -- 活动简介
    source_url       TEXT NOT NULL UNIQUE,     -- 原文链接（去重依据）
    source_platform  TEXT,                     -- 来源平台: lvye / weixin
    raw_text         TEXT,                     -- 原始文章备份
    cover_image      TEXT,                     -- 封面图URL
    status           TEXT DEFAULT 'pending',   -- pending/approved/rejected
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 索引（加速筛选查询）
CREATE INDEX IF NOT EXISTS idx_activities_date     ON activities(activity_date);
CREATE INDEX IF NOT EXISTS idx_activities_type     ON activities(activity_type);
CREATE INDEX IF NOT EXISTS idx_activities_status   ON activities(status);
CREATE INDEX IF NOT EXISTS idx_activities_platform ON activities(source_platform);

-- 4. 开启 Row Level Security，允许匿名读取已审核活动
ALTER TABLE activities  ENABLE ROW LEVEL SECURITY;
ALTER TABLE organizers  ENABLE ROW LEVEL SECURITY;

-- 允许所有人读取 approved 状态的活动（前端直接查询用）
CREATE POLICY "public read approved activities"
    ON activities FOR SELECT
    USING (status = 'approved');

-- 允许所有人读取组织方信息
CREATE POLICY "public read organizers"
    ON organizers FOR SELECT
    USING (true);

-- 5. 允许服务端（service_role key）写入数据
-- 爬虫脚本使用 SUPABASE_SERVICE_KEY，绕过 RLS 直接写入
-- 无需额外配置，service_role 默认有全部权限

-- 6. 自动更新 updated_at 字段的触发器
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_activities_updated_at
    BEFORE UPDATE ON activities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ============================================================
-- 初始化完成后，在 Supabase Dashboard > Settings > API 中获取：
--   SUPABASE_URL      → Project URL
--   SUPABASE_ANON_KEY → anon/public key（前端用）
--   SUPABASE_SERVICE_KEY → service_role key（爬虫用，勿泄露）
-- ============================================================

"""
入库模块：将结构化活动数据写入 Supabase，自动去重
"""

import os
import json
import logging
from typing import Optional
from datetime import date

from supabase import create_client, Client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def get_client() -> Client:
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise ValueError("SUPABASE_URL 或 SUPABASE_SERVICE_KEY 未设置")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def upsert_organizer(client: Client, name: str, platform: str) -> Optional[int]:
    """插入或获取组织方ID"""
    if not name:
        return None
    try:
        # 先查是否存在
        res = client.table("organizers").select("id").eq("name", name).execute()
        if res.data:
            return res.data[0]["id"]
        # 不存在则插入
        res = client.table("organizers").insert({
            "name": name,
            "platform": platform,
        }).execute()
        return res.data[0]["id"] if res.data else None
    except Exception as e:
        logger.warning(f"组织方处理失败 '{name}': {e}")
        return None


def is_valid_date(date_str: Optional[str]) -> bool:
    """校验日期格式是否合法"""
    if not date_str:
        return False
    try:
        from datetime import datetime
        d = datetime.strptime(date_str, "%Y-%m-%d").date()
        # 过滤过去超过7天的活动（可能是旧文章）
        today = date.today()
        from datetime import timedelta
        return d >= today - timedelta(days=7)
    except ValueError:
        return False


def save_activities(activities: list[dict]) -> dict:
    """
    批量写入活动数据，自动去重（以 source_url 为唯一键）
    返回统计信息
    """
    client = get_client()
    stats = {"inserted": 0, "skipped_duplicate": 0, "skipped_invalid": 0, "failed": 0}

    for item in activities:
        source_url = item.get("source_url", "").strip()
        if not source_url:
            stats["skipped_invalid"] += 1
            continue

        # 日期校验：有日期时过滤过期活动；无日期（如"电询"）允许入库
        activity_date = item.get("activity_date")
        if activity_date and not is_valid_date(activity_date):
            logger.info(f"  跳过（日期已过期）: {item.get('activity_name', '')[:30]} | {activity_date}")
            stats["skipped_invalid"] += 1
            continue

        try:
            # 检查是否已存在（去重）
            existing = client.table("activities").select("id").eq("source_url", source_url).execute()
            if existing.data:
                logger.info(f"  已存在，跳过: {source_url[:60]}")
                stats["skipped_duplicate"] += 1
                continue

            # 处理组织方
            organizer_id = upsert_organizer(
                client,
                item.get("organizer_name"),
                item.get("source_platform", ""),
            )

            # 构建入库数据（只保留数据库字段）
            record = {
                "activity_name":   item.get("activity_name", "未知活动")[:200],
                "activity_type":   item.get("activity_type"),
                "difficulty":      item.get("difficulty"),
                "activity_date":   item.get("activity_date"),
                "meeting_time":    item.get("meeting_time"),
                "meeting_place":   item.get("meeting_place"),
                "duration":        item.get("duration"),
                "price":           item.get("price"),
                "price_min":       item.get("price_min"),
                "organizer_name":  item.get("organizer_name"),
                "organizer_id":    organizer_id,
                "quota":           item.get("quota"),
                "destination":     item.get("destination"),
                "description":     item.get("description"),
                "source_url":      source_url,
                "source_platform": item.get("source_platform"),
                "raw_text":        (item.get("raw_text") or "")[:2000],
                "cover_image":     item.get("cover_image"),
                "status":          "pending",  # 默认待审核
            }

            # 清理None以外的空字符串
            record = {k: (v if v != "" else None) for k, v in record.items()}

            client.table("activities").insert(record).execute()
            logger.info(f"  ✓ 入库: {record['activity_name'][:40]}")
            stats["inserted"] += 1

        except Exception as e:
            logger.error(f"  入库失败 {source_url[:60]}: {e}")
            stats["failed"] += 1

    logger.info(
        f"入库完成 | 新增: {stats['inserted']} | "
        f"重复跳过: {stats['skipped_duplicate']} | "
        f"无效跳过: {stats['skipped_invalid']} | "
        f"失败: {stats['failed']}"
    )
    return stats


if __name__ == "__main__":
    import sys
    input_file = sys.argv[1] if len(sys.argv) > 1 else "extracted.json"
    with open(input_file, encoding="utf-8") as f:
        data = json.load(f)
    save_activities(data)

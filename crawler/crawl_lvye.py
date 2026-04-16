"""
绿野网 (lvye.cn) 活动爬虫
抓取北京地区近期户外活动列表及详情页
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.lvye.cn/",
}

BASE_URL = "https://www.lvye.cn"
# 绿野活动列表页，按北京筛选，按时间排序
LIST_URL = "https://www.lvye.cn/activities/?city=1&sort=time&page={page}"


def fetch_page(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """请求页面，失败自动重试"""
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(1.5, 3.0))  # 随机延迟，避免被封
            resp = requests.get(url, headers=HEADERS, timeout=15)
            resp.raise_for_status()
            resp.encoding = "utf-8"
            return BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            logger.warning(f"第{attempt+1}次请求失败 {url}: {e}")
            if attempt == retries - 1:
                logger.error(f"放弃请求: {url}")
                return None
    return None


def parse_activity_list(soup: BeautifulSoup) -> list[dict]:
    """解析活动列表页，返回活动摘要列表"""
    activities = []
    # 绿野活动卡片选择器（根据实际页面结构调整）
    cards = soup.select(".activity-item, .act-item, .list-item")
    if not cards:
        # 备用：尝试更宽泛的选择器
        cards = soup.select("li[class*='activity'], div[class*='activity-card']")

    for card in cards:
        try:
            # 标题和链接
            title_el = card.select_one("a[href*='/activities/']")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            url = href if href.startswith("http") else BASE_URL + href

            # 日期
            date_el = card.select_one(".date, .time, [class*='date']")
            date_text = date_el.get_text(strip=True) if date_el else ""

            # 费用
            price_el = card.select_one(".price, .fee, [class*='price']")
            price_text = price_el.get_text(strip=True) if price_el else ""

            # 难度
            diff_el = card.select_one(".difficulty, .level, [class*='diff']")
            diff_text = diff_el.get_text(strip=True) if diff_el else ""

            # 组织方
            org_el = card.select_one(".organizer, .author, .user, [class*='org']")
            org_text = org_el.get_text(strip=True) if org_el else ""

            # 封面图
            img_el = card.select_one("img")
            img_url = img_el.get("src", "") or img_el.get("data-src", "") if img_el else ""

            activities.append({
                "activity_name": title,
                "source_url": url,
                "date_text": date_text,
                "price": price_text,
                "difficulty": diff_text,
                "organizer_name": org_text,
                "cover_image": img_url,
                "source_platform": "lvye",
            })
        except Exception as e:
            logger.warning(f"解析卡片失败: {e}")
            continue

    return activities


def parse_activity_detail(url: str) -> dict:
    """抓取活动详情页，提取结构化字段"""
    soup = fetch_page(url)
    if not soup:
        return {}

    detail = {"source_url": url, "source_platform": "lvye"}

    try:
        # 标题
        title_el = soup.select_one("h1, .activity-title, [class*='title']")
        if title_el:
            detail["activity_name"] = title_el.get_text(strip=True)

        # 正文（用于LLM提取）
        content_el = soup.select_one(
            ".activity-content, .content, .detail-content, article, [class*='content']"
        )
        if content_el:
            detail["raw_text"] = content_el.get_text(separator="\n", strip=True)[:3000]

        # 封面图
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img:
            detail["cover_image"] = og_img.get("content", "")

        # 尝试直接从页面提取结构化字段（绿野部分活动有固定格式）
        info_items = soup.select(".info-item, .detail-item, [class*='info-row']")
        for item in info_items:
            label_el = item.select_one(".label, .key, dt")
            value_el = item.select_one(".value, .val, dd")
            if not label_el or not value_el:
                continue
            label = label_el.get_text(strip=True)
            value = value_el.get_text(strip=True)

            if "时间" in label or "日期" in label:
                detail["date_text"] = value
            elif "集合" in label and "时间" in label:
                detail["meeting_time"] = value
            elif "集合" in label and ("地" in label or "点" in label):
                detail["meeting_place"] = value
            elif "时长" in label or "行程" in label:
                detail["duration"] = value
            elif "费用" in label or "收费" in label or "价格" in label:
                detail["price"] = value
            elif "难度" in label:
                detail["difficulty"] = value
            elif "名额" in label or "人数" in label:
                detail["quota"] = value
            elif "目的地" in label or "路线" in label:
                detail["destination"] = value

    except Exception as e:
        logger.warning(f"解析详情页失败 {url}: {e}")

    return detail


def crawl_lvye(max_pages: int = 5, days_ahead: int = 30) -> list[dict]:
    """
    主入口：爬取绿野近期北京活动
    max_pages: 最多爬取列表页数
    days_ahead: 只保留未来N天内的活动
    """
    all_activities = []
    cutoff_date = datetime.now() + timedelta(days=days_ahead)

    for page in range(1, max_pages + 1):
        logger.info(f"正在爬取绿野列表第 {page} 页...")
        url = LIST_URL.format(page=page)
        soup = fetch_page(url)
        if not soup:
            break

        items = parse_activity_list(soup)
        if not items:
            logger.info(f"第 {page} 页无活动，停止翻页")
            break

        logger.info(f"第 {page} 页找到 {len(items)} 条活动")

        for item in items:
            # 抓取详情页
            logger.info(f"  抓取详情: {item['activity_name'][:30]}...")
            detail = parse_activity_detail(item["source_url"])
            merged = {**item, **detail}
            all_activities.append(merged)

        # 翻页间隔
        time.sleep(random.uniform(2, 4))

    logger.info(f"绿野爬取完成，共 {len(all_activities)} 条活动")
    return all_activities


if __name__ == "__main__":
    results = crawl_lvye(max_pages=3)
    # 本地调试：输出到文件
    with open("lvye_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 条到 lvye_raw.json")

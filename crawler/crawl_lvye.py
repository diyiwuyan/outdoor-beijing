"""
绿野网 (lvye.cn) 活动爬虫
抓取精选活动列表（/lines/all）及详情页
直接解析结构化字段，不依赖 LLM
"""

import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
import logging
from datetime import date, datetime
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
LIST_URLS = [
    "https://www.lvye.cn/lines/all",
]

# 活动类型关键词映射
TYPE_KEYWORDS = {
    "徒步": ["徒步", "登山", "爬山", "穿越", "越野", "hiking", "trail"],
    "骑行": ["骑行", "自行车", "单车", "cycling"],
    "露营": ["露营", "帐篷", "营地", "camp"],
    "攀岩": ["攀岩", "攀登", "climbing"],
    "滑雪": ["滑雪", "ski", "雪地"],
    "皮划艇": ["皮划艇", "划船", "漂流", "kayak"],
}

# 难度关键词
DIFF_KEYWORDS = {
    "入门": ["入门", "亲子", "轻松", "简单", "初级", "新手"],
    "进阶": ["进阶", "中级", "中等"],
    "挑战": ["挑战", "高级", "困难", "强度", "极限", "重装"],
}


def infer_type(text: str) -> Optional[str]:
    """从标题/描述推断活动类型"""
    text_lower = text.lower()
    for t, keywords in TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return t
    return "其他"


def infer_difficulty(text: str) -> Optional[str]:
    """从标题/描述推断难度"""
    for d, keywords in DIFF_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return d
    return None


def parse_date_text(date_text: str) -> Optional[str]:
    """
    从绿野日期文本解析出最近的未来日期（YYYY-MM-DD）
    输入示例：
      "05-01日"
      "04-24、05-01、05-16日"
      "电询"
      "05-01~05-03"
    """
    if not date_text or "电询" in date_text:
        return None

    today = date.today()
    current_year = today.year

    # 提取所有 MM-DD 格式的日期
    matches = re.findall(r'(\d{1,2})[/-](\d{1,2})', date_text)
    if not matches:
        return None

    candidates = []
    for m, d in matches:
        try:
            month, day = int(m), int(d)
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            # 先试今年
            try:
                candidate = date(current_year, month, day)
            except ValueError:
                continue
            # 如果已过去超过7天，试明年
            if (candidate - today).days < -7:
                try:
                    candidate = date(current_year + 1, month, day)
                except ValueError:
                    continue
            candidates.append(candidate)
        except Exception:
            continue

    if not candidates:
        return None

    # 取最近的未来日期（或最近的过去日期）
    future = [c for c in candidates if c >= today]
    if future:
        return min(future).strftime("%Y-%m-%d")
    # 全是过去的，取最近的
    return max(candidates).strftime("%Y-%m-%d")


def parse_price_text(price_text: str) -> Optional[int]:
    """从价格文本提取最低数字"""
    if not price_text:
        return None
    nums = re.findall(r'[\d,]+(?:\.\d+)?', price_text.replace(",", ""))
    if not nums:
        return None
    try:
        return int(float(min(nums, key=lambda x: float(x))))
    except Exception:
        return None


def fetch_page(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """请求页面，失败自动重试"""
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(1.5, 3.0))
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


def parse_list_page(soup: BeautifulSoup) -> list[dict]:
    """解析活动列表页，返回活动摘要列表"""
    activities = []
    show_links = soup.select("a[href*='/lines/show_']")
    seen_urls = set()

    for link in show_links:
        try:
            href = link.get("href", "")
            url = href if href.startswith("http") else BASE_URL + href
            if url in seen_urls:
                continue
            seen_urls.add(url)

            li = link.find_parent("li") or link.parent

            # 标题
            title_el = li.select_one(".bt") if li else None
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                img = link.select_one("img")
                title = img.get("alt", "").strip() if img else link.get_text(strip=True)
            if not title:
                continue

            # 封面图（懒加载用 st-src 或 data-src）
            img_el = link.select_one("img")
            cover = ""
            if img_el:
                cover = (img_el.get("st-src") or img_el.get("data-src")
                         or img_el.get("src") or "")
                # 过滤占位图
                if "grey.gif" in cover or "placeholder" in cover:
                    cover = img_el.get("st-src") or img_el.get("data-src") or ""

            # 日期
            date_el = li.select_one(".dates") if li else None
            date_text = date_el.get_text(strip=True).replace("团期：", "").strip() if date_el else ""

            # 简介
            desc_el = li.select_one(".ts") if li else None
            desc_text = desc_el.get_text(strip=True) if desc_el else ""

            activities.append({
                "activity_name": title,
                "source_url": url,
                "date_text": date_text,
                "description": desc_text,
                "cover_image": cover,
                "source_platform": "lvye",
            })
        except Exception as e:
            logger.warning(f"解析卡片失败: {e}")
            continue

    return activities


def parse_activity_detail(url: str, list_item: dict) -> dict:
    """
    抓取活动详情页，提取结构化字段
    list_item: 列表页已有的数据，用于补充
    """
    soup = fetch_page(url)
    if not soup:
        return {}

    detail = {"source_url": url, "source_platform": "lvye"}

    try:
        # 标题（详情页 h1 更准确）
        h1 = soup.select_one("h1")
        if h1:
            detail["activity_name"] = h1.get_text(strip=True)

        # 价格
        price_el = soup.select_one(".new-price")
        if price_el:
            detail["price"] = price_el.get_text(strip=True)

        # 封面图（og:image 最可靠）
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img and og_img.get("content"):
            detail["cover_image"] = og_img.get("content", "")
        elif list_item.get("cover_image"):
            detail["cover_image"] = list_item["cover_image"]

        # 从详情页提取集合地点、天数等
        # 绿野详情页结构：.cp-show-msg 或 .line-info 里有表格
        for sel in [".cp-show-msg p", ".line-info li", ".info-item", ".detail-info td"]:
            for row in soup.select(sel):
                text = row.get_text(strip=True)
                if ("集合" in text or "出发地" in text) and not detail.get("meeting_place"):
                    detail["meeting_place"] = text[:100]
                elif ("天" in text or "日" in text) and re.search(r'\d+天', text) and not detail.get("duration"):
                    m = re.search(r'\d+天\d*晚?', text)
                    if m:
                        detail["duration"] = m.group()

        # raw_text 供备用
        content_el = soup.select_one(
            ".dmp-des, .detail-main, .product-content, .line-content, .line-show-main, .line-desc"
        )
        if content_el:
            raw = content_el.get_text(separator="\n", strip=True)[:2000]
        else:
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            raw = soup.get_text(separator="\n", strip=True)[:2000]
        detail["raw_text"] = raw

    except Exception as e:
        logger.warning(f"解析详情页失败 {url}: {e}")

    return detail


def build_activity_record(list_item: dict, detail: dict) -> dict:
    """
    合并列表页和详情页数据，直接构建入库记录
    不依赖 LLM，用规则推断类型/难度/日期
    """
    merged = {**list_item, **detail}

    name = merged.get("activity_name", "")
    desc = merged.get("description", "")
    combined_text = name + " " + desc

    # 解析日期
    date_text = merged.get("date_text", "")
    activity_date = parse_date_text(date_text)

    # 解析价格
    price_str = merged.get("price", "")
    price_min = parse_price_text(price_str)

    # 推断类型和难度
    activity_type = infer_type(combined_text)
    difficulty = infer_difficulty(combined_text)

    # 从标题提取天数（如 "1日"、"3天2晚"）
    duration = merged.get("duration")
    if not duration:
        m = re.search(r'(\d+)[日天](?:\d+晚)?', name)
        if m:
            duration = m.group()

    record = {
        "activity_name":   name[:200],
        "activity_type":   activity_type,
        "difficulty":      difficulty,
        "activity_date":   activity_date,
        "meeting_time":    None,
        "meeting_place":   merged.get("meeting_place"),
        "duration":        duration,
        "price":           price_str or None,
        "price_min":       price_min,
        "organizer_name":  None,
        "quota":           None,
        "destination":     None,
        "description":     (merged.get("description") or "")[:200] or None,
        "source_url":      merged.get("source_url", ""),
        "source_platform": "lvye",
        "cover_image":     merged.get("cover_image") or None,
        "raw_text":        (merged.get("raw_text") or "")[:2000],
        "status":          "pending",
    }

    # 清理空字符串
    return {k: (v if v != "" else None) for k, v in record.items()}


def crawl_lvye(max_pages: int = 3) -> list[dict]:
    """
    主入口：爬取绿野精选活动，直接返回可入库的结构化记录
    """
    all_records = []
    seen_urls = set()

    for list_url in LIST_URLS:
        for page in range(1, max_pages + 1):
            url = list_url if page == 1 else list_url + f"?page={page}"

            logger.info(f"正在爬取绿野列表: {url}")
            soup = fetch_page(url)
            if not soup:
                break

            items = parse_list_page(soup)
            if not items:
                logger.info(f"第 {page} 页无活动，停止翻页")
                break

            logger.info(f"第 {page} 页找到 {len(items)} 条活动")

            new_items = [i for i in items if i["source_url"] not in seen_urls]
            if not new_items:
                logger.info("无新活动，停止翻页")
                break

            for item in new_items:
                seen_urls.add(item["source_url"])
                logger.info(f"  抓取详情: {item['activity_name'][:30]}...")
                detail = parse_activity_detail(item["source_url"], item)
                record = build_activity_record(item, detail)
                all_records.append(record)
                logger.info(
                    f"    日期={record.get('activity_date')} "
                    f"类型={record.get('activity_type')} "
                    f"价格={record.get('price','?')}"
                )
                time.sleep(random.uniform(1, 2))

            time.sleep(random.uniform(2, 4))

    logger.info(f"绿野爬取完成，共 {len(all_records)} 条活动")
    return all_records


if __name__ == "__main__":
    results = crawl_lvye(max_pages=2)
    with open("lvye_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 条到 lvye_raw.json")
    # 打印前3条看效果
    for r in results[:3]:
        print(f"  {r['activity_name'][:40]} | {r['activity_date']} | {r['price']} | {r['activity_type']}")

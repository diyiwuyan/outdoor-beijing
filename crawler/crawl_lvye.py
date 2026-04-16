"""
绿野网 (lvye.cn) 活动爬虫
抓取精选活动列表（/lines/all）及详情页
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import logging
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
# 绿野精选活动列表，按北京/京郊筛选
# 参数说明：all-{目的地}-{类型}-{天数}-{价格}-{排序}-{页码}
# 直接用 /lines/all 获取全部，再用 /lines/all?city=1 筛选北京
LIST_URLS = [
    "https://www.lvye.cn/lines/all",           # 全部精选
]


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

    # 找所有 /lines/show_ 链接的父 li
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

            # 标题：.bt 或 img alt
            title_el = li.select_one(".bt") if li else None
            if title_el:
                title = title_el.get_text(strip=True)
            else:
                img = link.select_one("img")
                title = img.get("alt", "").strip() if img else link.get_text(strip=True)

            if not title:
                continue

            # 封面图
            img_el = link.select_one("img")
            cover = ""
            if img_el:
                cover = img_el.get("src") or img_el.get("data-src") or ""

            # 日期（.dates span）
            date_el = li.select_one(".dates") if li else None
            date_text = date_el.get_text(strip=True).replace("团期：", "") if date_el else ""

            # 价格：列表页通常没有价格，留空，详情页再补
            price_text = ""

            # 简介（.ts）
            desc_el = li.select_one(".ts") if li else None
            desc_text = desc_el.get_text(strip=True) if desc_el else ""

            activities.append({
                "activity_name": title,
                "source_url": url,
                "date_text": date_text,
                "price": price_text,
                "description": desc_text,
                "cover_image": cover,
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
        h1 = soup.select_one("h1")
        if h1:
            detail["activity_name"] = h1.get_text(strip=True)

        # 价格：优先取 .new-price（含完整文字如 ￥3888.00起）
        price_el = soup.select_one(".new-price")
        if price_el:
            detail["price"] = price_el.get_text(strip=True)

        # 封面图
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img:
            detail["cover_image"] = og_img.get("content", "")
        else:
            first_img = soup.select_one(".dmp-banner img, .detail-main-pic img")
            if first_img:
                detail["cover_image"] = first_img.get("src", "")

        # 从页面正文提取 raw_text 供 LLM 解析
        # 优先取详情内容区，包含日期/集合地点等关键信息
        content_el = soup.select_one(".dmp-des, .detail-main, .product-content, .line-content, .line-show-main")
        if content_el:
            raw = content_el.get_text(separator="\n", strip=True)
        else:
            # 兜底：取 body 全文（去掉导航/脚本）
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            raw = soup.get_text(separator="\n", strip=True)
        # 把标题和日期拼到 raw_text 开头，确保 LLM 能提取
        prefix_parts = []
        h1 = soup.select_one("h1")
        if h1:
            prefix_parts.append("活动名称：" + h1.get_text(strip=True))
        # 价格也放进去
        if price_el:
            prefix_parts.append("价格：" + price_el.get_text(strip=True))
        detail["raw_text"] = "\n".join(prefix_parts) + "\n" + raw[:2500]

        # 尝试提取团期/集合地点等结构化字段
        # 绿野详情页通常在 .cp-show-msg 或 table 里
        info_rows = soup.select(".info-row, .detail-info tr, .cp-show-msg p")
        for row in info_rows:
            text = row.get_text(strip=True)
            if "团期" in text or "出发" in text:
                detail["date_text"] = text.replace("团期：", "").replace("出发日期：", "").strip()
            elif "集合" in text and ("地" in text or "点" in text):
                detail["meeting_place"] = text
            elif "费用" in text or "价格" in text:
                detail["price"] = text

    except Exception as e:
        logger.warning(f"解析详情页失败 {url}: {e}")

    return detail


def crawl_lvye(max_pages: int = 3) -> list[dict]:
    """
    主入口：爬取绿野精选活动
    max_pages: 每个列表 URL 最多爬取的页数
    """
    all_activities = []
    seen_urls = set()

    for list_url in LIST_URLS:
        for page in range(1, max_pages + 1):
            # 绿野翻页：/lines/all?page=2 或 /lines/all-...-{page}
            if page == 1:
                url = list_url
            else:
                url = list_url + f"?page={page}"

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
                detail = parse_activity_detail(item["source_url"])
                merged = {**item, **detail}
                all_activities.append(merged)
                time.sleep(random.uniform(1, 2))

            time.sleep(random.uniform(2, 4))

    logger.info(f"绿野爬取完成，共 {len(all_activities)} 条活动")
    return all_activities


if __name__ == "__main__":
    results = crawl_lvye(max_pages=2)
    with open("lvye_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 条到 lvye_raw.json")

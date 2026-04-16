"""
微信公众号文章爬虫（通过搜狗微信搜索）
无需登录，抓取近期北京户外活动相关文章
"""

import requests
from bs4 import BeautifulSoup
import json
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://weixin.sogou.com/",
}

# 搜狗微信搜索入口
SOGOU_SEARCH_URL = "https://weixin.sogou.com/weixin?type=2&query={query}&page={page}"

# 搜索关键词列表（覆盖主要活动类型）
SEARCH_KEYWORDS = [
    "北京徒步 活动 报名",
    "北京露营 活动 周末",
    "北京骑行 活动 招募",
    "北京攀岩 活动",
    "北京户外 活动 招募",
    "北京登山 活动",
    "北京皮划艇 活动",
    "北京滑雪 活动",
]


def fetch_page(url: str, retries: int = 3) -> Optional[BeautifulSoup]:
    """请求页面，失败自动重试"""
    for attempt in range(retries):
        try:
            time.sleep(random.uniform(2.0, 4.0))
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


def parse_sogou_results(soup: BeautifulSoup) -> list[dict]:
    """解析搜狗微信搜索结果页"""
    articles = []

    # 搜狗微信搜索结果结构
    items = soup.select(".news-box .news-list li, .txt-box")
    if not items:
        items = soup.select("li.news")

    for item in items:
        try:
            # 标题和链接
            title_el = item.select_one("h3 a, .txt-box h3 a")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")
            # 搜狗会做跳转，需要跟随重定向
            if not url.startswith("http"):
                continue

            # 摘要
            summary_el = item.select_one("p.txt-info, .txt-box p")
            summary = summary_el.get_text(strip=True) if summary_el else ""

            # 公众号名称
            account_el = item.select_one(".account, .s-p, span.all-time-y2")
            account = account_el.get_text(strip=True) if account_el else ""

            # 发布时间
            time_el = item.select_one(".s-p, .time, span[class*='time']")
            pub_time = time_el.get_text(strip=True) if time_el else ""

            # 封面图
            img_el = item.select_one("img")
            img_url = img_el.get("src", "") or img_el.get("data-src", "") if img_el else ""

            articles.append({
                "activity_name": title,
                "source_url": url,
                "summary": summary,
                "organizer_name": account,
                "pub_time": pub_time,
                "cover_image": img_url,
                "source_platform": "weixin",
            })
        except Exception as e:
            logger.warning(f"解析搜索结果条目失败: {e}")
            continue

    return articles


def fetch_article_content(url: str) -> dict:
    """
    抓取微信公众号文章正文
    注意：微信文章需要跟随搜狗跳转链接
    """
    result = {"source_url": url, "raw_text": "", "cover_image": ""}

    try:
        time.sleep(random.uniform(1.5, 3.0))
        # 跟随重定向获取真实微信文章URL
        resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        resp.encoding = "utf-8"
        final_url = resp.url
        result["source_url"] = final_url  # 更新为真实URL

        soup = BeautifulSoup(resp.text, "html.parser")

        # 微信文章正文容器
        content_el = soup.select_one(
            "#js_content, .rich_media_content, [id*='content']"
        )
        if content_el:
            result["raw_text"] = content_el.get_text(separator="\n", strip=True)[:4000]

        # 封面图（og:image）
        og_img = soup.select_one('meta[property="og:image"]')
        if og_img:
            result["cover_image"] = og_img.get("content", "")

        # 文章标题（更准确）
        og_title = soup.select_one('meta[property="og:title"]')
        if og_title:
            result["activity_name"] = og_title.get("content", "")

    except Exception as e:
        logger.warning(f"抓取文章内容失败 {url}: {e}")

    return result


def is_recent(pub_time_text: str, days: int = 14) -> bool:
    """
    判断文章是否在近N天内发布
    搜狗返回的时间格式多样：'3天前'、'昨天'、'2024-01-15' 等
    """
    if not pub_time_text:
        return True  # 无法判断时默认保留

    now = datetime.now()
    text = pub_time_text.strip()

    try:
        if "分钟前" in text or "小时前" in text:
            return True
        if "昨天" in text:
            return True
        if "天前" in text:
            n = int(text.replace("天前", "").strip())
            return n <= days
        # 尝试解析日期格式
        for fmt in ("%Y-%m-%d", "%Y年%m月%d日", "%m月%d日"):
            try:
                pub_date = datetime.strptime(text[:10], fmt)
                return (now - pub_date).days <= days
            except ValueError:
                continue
    except Exception:
        pass

    return True  # 解析失败默认保留


def crawl_weixin(max_pages_per_keyword: int = 2, days: int = 14) -> list[dict]:
    """
    主入口：通过搜狗微信搜索抓取公众号文章
    max_pages_per_keyword: 每个关键词最多翻几页
    days: 只保留近N天的文章
    """
    all_articles = []
    seen_urls = set()

    for keyword in SEARCH_KEYWORDS:
        logger.info(f"搜索关键词: {keyword}")
        encoded_kw = quote(keyword)

        for page in range(1, max_pages_per_keyword + 1):
            url = SOGOU_SEARCH_URL.format(query=encoded_kw, page=page)
            soup = fetch_page(url)
            if not soup:
                break

            # 检测是否触发验证码
            if "验证码" in (soup.get_text() or "") or "captcha" in str(soup).lower():
                logger.warning(f"触发验证码，跳过关键词: {keyword}")
                break

            items = parse_sogou_results(soup)
            if not items:
                logger.info(f"  第{page}页无结果，停止")
                break

            logger.info(f"  第{page}页找到 {len(items)} 篇文章")

            for item in items:
                # 时间过滤
                if not is_recent(item.get("pub_time", ""), days=days):
                    continue
                # URL去重
                if item["source_url"] in seen_urls:
                    continue
                seen_urls.add(item["source_url"])

                # 抓取文章正文
                logger.info(f"    抓取正文: {item['activity_name'][:30]}...")
                content = fetch_article_content(item["source_url"])
                merged = {**item, **content}
                all_articles.append(merged)

            time.sleep(random.uniform(3, 6))  # 关键词间隔更长

        time.sleep(random.uniform(5, 10))  # 不同关键词间隔

    logger.info(f"微信爬取完成，共 {len(all_articles)} 篇文章")
    return all_articles


if __name__ == "__main__":
    results = crawl_weixin(max_pages_per_keyword=1)
    with open("weixin_raw.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 篇到 weixin_raw.json")

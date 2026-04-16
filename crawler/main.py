"""
主调度脚本：每天由 GitHub Actions 触发
流程：爬取绿野 + 爬取微信 → LLM提取 → 入库
"""

import json
import logging
import sys
from datetime import datetime

from crawl_lvye import crawl_lvye
from crawl_weixin import crawl_weixin
from llm_extract import extract_activities
from save_to_db import save_activities

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    start = datetime.now()
    logger.info("=" * 50)
    logger.info(f"开始每日爬取任务: {start.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    all_raw = []

    # Step 1: 爬取绿野
    logger.info("\n【Step 1】爬取绿野活动...")
    try:
        lvye_data = crawl_lvye(max_pages=5)
        logger.info(f"绿野爬取完成: {len(lvye_data)} 条")
        all_raw.extend(lvye_data)
    except Exception as e:
        logger.error(f"绿野爬取失败: {e}")

    # Step 2: 爬取微信公众号
    logger.info("\n【Step 2】爬取微信公众号文章...")
    try:
        weixin_data = crawl_weixin(max_pages_per_keyword=2, days=14)
        logger.info(f"微信爬取完成: {len(weixin_data)} 条")
        all_raw.extend(weixin_data)
    except Exception as e:
        logger.error(f"微信爬取失败: {e}")

    if not all_raw:
        logger.warning("本次爬取无数据，任务结束")
        return

    logger.info(f"\n原始数据合计: {len(all_raw)} 条")

    # Step 3: LLM结构化提取
    logger.info("\n【Step 3】LLM结构化提取...")
    try:
        extracted = extract_activities(all_raw)
        logger.info(f"LLM提取完成: {len(extracted)} 条有效活动")
    except Exception as e:
        logger.error(f"LLM提取失败: {e}")
        extracted = []

    if not extracted:
        logger.warning("无有效活动数据，任务结束")
        return

    # Step 4: 入库
    logger.info("\n【Step 4】写入数据库...")
    try:
        stats = save_activities(extracted)
    except Exception as e:
        logger.error(f"入库失败: {e}")
        stats = {}

    # 汇总
    elapsed = (datetime.now() - start).seconds
    logger.info("\n" + "=" * 50)
    logger.info(f"任务完成！耗时 {elapsed}s")
    logger.info(f"原始数据: {len(all_raw)} 条")
    logger.info(f"有效活动: {len(extracted)} 条")
    logger.info(f"入库统计: {stats}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()

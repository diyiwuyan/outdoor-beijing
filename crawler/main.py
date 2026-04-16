"""
主调度脚本：每天由 GitHub Actions 触发
流程：
  绿野 → 直接结构化（不走 LLM）→ 入库
  微信 → LLM提取 → 入库
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

    all_to_save = []

    # ── Step 1: 绿野（直接结构化，不走 LLM）──────────────────
    logger.info("\n【Step 1】爬取绿野活动（规则解析，无需LLM）...")
    try:
        lvye_records = crawl_lvye(max_pages=5)
        logger.info(f"绿野爬取完成: {len(lvye_records)} 条，直接入库")
        all_to_save.extend(lvye_records)
    except Exception as e:
        logger.error(f"绿野爬取失败: {e}", exc_info=True)

    # ── Step 2: 微信公众号（走 LLM 提取）────────────────────
    logger.info("\n【Step 2】爬取微信公众号文章...")
    weixin_raw = []
    try:
        weixin_raw = crawl_weixin(max_pages_per_keyword=2, days=14)
        logger.info(f"微信爬取完成: {len(weixin_raw)} 条原始文章")
    except Exception as e:
        logger.error(f"微信爬取失败: {e}", exc_info=True)

    if weixin_raw:
        logger.info("\n【Step 3】LLM结构化提取微信文章...")
        try:
            weixin_extracted = extract_activities(weixin_raw)
            logger.info(f"LLM提取完成: {len(weixin_extracted)} 条有效活动")
            all_to_save.extend(weixin_extracted)
        except Exception as e:
            logger.error(f"LLM提取失败: {e}", exc_info=True)
    else:
        logger.info("\n【Step 3】微信无数据，跳过LLM提取")

    # ── Step 4: 入库 ─────────────────────────────────────────
    if not all_to_save:
        logger.warning("本次爬取无数据，任务结束")
        return

    logger.info(f"\n【Step 4】写入数据库，共 {len(all_to_save)} 条...")
    try:
        stats = save_activities(all_to_save)
    except Exception as e:
        logger.error(f"入库失败: {e}", exc_info=True)
        stats = {}

    # ── 汇总 ─────────────────────────────────────────────────
    elapsed = (datetime.now() - start).seconds
    logger.info("\n" + "=" * 50)
    logger.info(f"任务完成！耗时 {elapsed}s")
    logger.info(f"待入库: {len(all_to_save)} 条")
    logger.info(f"入库统计: {stats}")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()

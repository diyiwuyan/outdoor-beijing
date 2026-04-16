"""
火山方舟 LLM 结构化提取模块
将爬取的原始文章文本提取为标准化活动字段
"""

import os
import json
import logging
import re
from typing import Optional
from datetime import datetime

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 火山方舟 API 配置
VOLC_API_KEY = os.environ.get("VOLC_API_KEY", "")
VOLC_API_URL = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
# 使用 Doubao-pro-32k，性价比最高，适合文本提取任务
VOLC_MODEL = os.environ.get("VOLC_MODEL", "doubao-pro-32k")

EXTRACT_PROMPT = """你是一个户外活动信息提取助手。请从以下文章中提取户外活动信息，输出标准JSON。

提取规则：
1. 若某字段在文章中未提及，填 null
2. activity_type 只能是以下之一：徒步、骑行、露营、攀岩、滑雪、皮划艇、其他
3. difficulty 只能是以下之一：入门、进阶、挑战、null
4. activity_date 格式为 YYYY-MM-DD，若只有月日则补充当前年份（{current_year}年）
5. price_min 提取费用中的最低数字（整数），免费填0，无法判断填null
6. is_outdoor_activity：判断这篇文章是否确实是在招募/宣传一个具体的户外活动（true/false）
7. destination 填目的地或路线名称，如"香山"、"怀柔水长城"

输出JSON格式（只输出JSON，不要其他文字）：
{{
  "is_outdoor_activity": true,
  "activity_name": "活动名称",
  "activity_type": "徒步",
  "difficulty": "入门",
  "activity_date": "2024-03-15",
  "meeting_time": "早7:30",
  "meeting_place": "地铁X号线X站X出口",
  "duration": "1天",
  "price": "AA制约80元，含门票",
  "price_min": 80,
  "organizer_name": "组织方名称",
  "quota": "20人",
  "destination": "香山",
  "description": "一句话简介（50字以内）"
}}

文章内容：
{text}"""


def call_llm(text: str, retries: int = 2) -> Optional[dict]:
    """调用火山方舟API提取结构化信息"""
    if not VOLC_API_KEY:
        logger.error("VOLC_API_KEY 未设置")
        return None

    if not text or len(text.strip()) < 50:
        logger.warning("文章内容过短，跳过LLM提取")
        return None

    current_year = datetime.now().year
    prompt = EXTRACT_PROMPT.format(
        text=text[:3000],  # 限制输入长度，控制token消耗
        current_year=current_year,
    )

    payload = {
        "model": VOLC_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,  # 低温度，保证输出稳定
        "max_tokens": 500,
    }
    headers = {
        "Authorization": f"Bearer {VOLC_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(retries):
        try:
            resp = requests.post(VOLC_API_URL, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 清理可能的markdown代码块包裹
            content = re.sub(r"^```json\s*", "", content)
            content = re.sub(r"\s*```$", "", content)

            result = json.loads(content)
            return result

        except json.JSONDecodeError as e:
            logger.warning(f"LLM返回非JSON内容 (第{attempt+1}次): {e}")
        except Exception as e:
            logger.warning(f"LLM调用失败 (第{attempt+1}次): {e}")
            if attempt == retries - 1:
                logger.error("LLM提取失败，放弃")

    return None


def extract_activities(raw_items: list[dict]) -> list[dict]:
    """
    批量处理原始爬取数据，通过LLM提取结构化字段
    raw_items: 爬虫输出的原始数据列表
    返回: 结构化活动列表（过滤掉非活动文章）
    """
    results = []
    total = len(raw_items)

    for i, item in enumerate(raw_items):
        logger.info(f"LLM提取 [{i+1}/{total}]: {item.get('activity_name', '')[:30]}...")

        raw_text = item.get("raw_text", "") or item.get("summary", "")
        if not raw_text:
            logger.info("  无正文内容，跳过")
            continue

        extracted = call_llm(raw_text)
        if not extracted:
            logger.info("  LLM提取失败，跳过")
            continue

        # 过滤非活动文章
        if not extracted.get("is_outdoor_activity", False):
            logger.info("  判断为非活动文章，跳过")
            continue

        # 合并：LLM提取结果优先，原始爬取数据作为补充
        merged = {
            # 来自爬虫的字段
            "source_url": item.get("source_url", ""),
            "source_platform": item.get("source_platform", ""),
            "cover_image": item.get("cover_image", ""),
            "raw_text": raw_text[:2000],  # 只保留前2000字
            # 来自LLM的字段（覆盖爬虫的粗糙提取）
            "activity_name": extracted.get("activity_name") or item.get("activity_name", ""),
            "activity_type": extracted.get("activity_type"),
            "difficulty": extracted.get("difficulty"),
            "activity_date": extracted.get("activity_date"),
            "meeting_time": extracted.get("meeting_time"),
            "meeting_place": extracted.get("meeting_place"),
            "duration": extracted.get("duration"),
            "price": extracted.get("price"),
            "price_min": extracted.get("price_min"),
            "organizer_name": extracted.get("organizer_name") or item.get("organizer_name", ""),
            "quota": extracted.get("quota"),
            "destination": extracted.get("destination"),
            "description": extracted.get("description"),
            "status": "pending",  # 默认待审核
        }

        # 清理空字符串为None
        merged = {k: (v if v != "" else None) for k, v in merged.items()}
        results.append(merged)
        logger.info(f"  ✓ 提取成功: {merged['activity_name'][:30]}")

    logger.info(f"LLM提取完成: {total} 条原始数据 → {len(results)} 条有效活动")
    return results


if __name__ == "__main__":
    # 本地调试：读取爬虫输出文件测试
    import sys

    input_file = sys.argv[1] if len(sys.argv) > 1 else "lvye_raw.json"
    with open(input_file, encoding="utf-8") as f:
        raw = json.load(f)

    results = extract_activities(raw[:5])  # 调试只处理前5条
    with open("extracted.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"已保存 {len(results)} 条到 extracted.json")

"""

一筆 JD -> {fit, reason}

這支**沒有進入點**，只被 import：

    pipeline.py -> judge / load_rules / load_profile / make_client / sha16 / MODEL
    eval.py     -> 一樣的那些
"""

import hashlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

MODEL = "gpt-5.6-sol"

RULES_PATH = Path("private/prompts/rules.md")
PROFILE_PATH = Path("private/profile.md")


class Judgement(BaseModel):
    """LLM 的輸出格式。"""

    fit: bool = Field(description="true = 適合投，false = 不適合")
    reason: str = Field(description="一句繁體中文，講決定性的那個理由")


def sha16(data: str | bytes) -> str:
    """內容 hash 取前 16 碼 —— 判斷用的每一份輸入（prompt、profile、dataset）都用這個標身分。"""
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()[
        :16
    ]


def _join(items: list) -> str:
    """把清單型的欄位攤成一行。

    同樣是清單，104 給的形狀卻不一致：major 是純字串，jobCategory / specialty /
    skill 是 {code, description}。
    """
    texts = (
        item
        if isinstance(item, str)
        else item.get("description") or item.get("name", "")
        for item in items
    )
    return "、".join(text for text in texts if text)


def jd_to_text(detail: dict) -> str:
    """一則職缺的 detail -> 送進 LLM 的 JD 純文字。

    只做攤平和挑欄位，不做任何判斷，空欄位直接不輸出。
    """
    header, condition, jd = detail["header"], detail["condition"], detail["jobDetail"]

    fields: list[tuple[str, str]] = [
        ("職稱", header["jobName"]),
        ("公司", header["custName"]),
        ("產業", detail["industry"]),
        ("公司規模", detail["employees"]),
        ("職務類別", _join(jd["jobCategory"])),
        ("管理責任", jd["manageResp"]),
        ("出差", jd["businessTrip"]),
        (
            "委託招募",
            f"由人力業者代為招募（{jd['delegatedRecruit']}）"
            if jd["delegatedRecruit"]
            else "",
        ),
        ("工作經歷要求", condition["workExp"]),
        ("學歷要求", condition["edu"]),
        ("科系要求", _join(condition["major"])),
        ("擅長工具", _join(condition["specialty"])),
        ("工作技能", _join(condition["skill"])),
        ("其他條件", condition["other"]),
    ]
    lines = [f"{name}：{value}" for name, value in fields if value]
    return "\n".join(lines) + f"\n\n【工作內容】\n{jd['jobDescription']}"


def load_rules() -> str:
    return RULES_PATH.read_text(encoding="utf-8")


def load_profile() -> str:
    return PROFILE_PATH.read_text(encoding="utf-8")


def make_client() -> OpenAI:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        sys.exit("找不到 OPENAI_API_KEY，請在 .env 加上這一行：OPENAI_API_KEY=sk-...")
    return OpenAI(api_key=api_key)


def judge(detail: dict, client: OpenAI, rules: str, profile: str) -> Judgement:
    response = client.responses.parse(
        model=MODEL,
        # temperature=0,
        instructions=f"{rules}\n\n# 我的 profile\n\n{profile}",
        input=jd_to_text(detail),
        text_format=Judgement,
    )
    result = response.output_parsed
    if result is None:
        raise RuntimeError(
            f"沒有拿到結構化輸出：{response.status} / {response.incomplete_details}"
        )
    return result

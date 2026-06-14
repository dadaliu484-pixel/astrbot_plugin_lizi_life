from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import date


MOODS = ("有点困", "心情不错", "安静地惦记你", "精力很好", "有一点嘴硬", "想拉你去做点正事")
KEYWORDS = ("别熬夜", "先喝水", "慢慢来", "少刷一会儿", "先做十分钟", "记得吃饭", "今天也算数")
REWARDS = ("李子少骂你一次", "得到一句认真夸奖", "今晚可以安心一点", "成就进度 +1", "获得三分钟休息券")


@dataclass(frozen=True)
class DailyState:
    mood: str
    possessiveness: int
    stubbornness: int
    missing_you: int
    keyword: str


def stable_rng(*parts: str) -> random.Random:
    raw = "\x1f".join(parts).encode("utf-8")
    seed = int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")
    return random.Random(seed)


def make_daily_state(day: date, user_key: str, character_name: str) -> DailyState:
    rng = stable_rng(day.isoformat(), user_key, character_name)
    return DailyState(
        mood=rng.choice(MOODS),
        possessiveness=rng.randint(35, 88),
        stubbornness=rng.randint(55, 96),
        missing_you=rng.randint(65, 99),
        keyword=rng.choice(KEYWORDS),
    )


def choose_task(tasks: list[str], day: date, user_key: str, draw_index: int) -> dict:
    clean = [item.strip() for item in tasks if item.strip()]
    if not clean:
        clean = ["喝一杯水，然后站起来活动三分钟"]
    rng = stable_rng(day.isoformat(), user_key, str(draw_index))
    task = rng.choice(clean)
    return {
        "title": task[:18],
        "content": task,
        "difficulty": rng.choice(("★", "★", "★★")),
        "minutes": rng.choice((3, 5, 8, 10)),
        "reward": rng.choice(REWARDS),
    }


def parse_group_characters(raw: str) -> list[tuple[str, str]]:
    result = []
    for line in raw.splitlines():
        if "|" not in line:
            continue
        name, prompt = line.split("|", 1)
        if name.strip() and prompt.strip():
            result.append((name.strip(), prompt.strip()))
    return result


def parse_health_endpoints(raw: str) -> list[tuple[str, str, str]]:
    result = []
    for line in raw.splitlines():
        parts = [part.strip() for part in line.split("|", 2)]
        if len(parts) >= 2 and parts[0] and parts[1]:
            result.append((parts[0], parts[1], parts[2] if len(parts) == 3 else ""))
    return result


def achievements_for(data: dict) -> list[str]:
    completed = int(data.get("completed_count", 0))
    diary_count = int(data.get("diary_count", 0))
    achievements = []
    if completed >= 1:
        achievements.append("启动成功：完成第一个小任务")
    if completed >= 3:
        achievements.append("渐入佳境：累计完成 3 个任务")
    if completed >= 10:
        achievements.append("不是偶然：累计完成 10 个任务")
    if diary_count >= 1:
        achievements.append("留下今天：生成第一篇日记")
    if data.get("checked_server"):
        achievements.append("系统在线：完成一次服务器巡检")
    return achievements

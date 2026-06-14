from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import psutil

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.agent.message import TextPart

from .core import (
    achievements_for,
    choose_task,
    make_daily_state,
    parse_group_characters,
    parse_health_endpoints,
    stable_rng,
)


class LiziLifePlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self._locks: dict[str, asyncio.Lock] = {}

    def _user_key(self, event: AstrMessageEvent) -> str:
        return str(event.unified_msg_origin)

    def _lock(self, key: str) -> asyncio.Lock:
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        return self._locks[key]

    async def _get_user(self, event: AstrMessageEvent) -> dict[str, Any]:
        key = f"user:{self._user_key(event)}"
        data = await self.get_kv_data(key, {})
        return data if isinstance(data, dict) else {}

    async def _save_user(self, event: AstrMessageEvent, data: dict[str, Any]) -> None:
        await self.put_kv_data(f"user:{self._user_key(event)}", data)

    async def _activity(self, event: AstrMessageEvent, text: str) -> None:
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            activities = data.setdefault("activities", {})
            today = date.today().isoformat()
            entries = activities.setdefault(today, [])
            entries.append({"time": datetime.now().strftime("%H:%M"), "text": text[:300]})
            activities[today] = entries[-30:]
            for old_day in sorted(activities)[:-14]:
                activities.pop(old_day, None)
            await self._save_user(event, data)

    async def _ask(self, event: AstrMessageEvent, prompt: str, fallback: str) -> str:
        try:
            provider_id = await self.context.get_current_chat_provider_id(
                umo=event.unified_msg_origin
            )
            if not provider_id:
                return fallback
            response = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            text = (response.completion_text or "").strip()
            return text or fallback
        except Exception as exc:
            logger.warning("lizi_life LLM call failed: %s", exc)
            return fallback

    def _state_text(self, event: AstrMessageEvent, target_day: date | None = None) -> str:
        target_day = target_day or date.today()
        name = self.config.get("character_name", "李子")
        state = make_daily_state(target_day, self._user_key(event), name)
        return (
            f"{name}今日状态\n\n"
            f"心情：{state.mood}\n"
            f"占有欲：{state.possessiveness}\n"
            f"嘴硬程度：{state.stubbornness}\n"
            f"想你程度：{state.missing_you}\n"
            f"今日关键词：{state.keyword}"
        )

    @filter.command("李子帮助", alias={"生活帮助", "lizihelp"})
    async def help_command(self, event: AstrMessageEvent):
        """查看李子生活陪伴插件命令。"""
        yield event.plain_result(
            "可用命令\n"
            "/状态\n/群聊 内容\n/吃什么 [预算]\n/抽任务\n/完成\n/成就\n"
            "/记录 内容\n/日记\n/昨日回忆\n/今日事件\n/睡觉\n/起床\n"
            "/今天科研 [主题]\n/status"
        )

    @filter.command("状态", alias={"今日状态"})
    async def daily_state(self, event: AstrMessageEvent):
        """查看角色今日状态。"""
        await self._activity(event, "查看了今日状态")
        yield event.plain_result(self._state_text(event))

    @filter.command("群聊")
    async def group_chat(self, event: AstrMessageEvent, message: str = ""):
        """让多个设定角色围绕一件事进行短群聊。"""
        if not message.strip():
            yield event.plain_result("用法：/群聊 我今天又刷了两个小时视频")
            return
        characters = parse_group_characters(self.config.get("group_characters", ""))
        cast = "\n".join(f"- {name}：{desc}" for name, desc in characters)
        fallback = "\n".join(
            f"{name}：先把这件事缩小成一个现在能做的小动作。"
            for name, _ in characters[:3]
        )
        prompt = (
            "请模拟一个自然的中文小群聊。不要写旁白，不要使用 Markdown 列表，每人说一到两句，"
            "既要有性格差异，也要最终给出一个十分钟内可执行的动作。不要羞辱或控制用户。\n\n"
            f"角色：\n{cast}\n\n用户说：{message}"
        )
        text = await self._ask(event, prompt, fallback)
        await self._activity(event, f"群聊主题：{message}")
        yield event.plain_result(text)

    @filter.command("吃什么", alias={"穷鬼套餐"})
    async def what_to_eat(self, event: AstrMessageEvent, budget: int = 20):
        """根据预算生成简单饮食建议。"""
        budget = max(5, min(budget, 500))
        preferences = self.config.get("food_preferences", "")
        fallback = (
            f"预算：{budget} 元\n"
            "建议：鸡蛋两个 + 一份当季蔬菜 + 主食；如果还有余量，加鸡腿或豆制品。\n"
            "优先保证蛋白质和蔬菜，不要只靠主食顶一整天。"
        )
        prompt = (
            "请给出一份简短、现实、能执行的中文今日饮食方案。包含午饭、晚饭和一句理由。"
            "严格尊重预算，不虚构精确营养数值，不提供医疗建议。\n"
            f"预算：{budget} 元\n偏好与常备食材：{preferences}"
        )
        text = await self._ask(event, prompt, fallback)
        await self._activity(event, f"查询 {budget} 元饮食方案")
        yield event.plain_result(text)

    @filter.command("抽任务")
    async def draw_task(self, event: AstrMessageEvent):
        """抽取一个低压力启动任务。"""
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            index = int(data.get("draw_count", 0)) + 1
            tasks = self.config.get("starter_tasks", "").splitlines()
            task = choose_task(tasks, date.today(), self._user_key(event), index)
            task["drawn_at"] = datetime.now().isoformat(timespec="seconds")
            task["done"] = False
            data["draw_count"] = index
            data["current_task"] = task
            await self._save_user(event, data)
        await self._activity(event, f"抽到任务：{task['content']}")
        yield event.plain_result(
            f"今日任务卡：{task['title']}\n\n"
            f"难度：{task['difficulty']}\n耗时：{task['minutes']} 分钟\n"
            f"奖励：{task['reward']}\n\n任务内容：\n{task['content']}\n\n"
            "做完后发送 /完成"
        )

    @filter.command("完成")
    async def complete_task(self, event: AstrMessageEvent):
        """完成当前抽取的任务。"""
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            task = data.get("current_task")
            if not task or task.get("done"):
                yield event.plain_result("现在没有待完成的任务，先发送 /抽任务。")
                return
            task["done"] = True
            task["completed_at"] = datetime.now().isoformat(timespec="seconds")
            data["completed_count"] = int(data.get("completed_count", 0)) + 1
            data["current_task"] = task
            count = data["completed_count"]
            await self._save_user(event, data)
        await self._activity(event, f"完成任务：{task['content']}")
        yield event.plain_result(
            f"完成了。{task['reward']}。\n这是你累计完成的第 {count} 个小任务。"
        )

    @filter.command("成就")
    async def achievements(self, event: AstrMessageEvent):
        """查看已经解锁的成就。"""
        data = await self._get_user(event)
        items = achievements_for(data)
        text = "\n".join(f"成就解锁：{item}" for item in items)
        yield event.plain_result(text or "还没有解锁成就。先从 /抽任务 开始。")

    @filter.command("记录")
    async def record(self, event: AstrMessageEvent, content: str = ""):
        """记录一条可用于日记摘要的事件。"""
        if not content.strip():
            yield event.plain_result("用法：/记录 今天整理完了 WRKY 序列")
            return
        await self._activity(event, content.strip())
        yield event.plain_result("记下了。生成 /日记 时会参考这件事。")

    async def _diary_for(self, event: AstrMessageEvent, target_day: date) -> str:
        data = await self._get_user(event)
        day_key = target_day.isoformat()
        cached = data.get("diaries", {}).get(day_key)
        if cached:
            return cached
        entries = data.get("activities", {}).get(day_key, [])
        if not entries:
            return f"{day_key} 还没有留下足够的记录。可以先用 /记录 写下一件事。"
        activity_text = "\n".join(f"{item['time']} {item['text']}" for item in entries)
        name = self.config.get("character_name", "李子")
        prompt = (
            f"你是{name}。根据下面的事件写一篇 80 到 160 字的私人日记。"
            "语气自然、有一点嘴硬但温柔，只总结已有事实，不编造聊天和经历，不渲染依赖。\n\n"
            f"日期：{day_key}\n事件：\n{activity_text}"
        )
        fallback = f"{day_key}\n今天记住了这些事：\n" + "\n".join(
            f"- {item['text']}" for item in entries[-5:]
        )
        diary = await self._ask(event, prompt, fallback)
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data.setdefault("diaries", {})[day_key] = diary
            data["diary_count"] = int(data.get("diary_count", 0)) + 1
            await self._save_user(event, data)
        return diary

    @filter.command("日记")
    async def diary(self, event: AstrMessageEvent):
        """生成或查看今天的日记摘要。"""
        yield event.plain_result(await self._diary_for(event, date.today()))

    @filter.command("昨日回忆")
    async def yesterday(self, event: AstrMessageEvent):
        """查看昨天的日记摘要。"""
        yield event.plain_result(
            await self._diary_for(event, date.today() - timedelta(days=1))
        )

    @filter.command("今日事件")
    async def daily_event(self, event: AstrMessageEvent):
        """生成角色关系网中的今日小事件。"""
        data = await self._get_user(event)
        day_key = date.today().isoformat()
        cached = data.get("daily_events", {}).get(day_key)
        if cached:
            yield event.plain_result(cached)
            return
        characters = parse_group_characters(self.config.get("group_characters", ""))
        cast = "、".join(name for name, _ in characters) or "李子、小夏、阿岚"
        rng = stable_rng(day_key, self._user_key(event), "event")
        seed_hint = rng.choice(("吃饭", "熬夜", "科研", "服务器", "出门", "整理房间"))
        fallback = f"小夏问起你今天有没有好好{seed_hint}，李子嘴上说不知道，转头却认真记了下来。"
        prompt = (
            f"为角色 {cast} 写一个 50 到 100 字的日常小事件，主题与“{seed_hint}”有关。"
            "温暖、克制、有生活感，不写宏大剧情，不制造嫉妒或控制关系。"
        )
        text = await self._ask(event, prompt, fallback)
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data.setdefault("daily_events", {})[day_key] = text
            await self._save_user(event, data)
        await self._activity(event, f"查看今日事件：{seed_hint}")
        yield event.plain_result(text)

    @filter.command("睡觉", alias={"晚安"})
    async def sleep_mode(self, event: AstrMessageEvent):
        """开启晚安短回复模式。"""
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data["sleep_mode"] = True
            await self._save_user(event, data)
        await self._activity(event, "进入晚安模式")
        yield event.plain_result("好了，不许再刷了。手机放远一点，明天醒了再找我。晚安。")

    @filter.command("起床", alias={"早安"})
    async def wake_mode(self, event: AstrMessageEvent):
        """关闭晚安模式。"""
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data["sleep_mode"] = False
            await self._save_user(event, data)
        await self._activity(event, "结束晚安模式")
        yield event.plain_result("早。先喝口水，别急着把今天想得太重。")

    @filter.command("今天科研", alias={"wrky", "导师汇报"})
    async def research(self, event: AstrMessageEvent, topic: str = ""):
        """把科研压力拆成一个小任务。"""
        context = self.config.get("research_context", "")
        fallback = "今天只做一步：整理一个文件夹，把序列、motif 图和系统树截图分别放好。限时十分钟。"
        prompt = (
            "你是务实的科研陪跑助手。把任务拆成今天只做一步、10 到 25 分钟可完成的动作。"
            "不要假装知道实验结果，不替用户编造数据。输出：今日一步、完成标准、卡住时怎么办。\n"
            f"科研背景：{context}\n用户补充：{topic or '没有补充'}"
        )
        text = await self._ask(event, prompt, fallback)
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data["used_research"] = True
            await self._save_user(event, data)
        await self._activity(event, f"科研陪跑：{topic or '默认任务'}")
        yield event.plain_result(text)

    async def _external_health(self) -> list[str]:
        endpoints = parse_health_endpoints(self.config.get("health_endpoints", ""))
        timeout = max(1, min(int(self.config.get("health_timeout", 5)), 30))
        if not endpoints:
            return []

        async def check(name: str, url: str, token: str) -> str:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            started = datetime.now()
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.get(url, headers=headers)
                elapsed = int((datetime.now() - started).total_seconds() * 1000)
                status = "正常" if 200 <= response.status_code < 400 else f"异常 HTTP {response.status_code}"
                return f"{name}：{status}（{elapsed}ms）"
            except Exception as exc:
                return f"{name}：不可用（{type(exc).__name__}）"

        return await asyncio.gather(*(check(*item) for item in endpoints))

    @filter.command("status", alias={"服务器状态", "系统状态"})
    async def server_status(self, event: AstrMessageEvent):
        """查看云服务器资源和配置的外部健康检查。"""
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu = psutil.cpu_percent(interval=0.2)
        boot = datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.now() - boot
        lines = [
            "服务器小管家",
            "",
            f"CPU：{cpu:.0f}%",
            f"内存：{memory.percent:.0f}%（可用 {memory.available / 1024**3:.1f} GB）",
            f"磁盘：{disk.percent:.0f}%（可用 {disk.free / 1024**3:.1f} GB）",
            f"运行时间：{uptime.days} 天 {uptime.seconds // 3600} 小时",
        ]
        lines.extend(await self._external_health())
        async with self._lock(self._user_key(event)):
            data = await self._get_user(event)
            data["checked_server"] = True
            await self._save_user(event, data)
        await self._activity(event, "检查服务器状态")
        yield event.plain_result("\n".join(lines))

    @filter.on_llm_request()
    async def inject_runtime_context(
        self, event: AstrMessageEvent, req: ProviderRequest
    ) -> None:
        """在普通聊天中临时注入晚安模式和可选的今日状态。"""
        data = await self._get_user(event)
        parts = []
        if data.get("sleep_mode"):
            parts.append(self.config.get("night_prompt", "请简短提醒用户休息。"))
        if self.config.get("inject_daily_state", True):
            parts.append(self._state_text(event))
        if parts:
            req.extra_user_content_parts.append(
                TextPart(
                    text="<lizi_life_context>\n"
                    + "\n\n".join(parts)
                    + "\n</lizi_life_context>"
                ).mark_as_temp()
            )

    async def terminate(self):
        self._locks.clear()


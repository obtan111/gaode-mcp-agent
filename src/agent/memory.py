import json
import os
import time
import threading
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

from src.utils.logger import setup_logger

logger = setup_logger("memory")


class LongTermMemory:
    """
    长期记忆系统，用于跨会话持久化存储用户信息和交互记忆。

    记忆类型：
    - user_profile: 用户画像（姓名、偏好、沟通风格等）
    - fact_memory: 事实记忆（用户提到的具体事实，如"我计划去长沙旅游"）
    - preference_memory: 偏好记忆（用户的喜好，如"喜欢吃辣"）
    - summary_memory: 会话摘要记忆（历史会话的摘要，用于上下文延续）

    存储策略：
    - 使用本地 JSON 文件存储（轻量级，无需数据库）
    - 支持自动摘要和记忆遗忘
    - 支持基于关键词和时间的检索
    - 线程安全的读写操作
    """

    def __init__(self, storage_path: Optional[str] = None):
        self._lock = threading.Lock()

        if storage_path is None:
            storage_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "..", "data", "memory"
            )
            os.makedirs(storage_dir, exist_ok=True)
            storage_path = os.path.join(storage_dir, "long_term_memory.json")

        self._storage_path = storage_path
        self._memory: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.exists(self._storage_path):
            try:
                with self._lock:
                    with open(self._storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                logger.info(f"Loaded memory from {self._storage_path}")
                return data
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load memory: {e}, starting fresh")

        return {
            "user_profile": {},
            "fact_memories": [],
            "preference_memories": [],
            "session_summaries": [],
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "total_memories": 0,
            }
        }

    def _save(self) -> None:
        self._memory["metadata"]["last_updated"] = datetime.now().isoformat()
        self._memory["metadata"]["total_memories"] = (
            len(self._memory["fact_memories"]) +
            len(self._memory["preference_memories"]) +
            len(self._memory["session_summaries"])
        )
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(self._memory, f, ensure_ascii=False, indent=2)
            logger.debug("Memory saved successfully")
        except IOError as e:
            logger.error(f"Failed to save memory: {e}")

    def update_user_profile(self, **kwargs) -> Dict[str, Any]:
        with self._lock:
            for key, value in kwargs.items():
                self._memory["user_profile"][key] = value
            self._save()
            logger.info(f"Updated user profile: {list(kwargs.keys())}")
            return self._memory["user_profile"].copy()

    def get_user_profile(self) -> Dict[str, Any]:
        with self._lock:
            return self._memory["user_profile"].copy()

    def add_fact_memory(
        self,
        content: str,
        context: Optional[str] = None,
        importance: int = 3,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            memory = {
                "id": f"fact_{int(time.time())}",
                "type": "fact",
                "content": content,
                "context": context,
                "importance": max(1, min(5, importance)),
                "tags": tags or [],
                "created_at": datetime.now().isoformat(),
                "access_count": 0,
                "last_accessed": None,
            }
            self._memory["fact_memories"].append(memory)
            self._save()
            logger.info(f"Added fact memory: {content[:50]}...")
            return memory

    def add_preference_memory(
        self,
        category: str,
        preference: str,
        intensity: int = 3,
    ) -> Dict[str, Any]:
        with self._lock:
            memory = {
                "id": f"pref_{int(time.time())}",
                "type": "preference",
                "category": category,
                "preference": preference,
                "intensity": max(1, min(5, intensity)),
                "created_at": datetime.now().isoformat(),
            }
            self._memory["preference_memories"].append(memory)
            self._save()
            logger.info(f"Added preference memory: {category}={preference}")
            return memory

    def add_session_summary(
        self,
        session_id: str,
        summary: str,
        key_topics: Optional[List[str]] = None,
        action_items: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            memory = {
                "id": f"sum_{int(time.time())}",
                "type": "summary",
                "session_id": session_id,
                "summary": summary,
                "key_topics": key_topics or [],
                "action_items": action_items or [],
                "created_at": datetime.now().isoformat(),
            }
            self._memory["session_summaries"].append(memory)

            if len(self._memory["session_summaries"]) > 50:
                self._memory["session_summaries"] = self._memory["session_summaries"][-50:]

            self._save()
            logger.info(f"Added session summary: {summary[:50]}...")
            return memory

    def search_memories(
        self,
        query: str,
        memory_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        results = []
        query_lower = query.lower()

        with self._lock:
            if memory_type in (None, "fact"):
                for memory in self._memory["fact_memories"]:
                    if query_lower in memory["content"].lower():
                        memory["access_count"] += 1
                        memory["last_accessed"] = datetime.now().isoformat()
                        results.append(memory)

            if memory_type in (None, "preference"):
                for memory in self._memory["preference_memories"]:
                    if (query_lower in memory.get("category", "").lower() or
                        query_lower in memory.get("preference", "").lower()):
                        results.append(memory)

            if memory_type in (None, "summary"):
                for memory in self._memory["session_summaries"]:
                    if query_lower in memory.get("summary", "").lower():
                        results.append(memory)

            if memory_type in (None, "profile"):
                profile = self._memory["user_profile"]
                for key, value in profile.items():
                    if query_lower in str(value).lower():
                        results.append({
                            "id": f"profile_{key}",
                            "type": "profile",
                            "key": key,
                            "value": value,
                        })

        results.sort(
            key=lambda m: m.get("importance", m.get("intensity", 0)),
            reverse=True,
        )
        results = results[:limit]

        logger.info(f"Memory search for '{query}' found {len(results)} results")
        return results

    def get_relevant_context(
        self,
        user_input: str,
        max_memories: int = 5,
    ) -> str:
        relevant = self.search_memories(user_input, limit=max_memories)
        profile = self.get_user_profile()

        if not relevant:
            context_parts = []
            if profile:
                profile_str = ", ".join([f"{k}: {v}" for k, v in profile.items()])
                context_parts.append(f"用户信息: {profile_str}")
            return "\n".join(context_parts) if context_parts else ""

        context_parts = []

        if profile:
            profile_str = ", ".join([f"{k}: {v}" for k, v in profile.items()])
            context_parts.append(f"用户画像: {profile_str}")

        for memory in relevant:
            mem_type = memory.get("type", "")
            if mem_type == "fact":
                context_parts.append(f"[过往事实] {memory['content']}")
            elif mem_type == "preference":
                context_parts.append(f"[偏好] {memory['category']}: {memory['preference']}")
            elif mem_type == "summary":
                context_parts.append(f"[历史会话摘要] {memory['summary']}")
            elif mem_type == "profile":
                context_parts.append(f"[用户信息] {memory['key']}: {memory['value']}")

        return "\n".join(context_parts)

    def get_all_memories_summary(self) -> Dict[str, Any]:
        with self._lock:
            profile = self._memory["user_profile"].copy()
            facts = self._memory["fact_memories"][-10:]
            preferences = self._memory["preference_memories"]
            recent_summaries = self._memory["session_summaries"][-3:]
            total_facts = len(self._memory["fact_memories"])
            total_preferences = len(self._memory["preference_memories"])
            total_summaries = len(self._memory["session_summaries"])

        return {
            "profile": profile,
            "recent_facts": facts,
            "preferences": preferences,
            "recent_summaries": recent_summaries,
            "stats": {
                "total_facts": total_facts,
                "total_preferences": total_preferences,
                "total_summaries": total_summaries,
            }
        }

    def forget_memory(self, memory_id: str) -> bool:
        with self._lock:
            for memory_list in [self._memory["fact_memories"], self._memory["preference_memories"], self._memory["session_summaries"]]:
                for i, memory in enumerate(memory_list):
                    if memory.get("id") == memory_id:
                        del memory_list[i]
                        self._save()
                        logger.info(f"Forgot memory: {memory_id}")
                        return True
        return False

    def cleanup_expired(self, max_facts: int = 100) -> int:
        with self._lock:
            if len(self._memory["fact_memories"]) > max_facts:
                excess = len(self._memory["fact_memories"]) - max_facts
                self._memory["fact_memories"] = self._memory["fact_memories"][excess:]
                self._save()
                logger.info(f"Cleaned up {excess} expired memories")
                return excess
        return 0


_memory_instance: Optional[LongTermMemory] = None


def get_memory() -> LongTermMemory:
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = LongTermMemory()
    return _memory_instance

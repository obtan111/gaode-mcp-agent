import json
import os
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from collections import defaultdict

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger

logger = setup_logger("schedule_mcp")


@MCPClient.register_tool("ScheduleMCP")
class ScheduleMCP(MCPClient):
    """
    日程待办 MCP 工具。
    
    提供日程和待办事项管理功能：
    - 创建/查看/更新/删除日程
    - 创建/查看/更新/删除待办事项
    - 按日期/状态筛选
    - 日程提醒
    """
    
    def __init__(self):
        super().__init__()
        self._data_dir = os.path.join(os.path.dirname(__file__), "..", "..", "data", "schedule")
        os.makedirs(self._data_dir, exist_ok=True)
        self._schedules_file = os.path.join(self._data_dir, "schedules.json")
        self._todos_file = os.path.join(self._data_dir, "todos.json")
        self._schedules = self._load_data(self._schedules_file)
        self._todos = self._load_data(self._todos_file)
    
    def _load_data(self, file_path: str) -> list:
        """加载数据文件。"""
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                logger.warning(f"Failed to load data from {file_path}, starting fresh")
        return []
    
    def _save_data(self, file_path: str, data: list) -> None:
        """保存数据文件。"""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    
    def _generate_id(self) -> str:
        """生成唯一 ID。"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    # ========== 日程管理 ==========
    
    def create_schedule(
        self,
        title: str,
        date: str,
        time: Optional[str] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        priority: int = 3,
        reminder: bool = True,
    ) -> dict:
        """
        创建日程。
        
        Args:
            title: 日程标题
            date: 日期（格式：YYYY-MM-DD）
            time: 时间（格式：HH:MM）
            location: 地点
            description: 描述
            priority: 优先级（1-5，1最高，5最低）
            reminder: 是否启用提醒
        
        Returns:
            dict: 创建的日程信息
        """
        try:
            datetime.strptime(date, "%Y-%m-%d")
            if time:
                datetime.strptime(time, "%H:%M")
        except ValueError as e:
            raise ValueError(f"Invalid date/time format: {e}")
        
        schedule = {
            "id": self._generate_id(),
            "title": title,
            "date": date,
            "time": time,
            "location": location,
            "description": description,
            "priority": priority,
            "reminder": reminder,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "status": "pending",
        }
        
        self._schedules.append(schedule)
        self._save_data(self._schedules_file, self._schedules)
        
        logger.info(f"Created schedule: {title} on {date}")
        return {"success": True, "schedule": schedule}
    
    def list_schedules(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        status: Optional[str] = None,
        priority: Optional[int] = None,
    ) -> dict:
        """
        列出日程。
        
        Args:
            start_date: 开始日期（格式：YYYY-MM-DD）
            end_date: 结束日期（格式：YYYY-MM-DD）
            status: 状态筛选（pending/completed/cancelled）
            priority: 优先级筛选
        
        Returns:
            dict: 包含日程列表和统计信息
        """
        result = self._schedules.copy()
        
        if start_date:
            result = [s for s in result if s["date"] >= start_date]
        if end_date:
            result = [s for s in result if s["date"] <= end_date]
        if status:
            result = [s for s in result if s["status"] == status]
        if priority:
            result = [s for s in result if s["priority"] == priority]
        
        # 按日期和时间排序
        result.sort(key=lambda s: (s["date"], s.get("time") or "00:00"))
        
        # 统计
        stats = {
            "total": len(result),
            "pending": len([s for s in result if s["status"] == "pending"]),
            "completed": len([s for s in result if s["status"] == "completed"]),
            "cancelled": len([s for s in result if s["status"] == "cancelled"]),
        }
        
        logger.info(f"list_schedules: returned {len(result)} items")
        return {"schedules": result, "stats": stats}
    
    def update_schedule(
        self,
        schedule_id: str,
        title: Optional[str] = None,
        date: Optional[str] = None,
        time: Optional[str] = None,
        location: Optional[str] = None,
        description: Optional[str] = None,
        priority: Optional[int] = None,
        status: Optional[str] = None,
    ) -> dict:
        """
        更新日程。
        
        Args:
            schedule_id: 日程 ID
            title: 新标题
            date: 新日期
            time: 新时间
            location: 新地点
            description: 新描述
            priority: 新优先级
            status: 新状态
        
        Returns:
            dict: 更新后的日程信息
        """
        for schedule in self._schedules:
            if schedule["id"] == schedule_id:
                if title is not None:
                    schedule["title"] = title
                if date is not None:
                    schedule["date"] = date
                if time is not None:
                    schedule["time"] = time
                if location is not None:
                    schedule["location"] = location
                if description is not None:
                    schedule["description"] = description
                if priority is not None:
                    schedule["priority"] = priority
                if status is not None:
                    schedule["status"] = status
                
                schedule["updated_at"] = datetime.now().isoformat()
                self._save_data(self._schedules_file, self._schedules)
                
                logger.info(f"Updated schedule: {schedule_id}")
                return {"success": True, "schedule": schedule}
        
        raise ValueError(f"Schedule not found: {schedule_id}")
    
    def delete_schedule(self, schedule_id: str) -> dict:
        """
        删除日程。
        
        Args:
            schedule_id: 日程 ID
        
        Returns:
            dict: 删除结果
        """
        for i, schedule in enumerate(self._schedules):
            if schedule["id"] == schedule_id:
                del self._schedules[i]
                self._save_data(self._schedules_file, self._schedules)
                
                logger.info(f"Deleted schedule: {schedule_id}")
                return {"success": True, "message": f"Schedule {schedule_id} deleted"}
        
        raise ValueError(f"Schedule not found: {schedule_id}")
    
    # ========== 待办管理 ==========
    
    def create_todo(
        self,
        title: str,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: int = 3,
        tags: Optional[List[str]] = None,
    ) -> dict:
        """
        创建待办事项。
        
        Args:
            title: 待办标题
            description: 描述
            due_date: 截止日期（格式：YYYY-MM-DD）
            priority: 优先级（1-5）
            tags: 标签列表
        
        Returns:
            dict: 创建的待办信息
        """
        if due_date:
            try:
                datetime.strptime(due_date, "%Y-%m-%d")
            except ValueError:
                raise ValueError(f"Invalid due_date format: {due_date}")
        
        todo = {
            "id": self._generate_id(),
            "title": title,
            "description": description,
            "due_date": due_date,
            "priority": priority,
            "tags": tags or [],
            "completed": False,
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        }
        
        self._todos.append(todo)
        self._save_data(self._todos_file, self._todos)
        
        logger.info(f"Created todo: {title}")
        return {"success": True, "todo": todo}
    
    def list_todos(
        self,
        completed: Optional[bool] = None,
        due_before: Optional[str] = None,
        priority: Optional[int] = None,
        tag: Optional[str] = None,
    ) -> dict:
        """
        列出待办事项。
        
        Args:
            completed: 完成状态筛选
            due_before: 截止日期筛选（返回在此日期前截止的待办）
            priority: 优先级筛选
            tag: 标签筛选
        
        Returns:
            dict: 包含待办列表和统计信息
        """
        result = self._todos.copy()
        
        if completed is not None:
            result = [t for t in result if t["completed"] == completed]
        if due_before:
            result = [t for t in result if t.get("due_date") and t["due_date"] <= due_before]
        if priority:
            result = [t for t in result if t["priority"] == priority]
        if tag:
            result = [t for t in result if tag in (t.get("tags") or [])]
        
        # 按优先级和截止日期排序
        result.sort(key=lambda t: (t["priority"], t.get("due_date") or "9999-12-31"))
        
        # 统计
        stats = {
            "total": len(result),
            "completed": len([t for t in result if t["completed"]]),
            "pending": len([t for t in result if not t["completed"]]),
            "overdue": len([t for t in result if not t["completed"] and t.get("due_date") and t["due_date"] < datetime.now().strftime("%Y-%m-%d")]),
        }
        
        logger.info(f"list_todos: returned {len(result)} items")
        return {"todos": result, "stats": stats}
    
    def update_todo(
        self,
        todo_id: str,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_date: Optional[str] = None,
        priority: Optional[int] = None,
        completed: Optional[bool] = None,
        tags: Optional[List[str]] = None,
    ) -> dict:
        """
        更新待办事项。
        
        Args:
            todo_id: 待办 ID
            title: 新标题
            description: 新描述
            due_date: 新截止日期
            priority: 新优先级
            completed: 完成状态
            tags: 新标签列表
        
        Returns:
            dict: 更新后的待办信息
        """
        for todo in self._todos:
            if todo["id"] == todo_id:
                if title is not None:
                    todo["title"] = title
                if description is not None:
                    todo["description"] = description
                if due_date is not None:
                    todo["due_date"] = due_date
                if priority is not None:
                    todo["priority"] = priority
                if completed is not None:
                    todo["completed"] = completed
                    if completed:
                        todo["completed_at"] = datetime.now().isoformat()
                    else:
                        todo["completed_at"] = None
                if tags is not None:
                    todo["tags"] = tags
                
                self._save_data(self._todos_file, self._todos)
                
                logger.info(f"Updated todo: {todo_id}")
                return {"success": True, "todo": todo}
        
        raise ValueError(f"Todo not found: {todo_id}")
    
    def delete_todo(self, todo_id: str) -> dict:
        """
        删除待办事项。
        
        Args:
            todo_id: 待办 ID
        
        Returns:
            dict: 删除结果
        """
        for i, todo in enumerate(self._todos):
            if todo["id"] == todo_id:
                del self._todos[i]
                self._save_data(self._todos_file, self._todos)
                
                logger.info(f"Deleted todo: {todo_id}")
                return {"success": True, "message": f"Todo {todo_id} deleted"}
        
        raise ValueError(f"Todo not found: {todo_id}")
    
    # ========== 统计与提醒 ==========
    
    def get_daily_summary(self, date: Optional[str] = None) -> dict:
        """
        获取每日摘要（日程+待办）。
        
        Args:
            date: 日期（格式：YYYY-MM-DD），默认为今天
        
        Returns:
            dict: 当日日程和待办汇总
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        schedules_today = [s for s in self._schedules if s["date"] == date and s["status"] != "cancelled"]
        todos_due_today = [t for t in self._todos if t.get("due_date") == date and not t["completed"]]
        
        # 即将到期的待办（7天内）
        upcoming_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        upcoming_todos = [
            t for t in self._todos
            if t.get("due_date") and t["due_date"] <= upcoming_date and not t["completed"]
        ]
        
        # 逾期待办
        overdue_date = datetime.now().strftime("%Y-%m-%d")
        overdue_todos = [
            t for t in self._todos
            if t.get("due_date") and t["due_date"] < overdue_date and not t["completed"]
        ]
        
        result = {
            "date": date,
            "schedules": {
                "count": len(schedules_today),
                "items": schedules_today,
            },
            "todos_due_today": {
                "count": len(todos_due_today),
                "items": todos_due_today,
            },
            "overdue_todos": {
                "count": len(overdue_todos),
                "items": overdue_todos,
            },
            "upcoming_todos": {
                "count": len(upcoming_todos),
                "items": upcoming_todos[:10],  # 最多显示10条
            },
        }
        
        logger.info(f"get_daily_summary: {date}")
        return result
    
    def search_schedule(self, keyword: str) -> dict:
        """
        搜索日程和待办。
        
        Args:
            keyword: 搜索关键词
        
        Returns:
            dict: 搜索结果
        """
        keyword_lower = keyword.lower()
        
        # 搜索日程
        matching_schedules = [
            s for s in self._schedules
            if keyword_lower in s["title"].lower()
            or (s.get("description") and keyword_lower in s["description"].lower())
            or (s.get("location") and keyword_lower in s["location"].lower())
        ]
        
        # 搜索待办
        matching_todos = [
            t for t in self._todos
            if keyword_lower in t["title"].lower()
            or (t.get("description") and keyword_lower in t["description"].lower())
            or any(keyword_lower in tag.lower() for tag in (t.get("tags") or []))
        ]
        
        result = {
            "keyword": keyword,
            "schedules": matching_schedules,
            "todos": matching_todos,
            "total": len(matching_schedules) + len(matching_todos),
        }
        
        logger.info(f"search_schedule: keyword='{keyword}', found={result['total']}")
        return result

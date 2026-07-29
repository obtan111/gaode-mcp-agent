from datetime import datetime, timedelta
from typing import Optional

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger

logger = setup_logger("time_mcp")


@MCPClient.register_tool("TimeMCP")
class TimeMCP(MCPClient):
    def get_current_time(self, timezone: str = "Asia/Shanghai") -> dict:
        """
        获取当前时间
        
        获取指定时区的当前日期和时间，返回格式化的时间字符串和时间戳。
        
        Args:
            timezone: 时区名称，默认为 "Asia/Shanghai"。常用时区包括：
                - Asia/Shanghai: 中国标准时间（UTC+8）
                - UTC: 协调世界时
                - America/New_York: 美国东部时间
                - Europe/London: 英国伦敦时间
        
        Returns:
            dict: 包含以下字段的字典：
                - datetime: 当前日期时间字符串（格式：YYYY-MM-DD HH:MM:SS）
                - date: 当前日期字符串（格式：YYYY-MM-DD）
                - time: 当前时间字符串（格式：HH:MM:SS）
                - timestamp: Unix时间戳（秒）
                - timezone: 使用的时区
                - weekday: 星期几（1-7，1表示周一）
                - week_number: 本年第几个星期
        """
        now = datetime.now()
        
        result = {
            "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "timestamp": int(now.timestamp()),
            "timezone": timezone,
            "weekday": now.isoweekday(),
            "week_number": now.isocalendar()[1],
        }
        
        logger.info(f"get_current_time called, result: {result}")
        return result

    def get_date_diff(self, date1: str, date2: str) -> dict:
        """
        计算两个日期之间的差值
        
        计算date1和date2之间相差的天数，可以是正数或负数。
        
        Args:
            date1: 第一个日期，格式为 "YYYY-MM-DD"
            date2: 第二个日期，格式为 "YYYY-MM-DD"
        
        Returns:
            dict: 包含以下字段的字典：
                - date1: 第一个日期
                - date2: 第二个日期
                - days_diff: 日期差值（date2 - date1），正数表示date2在date1之后
                - weeks_diff: 相差的周数（保留两位小数）
                - months_diff: 估算相差的月数（保留两位小数）
                - direction: 方向描述（"date2 is after date1" 或 "date2 is before date1" 或 "same date"）
        """
        try:
            d1 = datetime.strptime(date1, "%Y-%m-%d").date()
            d2 = datetime.strptime(date2, "%Y-%m-%d").date()
            
            delta_days = (d2 - d1).days
            delta_weeks = delta_days / 7.0
            delta_months = delta_days / 30.4375
            
            if delta_days > 0:
                direction = f"{date2} is after {date1}"
            elif delta_days < 0:
                direction = f"{date2} is before {date1}"
            else:
                direction = "same date"
            
            result = {
                "date1": date1,
                "date2": date2,
                "days_diff": delta_days,
                "weeks_diff": round(delta_weeks, 2),
                "months_diff": round(delta_months, 2),
                "direction": direction,
            }
            
            logger.info(f"get_date_diff called, date1={date1}, date2={date2}, result: {result}")
            return result
            
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            raise ValueError(f"Invalid date format. Please use 'YYYY-MM-DD'. Error: {e}")

    def get_future_date(self, days: int = 1, base_date: Optional[str] = None) -> dict:
        """
        日期推算：计算当前日期加上指定天数后的日期
        
        Args:
            days: 要添加的天数，可以是正数（未来）或负数（过去），默认为1（明天）
            base_date: 基准日期，格式为 "YYYY-MM-DD"。如果不提供，则使用当前日期
        
        Returns:
            dict: 包含以下字段的字典：
                - base_date: 基准日期（使用的起始日期）
                - days: 添加的天数
                - future_date: 推算后的日期（格式：YYYY-MM-DD）
                - future_datetime: 推算后的完整日期时间（格式：YYYY-MM-DD HH:MM:SS）
                - weekday: 推算后日期是星期几（1-7，1表示周一）
                - relative_description: 相对描述（如 "明天"、"昨天"、"3天后"、"5天前"）
        """
        if base_date:
            try:
                base = datetime.strptime(base_date, "%Y-%m-%d")
            except ValueError as e:
                logger.error(f"Invalid base_date format: {e}")
                raise ValueError(f"Invalid base_date format. Please use 'YYYY-MM-DD'. Error: {e}")
        else:
            base = datetime.now()
            base_date = base.strftime("%Y-%m-%d")
        
        future = base + timedelta(days=days)
        
        if days == 0:
            relative_desc = "今天"
        elif days == 1:
            relative_desc = "明天"
        elif days == -1:
            relative_desc = "昨天"
        elif days > 0:
            relative_desc = f"{days}天后"
        else:
            relative_desc = f"{abs(days)}天前"
        
        result = {
            "base_date": base_date,
            "days": days,
            "future_date": future.strftime("%Y-%m-%d"),
            "future_datetime": future.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": future.isoweekday(),
            "relative_description": relative_desc,
        }
        
        logger.info(f"get_future_date called, days={days}, base_date={base_date}, result: {result}")
        return result
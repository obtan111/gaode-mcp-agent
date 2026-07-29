import time
import hashlib
import json
from typing import Any, Dict, Optional, Tuple
from collections import OrderedDict
from threading import Lock


class MCPCache:
    """
    MCP 工具调用缓存系统。
    
    缓存策略：
    - 基于工具名+方法名+参数生成缓存键
    - 支持 TTL（Time To Live）自动过期
    - 支持最大缓存数量限制（LRU 淘汰）
    - 线程安全（使用 Lock）
    
    使用场景：
    - 高德天气查询（同一城市短时间内不变化）
    - 时间查询（可缓存 1 分钟）
    - RAG 知识库查询（短时间内重复查询可复用）
    """
    
    _instance = None
    _lock = Lock()
    
    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._rw_lock = Lock()
        
        # 默认配置
        self.default_ttl = 300  # 默认缓存 5 分钟
        self.max_size = 500     # 最大缓存条目数
        
        # 不同工具/方法的 TTL 配置
        self._ttl_config: Dict[str, int] = {
            # 时间类 - 短缓存
            "TimeMCP.get_current_time": 60,
            
            # 天气类 - 中等缓存
            "AmapMCP.get_weather": 600,         # 10 分钟
            "AmapMCP.get_weather_forecast": 900, # 15 分钟
            
            # 地理位置类 - 长缓存
            "AmapMCP.geocode": 1800,             # 30 分钟
            "AmapMCP.regeocode": 1800,           # 30 分钟
            "AmapMCP.search_place": 1800,        # 30 分钟
            "AmapMCP.search_around": 1800,       # 30 分钟
            
            # 交通类 - 中等缓存
            "AmapMCP.get_driving_route": 300,    # 5 分钟
            "AmapMCP.get_transit_route": 300,    # 5 分钟
            "AmapMCP.get_walking_route": 300,    # 5 分钟
            "AmapMCP.get_bicycling_route": 300,  # 5 分钟
            
            # 距离计算 - 短缓存
            "AmapMCP.get_distance": 600,         # 10 分钟
            
            # RAG 类 - 长缓存
            "RAGMCP.search_knowledge": 600,       # 10 分钟
            "RAGMCP.list_knowledge_bases": 300,   # 5 分钟
            
            # 住宿美食门票 - 长缓存
            "AmapMCP.search_hotel": 1800,        # 30 分钟
            "AmapMCP.search_food": 1800,         # 30 分钟
            "AmapMCP.search_ticket": 1800,       # 30 分钟
        }
    
    def _generate_cache_key(self, tool_name: str, method_name: str, parameters: Dict[str, Any]) -> str:
        """
        生成缓存键。
        
        格式：{tool_name}.{method_name}:{md5(parameters)}
        """
        try:
            param_str = json.dumps(parameters, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            param_str = str(sorted(parameters.items()))
        key_content = f"{tool_name}.{method_name}:{param_str}"
        return hashlib.md5(key_content.encode()).hexdigest()
    
    def _get_ttl(self, tool_name: str, method_name: str) -> int:
        """
        获取指定工具方法的 TTL。
        
        优先使用精确匹配，其次使用工具名前缀匹配，最后使用默认值。
        """
        full_name = f"{tool_name}.{method_name}"
        
        # 精确匹配
        if full_name in self._ttl_config:
            return self._ttl_config[full_name]
        
        # 工具名前缀匹配
        for key, ttl in self._ttl_config.items():
            if key.startswith(f"{tool_name}."):
                return ttl
        
        # 默认值
        return self.default_ttl
    
    def get(self, tool_name: str, method_name: str, parameters: Dict[str, Any]) -> Tuple[Optional[Any], bool]:
        """
        获取缓存值。
        
        返回：(缓存值, 是否命中缓存)
        """
        cache_key = self._generate_cache_key(tool_name, method_name, parameters)
        
        with self._rw_lock:
            if cache_key not in self._cache:
                return None, False
            
            value, expire_time = self._cache[cache_key]
            
            # 检查是否过期
            if time.time() > expire_time:
                # 过期，删除缓存
                del self._cache[cache_key]
                return None, False
            
            # 命中缓存，移到末尾（LRU 更新）
            self._cache.move_to_end(cache_key)
            return value, True
    
    def set(self, tool_name: str, method_name: str, parameters: Dict[str, Any], value: Any) -> None:
        """
        设置缓存值。
        
        包括 TTL 计算、LRU 淘汰逻辑。
        """
        cache_key = self._generate_cache_key(tool_name, method_name, parameters)
        ttl = self._get_ttl(tool_name, method_name)
        expire_time = time.time() + ttl
        
        with self._rw_lock:
            # 如果已存在，先删除
            if cache_key in self._cache:
                del self._cache[cache_key]
            
            # 检查是否超出最大容量
            while len(self._cache) >= self.max_size:
                # 淘汰最早的条目
                self._cache.popitem(last=False)
            
            # 添加新条目
            self._cache[cache_key] = (value, expire_time)
    
    def invalidate(self, tool_name: str = None, method_name: str = None) -> int:
        """
        失效指定工具的缓存。
        
        可选参数：
        - tool_name: 只失效该工具的缓存
        - method_name: 只失效指定方法的缓存
        
        返回：失效的缓存条目数
        """
        with self._rw_lock:
            count = 0
            keys_to_delete = []
            
            for key in self._cache:
                if tool_name is None:
                    keys_to_delete.append(key)
                elif f"{tool_name}." in key:
                    if method_name is None or f".{method_name}" in key:
                        keys_to_delete.append(key)
            
            for key in keys_to_delete:
                del self._cache[key]
                count += 1
            
            return count
    
    def clear(self) -> None:
        """清空所有缓存。"""
        with self._rw_lock:
            self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息。
        """
        with self._rw_lock:
            current_time = time.time()
            valid_count = sum(1 for _, expire_time in self._cache.values() if expire_time > current_time)
            expired_count = len(self._cache) - valid_count
            
            return {
                "total_entries": len(self._cache),
                "valid_entries": valid_count,
                "expired_entries": expired_count,
                "max_size": self.max_size,
                "default_ttl": self.default_ttl,
                "ttl_config_count": len(self._ttl_config),
            }
    
    def configure(self, **kwargs) -> None:
        """
        更新缓存配置。
        
        支持的配置项：
        - default_ttl: 默认 TTL（秒）
        - max_size: 最大缓存数量
        - ttl_config: TTL 配置字典
        """
        if "default_ttl" in kwargs:
            self.default_ttl = kwargs["default_ttl"]
        if "max_size" in kwargs:
            self.max_size = kwargs["max_size"]
        if "ttl_config" in kwargs:
            self._ttl_config.update(kwargs["ttl_config"])


# 全局缓存实例
_mcp_cache: Optional[MCPCache] = None


def get_mcp_cache() -> MCPCache:
    """获取 MCP 缓存单例。"""
    global _mcp_cache
    if _mcp_cache is None:
        _mcp_cache = MCPCache()
    return _mcp_cache

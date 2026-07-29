import json
import inspect
from typing import Dict, Any, List, Type, Optional, Callable
from uuid import UUID
from datetime import datetime

from src.config import Config
from src.utils.logger import setup_logger
from src.utils.retry import retry
from src.database.crud import log_mcp_call
from src.mcp.cache import get_mcp_cache

logger = setup_logger("mcp_client")


class MCPClient:
    _registered_tools: Dict[str, Type["MCPClient"]] = {}
    _cache = get_mcp_cache()

    def __init__(self):
        self.config = Config()
        self._tool_name = self.__class__.__name__

    @classmethod
    def register_tool(cls, name: str = None):
        def decorator(tool_class: Type["MCPClient"]) -> Type["MCPClient"]:
            tool_name = name or tool_class.__name__
            cls._registered_tools[tool_name] = tool_class
            logger.info(f"Registered MCP tool: {tool_name}")
            return tool_class
        return decorator

    @classmethod
    def get_registered_tools(cls) -> List[str]:
        return list(cls._registered_tools.keys())

    @classmethod
    def get_tool_instance(cls, tool_name: str) -> "MCPClient":
        if tool_name not in cls._registered_tools:
            raise ValueError(f"Tool not registered: {tool_name}")
        return cls._registered_tools[tool_name]()

    def get_tool_functions(self) -> List[Dict[str, Any]]:
        functions = []
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("_"):
                continue
            docstring = inspect.getdoc(method)
            if docstring:
                functions.append({
                    "name": name,
                    "description": docstring.split("\n")[0].strip(),
                    "parameters": self._parse_parameters(method),
                })
        return functions

    def _parse_parameters(self, method: Callable) -> Dict[str, Any]:
        signature = inspect.signature(method)
        params = {"type": "object", "properties": {}, "required": []}
        
        for param_name, param in signature.parameters.items():
            if param_name == "self":
                continue
            
            param_type = param.annotation
            if param_type == inspect.Parameter.empty:
                param_type = "string"
            elif param_type == int:
                param_type = "integer"
            elif param_type == float:
                param_type = "number"
            elif param_type == bool:
                param_type = "boolean"
            elif param_type == list:
                param_type = "array"
            elif param_type == dict:
                param_type = "object"
            else:
                param_type = "string"
            
            params["properties"][param_name] = {
                "type": param_type,
                "description": "",
            }
            
            if param.default == inspect.Parameter.empty:
                params["required"].append(param_name)
        
        return params

    @retry(max_retries=2, backoff_factor=1.5, initial_delay=0.5)
    def call_tool(
        self,
        method_name: str,
        parameters: Dict[str, Any],
        session_id: Optional[UUID] = None,
        timeout: int = 30,
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        if not hasattr(self, method_name):
            raise ValueError(f"Method not found: {method_name}")
        
        method = getattr(self, method_name)
        
        logger.info(f"Calling tool method: {self._tool_name}.{method_name}, params: {parameters}, timeout: {timeout}s")
        
        # 检查缓存
        if use_cache:
            cached_value, is_hit = self._cache.get(
                self._tool_name, method_name, parameters
            )
            if is_hit:
                logger.info(f"Cache hit for {self._tool_name}.{method_name}")
                return {"success": True, "data": cached_value, "cached": True}
        
        start_time = datetime.now()
        
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(method, **parameters)
                try:
                    result = future.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError(f"Tool call {self._tool_name}.{method_name} timed out after {timeout}s")
            
            # 成功执行，写入缓存
            if use_cache:
                self._cache.set(
                    self._tool_name, method_name, parameters, result
                )
            
            try:
                log_mcp_call(
                    tool_name=f"{self._tool_name}.{method_name}",
                    parameters=parameters,
                    result=result,
                    session_id=session_id,
                )
            except Exception as log_err:
                logger.warning(f"Failed to log MCP call: {str(log_err)}")
            
            elapsed_ms = (datetime.now() - start_time).total_seconds() * 1000
            logger.info(f"Tool call completed: {self._tool_name}.{method_name} in {elapsed_ms:.2f}ms")
            
            return {"success": True, "data": result, "cached": False}
        
        except Exception as e:
            try:
                log_mcp_call(
                    tool_name=f"{self._tool_name}.{method_name}",
                    parameters=parameters,
                    result={"error": str(e)},
                    session_id=session_id,
                )
            except Exception:
                pass
            raise

    @classmethod
    def dispatch(
        cls,
        tool_name: str,
        method_name: str,
        parameters: Dict[str, Any],
        session_id: Optional[UUID] = None,
    ) -> Dict[str, Any]:
        tool_instance = cls.get_tool_instance(tool_name)
        return tool_instance.call_tool(method_name, parameters, session_id)

    @classmethod
    def get_all_available_functions(cls) -> List[Dict[str, Any]]:
        all_functions = []
        for tool_name, tool_class in cls._registered_tools.items():
            tool_instance = tool_class()
            functions = tool_instance.get_tool_functions()
            for func in functions:
                func["tool_name"] = tool_name
                all_functions.append(func)
        return all_functions
"""
大语言模型工厂模块。

该模块负责创建和管理不同类型的大语言模型实例，支持：
1. DeepSeek 模型（通过 langchain_openai 或 REST API）
2. 智谱 GLM 模型（通过 zhipuai SDK 或 REST API）

核心类：
- ModelFactory: 模型工厂，单例模式，负责模型创建和缓存
- SimpleLLM: 简易 DeepSeek LLM 实现（REST API 降级方案）
- ZhipuChatModel: 智谱 GLM 模型实现，支持工具调用
"""

from typing import Optional, Dict, Any, List, Union, Iterator
from datetime import datetime, timedelta
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, AIMessage, ToolMessage
from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.outputs import ChatGeneration, ChatResult

from src.config import Config
from src.utils.logger import logger
from src.utils.retry import retry
from src.utils.exception import ServiceError, ValidationError


class ModelFactory:
    """
    模型工厂类，负责创建和缓存不同类型的大语言模型。
    
    采用单例模式确保全局只有一个实例，支持模型缓存避免重复创建。
    
    支持的模型类型：
    - deepseek: DeepSeek 对话模型
    - zhipu: 智谱 GLM 系列模型
    
    属性：
    - config: 配置对象，包含 API Key 等配置
    - _models: 模型缓存字典，key 为 "{model_type}_{model_name}"
    """
    
    _instance: Optional["ModelFactory"] = None  # 单例实例

    def __new__(cls, *args, **kwargs):
        """实现单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化模型工厂"""
        self.config = Config()
        self._models: Dict[str, tuple] = {}  # 模型缓存: {cache_key: (model, timestamp)}
        self._max_cache_size = 10
        self._cache_expiry_hours = 24

    def create_model(
        self,
        model_type: str,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """
        创建指定类型的大语言模型实例。
        
        优先从缓存获取，如果缓存不存在则创建新实例。
        
        参数：
        - model_type: 模型类型（deepseek / zhipu）
        - model_name: 模型名称（可选，使用默认值）
        - temperature: 温度参数（可选，使用配置默认值）
        - max_tokens: 最大 token 数（可选）
        
        返回：
        - BaseChatModel 实例
        
        异常：
        - ValidationError: 不支持的模型类型
        - ServiceError: API Key 未配置
        """
        # 构建缓存键
        cache_key = f"{model_type}_{model_name}"
        
        # 清理过期和超量的缓存
        self._cleanup_cache()
        
        # 优先从缓存获取（检查是否过期）
        if cache_key in self._models:
            cached_model, timestamp = self._models[cache_key]
            if datetime.now() - timestamp < timedelta(hours=self._cache_expiry_hours):
                return cached_model

        # 使用配置的温度参数或传入的参数
        temp = temperature if temperature is not None else self.config.MODEL_TEMPERATURE

        # 根据模型类型创建实例
        if model_type.lower() == "deepseek":
            model = self._create_deepseek_model(model_name, temp, max_tokens)
        elif model_type.lower() == "deepseek-vl":
            model = self._create_deepseek_model(model_name or "deepseek-vl", temp, max_tokens)
        elif model_type.lower() == "zhipu":
            model = self._create_zhipu_model(model_name, temp, max_tokens)
        elif model_type.lower() == "zhipu-4v":
            model = self._create_zhipu_model(model_name or "glm-4v-flash", temp, max_tokens)
        else:
            raise ValidationError(f"Unsupported model type: {model_type}")

        # 缓存模型实例（带时间戳）
        self._models[cache_key] = (model, datetime.now())
        logger.info(f"Created {model_type} model: {model_name}")
        return model
    
    def _cleanup_cache(self):
        """清理过期和超量的模型缓存"""
        now = datetime.now()
        expired_keys = []
        
        # 查找过期的缓存
        for key, (_, timestamp) in self._models.items():
            if now - timestamp >= timedelta(hours=self._cache_expiry_hours):
                expired_keys.append(key)
        
        # 删除过期缓存
        for key in expired_keys:
            del self._models[key]
            logger.debug(f"Removed expired model cache: {key}")
        
        # 如果缓存数量超过限制，删除最旧的
        if len(self._models) > self._max_cache_size:
            sorted_keys = sorted(self._models.keys(), key=lambda k: self._models[k][1])
            keys_to_remove = sorted_keys[:len(self._models) - self._max_cache_size]
            for key in keys_to_remove:
                del self._models[key]
                logger.debug(f"Removed oldest model cache to limit size: {key}")

    def _create_deepseek_model(
        self,
        model_name: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
    ) -> BaseChatModel:
        """
        创建 DeepSeek 模型实例。
        
        优先使用 langchain_openai.ChatOpenAI，降级使用 SimpleLLM（REST API）。
        
        参数：
        - model_name: 模型名称（默认 deepseek-chat）
        - temperature: 温度参数
        - max_tokens: 最大 token 数
        
        返回：
        - BaseChatModel 实例
        """
        api_key = self.config.DEEPSEEK_API_KEY
        if not api_key:
            raise ServiceError("DEEPSEEK_API_KEY is not configured")

        try:
            # 优先使用 langchain_openai
            from langchain_openai import ChatOpenAI
            model = model_name or "deepseek-v4-flash"
            return ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
                # 关闭 v4-flash 思考模式：思维链会让输出 token 翻倍、延迟翻倍，
                # 且会吃掉 max_tokens 预算导致正式回答被截断
                model_kwargs={"thinking": {"type": "disabled"}},
            )
        except ImportError:
            # 降级使用 SimpleLLM
            logger.warning("langchain_openai not installed, using SimpleLLM fallback")
            return SimpleLLM(api_key=api_key, model=model_name or "deepseek-v4-flash")

    def _create_zhipu_model(
        self,
        model_name: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
    ) -> "ZhipuChatModel":
        """
        创建智谱 GLM 模型实例。
        
        参数：
        - model_name: 模型名称（默认 glm-4）
        - temperature: 温度参数
        - max_tokens: 最大 token 数
        
        返回：
        - ZhipuChatModel 实例
        """
        api_key = self.config.ZHIPU_API_KEY
        if not api_key:
            raise ServiceError("ZHIPU_API_KEY is not configured")

        model = model_name or "glm-4"
        return ZhipuChatModel(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            api_key=api_key,
        )

    def get_supported_models(self) -> List[str]:
        """
        获取支持的模型类型列表。
        
        返回：
        - 模型类型列表 ["deepseek", "deepseek-vl", "zhipu", "zhipu-4v"]
        """
        return ["deepseek", "deepseek-vl", "zhipu", "zhipu-4v"]


class SimpleLLM(BaseChatModel):
    """
    简易 DeepSeek LLM 实现，直接调用 REST API。
    
    作为 langchain_openai 不可用时的降级方案，实现了 BaseChatModel 接口。
    支持多模态输入（图片），通过 additional_kwargs 传递 image_urls。
    
    属性：
    - api_key: DeepSeek API Key
    - model: 模型名称（默认 deepseek-chat）
    - temperature: 温度参数（默认 0.7）
    - max_tokens: 最大 token 数（可选）
    """
    api_key: str
    model: str = "deepseek-chat"
    temperature: float = 0.7
    max_tokens: Optional[int] = None

    def __init__(self, **kwargs):
        """初始化 SimpleLLM"""
        super().__init__(**kwargs)

    def _format_messages(self, messages: List[Union[BaseMessage, Dict[str, Any]]]) -> list:
        """
        格式化消息列表，支持多模态输入（图片）。
        
        对于包含 image_urls 的消息，会将 content 转为多模态格式：
        [{"type": "text", "text": "..."}, {"type": "image_url", "image_url": {"url": "..."}}]
        
        参数：
        - messages: 消息列表
        
        返回：
        - 格式化后的消息列表
        """
        formatted_messages = []
        role_mapping = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}

        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                additional_kwargs = msg.get("additional_kwargs", {})
            else:
                role = role_mapping.get(msg.type, msg.type)
                content = msg.content if hasattr(msg, 'content') else str(msg)
                additional_kwargs = msg.additional_kwargs if hasattr(msg, 'additional_kwargs') else {}

            image_urls = additional_kwargs.get("image_urls", []) if additional_kwargs else []

            if image_urls and role == "user":
                content_parts = []
                text_content = content if isinstance(content, str) else str(content)
                if text_content:
                    content_parts.append({"type": "text", "text": text_content})
                for img_url in image_urls:
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": img_url}
                    })
                formatted_messages.append({"role": role, "content": content_parts})
            else:
                if isinstance(content, str):
                    formatted_messages.append({"role": role, "content": content})
                else:
                    formatted_messages.append({"role": role, "content": str(content)})

        return formatted_messages

    def _generate(
        self,
        messages: List[Union[BaseMessage, Dict[str, Any]]],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> AIMessage:
        """
        非流式生成：调用 DeepSeek REST API 获取完整响应。
        
        支持多模态输入（图片），通过 additional_kwargs.image_urls 传递。
        
        参数：
        - messages: 消息列表（支持 BaseMessage 或字典格式）
        - stop: 停止词列表（未使用）
        - run_manager: 回调管理器（未使用）
        
        返回：
        - AIMessage: AI 响应消息
        """
        import requests
        import json

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        formatted_messages = self._format_messages(messages)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "stream": False,
            # 关闭 v4-flash 思考模式：思维链使输出 token 翻倍、延迟翻倍
            "thinking": {"type": "disabled"},
        }
        
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        logger.info(f"Sending request to DeepSeek API, model={self.model}, messages_len={len(formatted_messages)}")
        logger.info(f"Request payload preview: {json.dumps(payload, ensure_ascii=False)[:500]}")
        
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        
        logger.info(f"DeepSeek API response status: {response.status_code}")
        if response.status_code != 200:
            logger.error(f"DeepSeek API error response: {response.text[:500]}")
        
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        from langchain_core.outputs import ChatGeneration, ChatResult
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    def _stream(
        self,
        messages: List[Union[BaseMessage, Dict[str, Any]]],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[AIMessage]:
        """
        流式生成：调用 DeepSeek REST API 获取流式响应。
        
        支持多模态输入（图片）。
        
        参数：
        - messages: 消息列表（支持 BaseMessage 或字典格式）
        - stop: 停止词列表（未使用）
        - run_manager: 回调管理器（未使用）
        
        返回：
        - Iterator[AIMessage]: AI 响应消息迭代器
        """
        import requests
        import json

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        formatted_messages = self._format_messages(messages)

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "temperature": self.temperature,
            "stream": True,
            # 关闭 v4-flash 思考模式，与 _generate 保持一致
            "thinking": {"type": "disabled"},
        }
        
        if self.max_tokens is not None:
            payload["max_tokens"] = self.max_tokens

        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
            stream=True,
        )
        response.raise_for_status()

        from langchain_core.outputs import ChatGenerationChunk
        from langchain_core.messages import AIMessageChunk

        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode("utf-8").replace("data: ", ""))
                    if data.get("choices"):
                        content = data["choices"][0]["delta"].get("content", "")
                        if content:
                            yield ChatGenerationChunk(message=AIMessageChunk(content=content))
                except (json.JSONDecodeError, ValueError):
                    continue

    @property
    def _llm_type(self) -> str:
        """返回模型类型标识"""
        return "simple-deepseek"


class ZhipuChatModel(BaseChatModel):
    """
    智谱 GLM 模型实现，支持工具调用、流式响应和多模态输入（图片）。
    
    优先使用 zhipuai SDK，降级使用 REST API。
    
    属性：
    - model: 模型名称（默认 glm-4），glm-4v 支持图片识别
    - temperature: 温度参数（默认 0.7）
    - max_tokens: 最大 token 数（可选）
    - api_key: 智谱 API Key
    - client: zhipuai SDK 客户端（如果可用）
    - _use_sdk: 是否使用 SDK（True 表示使用 SDK，False 表示使用 REST API）
    - _is_vision_model: 是否为视觉模型（glm-4v）
    """
    model: str = "glm-4"
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key: str
    client: Any = None

    def __init__(self, **kwargs):
        """初始化 ZhipuChatModel"""
        super().__init__(**kwargs)
        self._is_vision_model = any(kw in self.model.lower() for kw in ["glm-4v", "glm-4.5"])
        try:
            # 优先使用 zhipuai SDK
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
            self._use_sdk = True
        except ImportError:
            # 降级使用 REST API
            logger.warning("zhipuai SDK not installed, using REST API fallback")
            self._use_sdk = False

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        zhipu_messages = self._convert_messages(messages)

        if self._use_sdk:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=zhipu_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=False,
                **kwargs,
            )
            ai_message = self._convert_response(response)
        else:
            ai_message = self._generate_rest(zhipu_messages, **kwargs)
        
        return ChatResult(generations=[ChatGeneration(message=ai_message)])

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[AIMessage]:
        zhipu_messages = self._convert_messages(messages)

        if self._use_sdk:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=zhipu_messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
                **kwargs,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta = chunk.choices[0].delta
                    content = delta.content or ""
                    tool_calls = delta.tool_calls or []
                    yield AIMessage(content=content, tool_calls=self._convert_tool_calls(tool_calls))
        else:
            import requests
            import json

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }

            payload = {
                "model": self.model,
                "messages": zhipu_messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "stream": True,
            }

            response = requests.post(
                "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
                stream=True,
            )
            response.raise_for_status()

            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8").replace("data: ", ""))
                        if data.get("choices"):
                            delta = data["choices"][0]["delta"]
                            content = delta.get("content", "")
                            tool_calls = delta.get("tool_calls", [])
                            converted_tool_calls = self._convert_tool_calls(tool_calls) if tool_calls else []
                            yield AIMessage(content=content, tool_calls=converted_tool_calls)
                    except (json.JSONDecodeError, ValueError):
                        continue

    def _generate_rest(self, messages: List[Dict[str, Any]], **kwargs) -> AIMessage:
        import requests
        import json

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        payload.update(kwargs)

        response = requests.post(
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()

        content = data["choices"][0]["message"]["content"]
        return AIMessage(content=content)

    def _convert_messages(self, messages: List[Union[BaseMessage, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """
        将消息列表转换为智谱 API 格式。
        
        支持两种输入格式：
        1. BaseMessage 对象（langchain 标准格式）
        2. 字典格式 {"role": "...", "content": "..."}
        
        对于视觉模型（glm-4v），会自动将 image_urls 转换为多模态内容格式。
        
        参数：
        - messages: 消息列表（支持 BaseMessage 或字典格式）
        
        返回：
        - 智谱 API 格式的消息列表
        """
        zhipu_messages = []
        role_mapping = {"human": "user", "ai": "assistant", "system": "system", "tool": "tool"}
        
        for msg in messages:
            if isinstance(msg, dict):
                role = msg.get("role", "user")
                content = msg.get("content", "")
                additional_kwargs = msg.get("additional_kwargs", {})
                msg_type = role
            else:
                msg_type = msg.type
                role = role_mapping.get(msg.type, msg.type)
                content = msg.content if hasattr(msg, 'content') else str(msg)
                additional_kwargs = msg.additional_kwargs if hasattr(msg, 'additional_kwargs') else {}
            
            if msg_type == "human" or role == "user":
                if self._is_vision_model and isinstance(content, str):
                    content_parts = []
                    remaining_content = content
                    
                    import re
                    image_pattern = r'\[图片已上传\]\s*'
                    has_image = bool(re.search(image_pattern, remaining_content))
                    
                    if has_image:
                        remaining_content = re.sub(image_pattern, '', remaining_content).strip()
                    
                    if remaining_content:
                        content_parts.append({"type": "text", "text": remaining_content})
                    
                    image_urls = additional_kwargs.get("image_urls", [])
                    for img_url in image_urls:
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {"url": img_url}
                        })
                    
                    if content_parts:
                        zhipu_messages.append({"role": role, "content": content_parts})
                    else:
                        zhipu_messages.append({"role": role, "content": ""})
                else:
                    zhipu_messages.append({"role": role, "content": content})
            elif msg_type == "ai" or role == "assistant":
                content = content or ""
                tool_calls = []
                if isinstance(msg, dict):
                    tc_list = msg.get("tool_calls", [])
                    for tc in tc_list:
                        tool_calls.append({
                            "id": tc.get("id", ""),
                            "type": "function",
                            "function": {
                                "name": tc.get("name", ""),
                                "arguments": tc.get("arguments", ""),
                            },
                        })
                elif hasattr(msg, 'tool_calls') and msg.tool_calls:
                    for tc in msg.tool_calls:
                        tool_calls.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": tc["arguments"],
                            },
                        })
                
                zhipu_messages.append({
                    "role": role,
                    "content": content,
                    "tool_calls": tool_calls if tool_calls else None,
                })
            elif msg_type == "tool" or role == "tool":
                zhipu_messages.append({
                    "role": "tool",
                    "content": content,
                    "tool_call_id": additional_kwargs.get("tool_call_id", ""),
                })
            elif msg_type == "system" or role == "system":
                zhipu_messages.append({"role": "system", "content": content})
            else:
                zhipu_messages.append({"role": "user", "content": str(content)})
        
        return zhipu_messages

    def _convert_response(self, response: Any) -> AIMessage:
        choice = response.choices[0]
        content = choice.message.content or ""
        tool_calls = self._convert_tool_calls(choice.message.tool_calls or [])
        return AIMessage(content=content, tool_calls=tool_calls)

    def _convert_tool_calls(self, tool_calls: List[Any]) -> List[Dict[str, Any]]:
        converted = []
        for tc in tool_calls:
            if hasattr(tc, "function"):
                converted.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })
        return converted

    @property
    def _llm_type(self) -> str:
        return "zhipu"

    def bind_tools(self, tools: List[BaseTool]) -> "ZhipuChatModel":
        function_defs = []
        for tool in tools:
            func = {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.args,
                    "required": tool.args.get("required", []),
                },
            }
            function_defs.append(func)

        self._function_calls = function_defs
        return self

    def invoke(self, input: Union[List[BaseMessage], str], **kwargs: Any) -> AIMessage:
        if isinstance(input, str):
            messages = [BaseMessage(content=input, type="human")]
        else:
            messages = input

        if hasattr(self, "_function_calls"):
            kwargs["tools"] = self._function_calls

        return super().invoke(messages, **kwargs)

    def stream(self, input: Union[List[BaseMessage], str], **kwargs: Any) -> Iterator[AIMessage]:
        if isinstance(input, str):
            messages = [BaseMessage(content=input, type="human")]
        else:
            messages = input

        if hasattr(self, "_function_calls"):
            kwargs["tools"] = self._function_calls

        return super().stream(messages, **kwargs)
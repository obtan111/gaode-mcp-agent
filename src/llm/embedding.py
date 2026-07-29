from typing import Optional, Dict, List, Any, Union
from langchain_core.embeddings import Embeddings

from src.config import Config
from src.utils.logger import logger
from src.utils.retry import retry
from src.utils.exception import ServiceError, ValidationError


class EmbeddingFactory:
    _instance: Optional["EmbeddingFactory"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.config = Config()
        self._embeddings: Dict[str, Embeddings] = {}
        self._default_dimension = 1024

    def create_embedding(
        self,
        embedding_type: str,
        model_name: Optional[str] = None,
    ) -> Embeddings:
        cache_key = f"{embedding_type}_{model_name}"
        if cache_key in self._embeddings:
            return self._embeddings[cache_key]

        if embedding_type.lower() == "openai":
            embedding = self._create_openai_embedding(model_name)
        elif embedding_type.lower() == "zhipu":
            embedding = self._create_zhipu_embedding(model_name)
        elif embedding_type.lower() == "deepseek":
            embedding = self._create_deepseek_embedding(model_name)
        else:
            raise ValidationError(f"Unsupported embedding type: {embedding_type}")

        self._embeddings[cache_key] = embedding
        logger.info(f"Created {embedding_type} embedding: {model_name}")
        return embedding

    def _create_openai_embedding(self, model_name: Optional[str]) -> Embeddings:
        try:
            from langchain_openai import OpenAIEmbeddings
            model = model_name or "text-embedding-3-small"
            return OpenAIEmbeddings(model=model)
        except ImportError:
            logger.warning("langchain_openai not installed, using SimpleEmbedding fallback")
            return SimpleEmbedding()

    def _create_deepseek_embedding(self, model_name: Optional[str]) -> Embeddings:
        api_key = self.config.DEEPSEEK_API_KEY
        if not api_key:
            raise ServiceError("DEEPSEEK_API_KEY is not configured")

        try:
            from langchain_openai import OpenAIEmbeddings
            model = model_name or "text-embedding"
            return OpenAIEmbeddings(
                model=model,
                api_key=api_key,
                base_url="https://api.deepseek.com/v1",
            )
        except ImportError:
            logger.warning("langchain_openai not installed, using DeepseekEmbedding fallback")
            return DeepseekEmbedding(api_key=api_key, model=model_name or "text-embedding")

    def _create_zhipu_embedding(self, model_name: Optional[str]) -> "ZhipuEmbeddings":
        api_key = self.config.ZHIPU_API_KEY
        if not api_key:
            raise ServiceError("ZHIPU_API_KEY is not configured")

        model = model_name or "text_embedding"
        return ZhipuEmbeddings(model=model, api_key=api_key)

    def get_supported_embeddings(self) -> List[str]:
        return ["openai", "zhipu", "deepseek"]

    @property
    def default_dimension(self) -> int:
        return self._default_dimension


class SimpleEmbedding(Embeddings):
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[0.0] * 1536 for _ in texts]

    def embed_query(self, text: str) -> List[float]:
        return [0.0] * 1536

    @property
    def dimensions(self) -> int:
        return 1536


class DeepseekEmbedding(Embeddings):
    def __init__(self, api_key: str, model: str = "text-embedding"):
        self.api_key = api_key
        self.model = model

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        import requests
        import json

        embeddings = []
        for text in texts:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            payload = {
                "model": self.model,
                "input": text,
            }
            response = requests.post(
                "https://api.deepseek.com/v1/embeddings",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            embeddings.append(data["data"][0]["embedding"])
        return embeddings

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def embed_query(self, text: str) -> List[float]:
        import requests
        import json

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "input": text,
        }
        response = requests.post(
            "https://api.deepseek.com/v1/embeddings",
            headers=headers,
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]

    @property
    def dimensions(self) -> int:
        return 1536


class ZhipuEmbeddings(Embeddings):
    model: str = "embedding-2"
    api_key: str

    def __init__(self, model: str = "embedding-2", api_key: str = "", **kwargs):
        super().__init__()
        self.model = model
        self.api_key = api_key
        try:
            from zhipuai import ZhipuAI
            self.client = ZhipuAI(api_key=self.api_key)
            self._use_sdk = True
        except ImportError:
            logger.warning("zhipuai SDK not installed, using REST API fallback")
            self._use_sdk = False

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        if self._use_sdk:
            for text in texts:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=text,
                )
                embedding = response.data[0].embedding
                embeddings.append(embedding)
        else:
            import requests
            import json

            for text in texts:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                }
                payload = {
                    "model": self.model,
                    "input": text,
                }
                response = requests.post(
                    "https://open.bigmodel.cn/api/paas/v4/embeddings",
                    headers=headers,
                    json=payload,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data["data"][0]["embedding"])
        return embeddings

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def embed_query(self, text: str) -> List[float]:
        if self._use_sdk:
            response = self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            return response.data[0].embedding
        else:
            import requests
            import json

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            payload = {
                "model": self.model,
                "input": text,
            }
            response = requests.post(
                "https://open.bigmodel.cn/api/paas/v4/embeddings",
                headers=headers,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"][0]["embedding"]

    @property
    def dimensions(self) -> int:
        return 1024
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch, MagicMock

from src.llm import ModelFactory, EmbeddingFactory, ZhipuChatModel, ZhipuEmbeddings
from src.utils.exception import ServiceError, ValidationError


class TestModelFactory:
    def test_create_deepseek_model(self):
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        
        factory = ModelFactory()
        
        model = factory.create_model("deepseek")
        
        assert model is not None
        assert model.model == "deepseek-chat"
        
        ModelFactory._instance = None

    def test_create_zhipu_model(self):
        os.environ["ZHIPU_API_KEY"] = "test-zhipu-key"
        
        factory = ModelFactory()
        
        model = factory.create_model("zhipu")
        
        assert model is not None
        assert isinstance(model, ZhipuChatModel)
        
        ModelFactory._instance = None

    def test_create_unsupported_model(self):
        factory = ModelFactory()
        
        with pytest.raises(ValidationError):
            factory.create_model("unsupported")
        
        ModelFactory._instance = None

    def test_create_model_with_custom_temperature(self):
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        
        factory = ModelFactory()
        
        model = factory.create_model("deepseek", temperature=0.5)
        
        assert model.temperature == 0.5
        
        ModelFactory._instance = None

    def test_model_cache(self):
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        
        factory = ModelFactory()
        
        model1 = factory.create_model("deepseek")
        model2 = factory.create_model("deepseek")
        
        assert model1 is model2
        
        ModelFactory._instance = None

    def test_deepseek_api_key_missing(self):
        os.environ["DEEPSEEK_API_KEY"] = ""
        
        factory = ModelFactory()
        
        with pytest.raises(ServiceError):
            factory.create_model("deepseek")
        
        ModelFactory._instance = None

    def test_zhipu_api_key_missing(self):
        os.environ["ZHIPU_API_KEY"] = ""
        
        factory = ModelFactory()
        
        with pytest.raises(ServiceError):
            factory.create_model("zhipu")
        
        ModelFactory._instance = None


class TestEmbeddingFactory:
    def test_create_zhipu_embedding(self):
        os.environ["ZHIPU_API_KEY"] = "test-zhipu-key"
        
        factory = EmbeddingFactory()
        
        embedding = factory.create_embedding("zhipu")
        
        assert embedding is not None
        assert isinstance(embedding, ZhipuEmbeddings)
        assert embedding.dimensions == 1024
        
        EmbeddingFactory._instance = None

    def test_create_deepseek_embedding(self):
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
        
        factory = EmbeddingFactory()
        
        embedding = factory.create_embedding("deepseek")
        
        assert embedding is not None
        
        EmbeddingFactory._instance = None

    def test_create_unsupported_embedding(self):
        factory = EmbeddingFactory()
        
        with pytest.raises(ValidationError):
            factory.create_embedding("unsupported")
        
        EmbeddingFactory._instance = None

    def test_embedding_cache(self):
        os.environ["ZHIPU_API_KEY"] = "test-zhipu-key"
        
        factory = EmbeddingFactory()
        
        embedding1 = factory.create_embedding("zhipu")
        embedding2 = factory.create_embedding("zhipu")
        
        assert embedding1 is embedding2
        
        EmbeddingFactory._instance = None

    def test_zhipu_embedding_api_key_missing(self):
        os.environ["ZHIPU_API_KEY"] = ""
        
        factory = EmbeddingFactory()
        
        with pytest.raises(ServiceError):
            factory.create_embedding("zhipu")
        
        EmbeddingFactory._instance = None

    def test_default_dimension(self):
        factory = EmbeddingFactory()
        
        assert factory.default_dimension == 1024
        
        EmbeddingFactory._instance = None


class TestZhipuChatModel:
    @patch('zhipuai.ZhipuAI')
    def test_zhipu_model_invoke(self, mock_zhipu):
        mock_client = Mock()
        mock_zhipu.return_value = mock_client
        
        mock_response = Mock()
        mock_choice = Mock()
        mock_message = Mock()
        mock_message.content = "Hello, world!"
        mock_message.tool_calls = []
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        
        model = ZhipuChatModel(api_key="test-key", model="glm-4")
        
        result = model.invoke("Hello")
        
        assert result is not None
        assert result.content == "Hello, world!"

    @patch('zhipuai.ZhipuAI')
    def test_zhipu_model_bind_tools(self, mock_zhipu):
        mock_client = Mock()
        mock_zhipu.return_value = mock_client
        
        model = ZhipuChatModel(api_key="test-key")
        
        tool_mock = Mock()
        tool_mock.name = "test_tool"
        tool_mock.description = "Test tool"
        tool_mock.args = {"type": "object", "properties": {"param": {"type": "string"}}, "required": ["param"]}
        
        bound_model = model.bind_tools([tool_mock])
        
        assert hasattr(bound_model, "_function_calls")
        assert len(bound_model._function_calls) == 1


class TestZhipuEmbeddings:
    @patch('zhipuai.ZhipuAI')
    def test_zhipu_embeddings_embed_query(self, mock_zhipu):
        mock_client = Mock()
        mock_zhipu.return_value = mock_client
        
        mock_response = Mock()
        mock_data = Mock()
        mock_data.embedding = [0.1] * 1024
        mock_response.data = [mock_data]
        mock_client.embeddings.create.return_value = mock_response
        
        embedding = ZhipuEmbeddings(api_key="test-key")
        
        result = embedding.embed_query("Hello, world!")
        
        assert len(result) == 1024
        mock_client.embeddings.create.assert_called_once()

    @patch('zhipuai.ZhipuAI')
    def test_zhipu_embeddings_embed_documents(self, mock_zhipu):
        mock_client = Mock()
        mock_zhipu.return_value = mock_client
        
        mock_response = Mock()
        mock_data = Mock()
        mock_data.embedding = [0.1] * 1024
        mock_response.data = [mock_data]
        mock_client.embeddings.create.return_value = mock_response
        
        embedding = ZhipuEmbeddings(api_key="test-key")
        
        result = embedding.embed_documents(["Hello", "World"])
        
        assert len(result) == 2
        assert len(result[0]) == 1024
        assert mock_client.embeddings.create.call_count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.config import Config, validate_config, load_and_validate_config


class TestConfig:
    def test_config_defaults(self):
        config = Config()
        assert config.MODEL_TEMPERATURE == 0.7
        assert config.CHUNK_SIZE == 512
        assert config.CHUNK_OVERLAP == 50
        assert config.RETRIEVE_TOP_K == 5
        assert config.MAX_TOOL_CALLS == 10
        assert config.LOG_LEVEL == "INFO"
        assert config.CONNECTION_POOL_SIZE == 10
        assert config.CONNECTION_TIMEOUT == 30
        assert config.HEARTBEAT_INTERVAL == 60

    def test_config_from_env(self):
        os.environ["MODEL_TEMPERATURE"] = "0.5"
        os.environ["CHUNK_SIZE"] = "256"
        
        config = Config()
        assert config.MODEL_TEMPERATURE == 0.5
        assert config.CHUNK_SIZE == 256


class TestConfigValidation:
    def test_validate_config_with_missing_required(self):
        original_url = os.getenv("SUPABASE_URL")
        original_key = os.getenv("SUPABASE_KEY")
        
        try:
            os.environ["SUPABASE_URL"] = ""
            os.environ["SUPABASE_KEY"] = ""
            
            config = Config()
            is_valid, errors = validate_config(config)
            assert not is_valid
            assert "SUPABASE_URL" in str(errors)
            assert "SUPABASE_KEY" in str(errors)
        finally:
            if original_url is not None:
                os.environ["SUPABASE_URL"] = original_url
            if original_key is not None:
                os.environ["SUPABASE_KEY"] = original_key

    def test_validate_config_with_no_llm_key(self):
        original_deepseek = os.getenv("DEEPSEEK_API_KEY")
        original_zhipu = os.getenv("ZHIPU_API_KEY")
        
        try:
            os.environ["DEEPSEEK_API_KEY"] = ""
            os.environ["ZHIPU_API_KEY"] = ""
            
            config = Config()
            is_valid, errors = validate_config(config)
            assert not is_valid
            assert "LLM API key" in str(errors)
        finally:
            if original_deepseek is not None:
                os.environ["DEEPSEEK_API_KEY"] = original_deepseek
            if original_zhipu is not None:
                os.environ["ZHIPU_API_KEY"] = original_zhipu

    def test_validate_config_with_invalid_temperature(self):
        original_temp = os.getenv("MODEL_TEMPERATURE")
        
        try:
            os.environ["MODEL_TEMPERATURE"] = "1.5"
            config = Config()
            is_valid, errors = validate_config(config)
            assert not is_valid
            assert "MODEL_TEMPERATURE" in str(errors)
            
            os.environ["MODEL_TEMPERATURE"] = "-0.1"
            config = Config()
            is_valid, errors = validate_config(config)
            assert not is_valid
        finally:
            if original_temp is not None:
                os.environ["MODEL_TEMPERATURE"] = original_temp

    def test_validate_config_with_invalid_log_level(self):
        original_level = os.getenv("LOG_LEVEL")
        
        try:
            os.environ["LOG_LEVEL"] = "INVALID"
            config = Config()
            is_valid, errors = validate_config(config)
            assert not is_valid
            assert "LOG_LEVEL" in str(errors)
        finally:
            if original_level is not None:
                os.environ["LOG_LEVEL"] = original_level

    def test_load_and_validate_config_success(self):
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_KEY"] = "test-key"
        os.environ["DEEPSEEK_API_KEY"] = "test-deepseek"
        
        config = load_and_validate_config()
        assert config is not None
        assert config.SUPABASE_URL == "https://test.supabase.co"

    def test_load_and_validate_config_failure(self):
        os.environ["SUPABASE_URL"] = ""
        os.environ["SUPABASE_KEY"] = ""
        
        with pytest.raises(ValueError):
            load_and_validate_config()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
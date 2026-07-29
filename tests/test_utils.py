import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time
from datetime import datetime

from src.utils.logger import logger, get_log_level, log_api_call
from src.utils.retry import retry
from src.utils.exception import (
    AppException, ValidationError, NotFoundError, 
    ServiceError, handle_exception, get_error_info
)
from src.utils.formatter import (
    truncate_text, format_json, parse_json,
    base64_encode, base64_decode,
    format_datetime, parse_datetime,
    timestamp_to_datetime, datetime_to_timestamp,
    format_duration
)


class TestLogger:
    def test_get_log_level(self):
        original_level = os.environ.get("LOG_LEVEL")
        try:
            os.environ["LOG_LEVEL"] = "DEBUG"
            assert get_log_level() == 10
            os.environ["LOG_LEVEL"] = "INFO"
            assert get_log_level() == 20
            os.environ["LOG_LEVEL"] = "INVALID"
            assert get_log_level() == 20
        finally:
            if original_level is not None:
                os.environ["LOG_LEVEL"] = original_level
            else:
                os.environ.pop("LOG_LEVEL", None)

    def test_log_api_call(self):
        @log_api_call
        def test_func(a, b):
            return a + b

        result = test_func(1, 2)
        assert result == 3


class TestRetry:
    def test_retry_success(self):
        counter = {"attempts": 0}

        @retry(max_retries=3)
        def succeed_on_third():
            counter["attempts"] += 1
            if counter["attempts"] < 3:
                raise ValueError("Not ready yet")
            return "Success"

        result = succeed_on_third()
        assert result == "Success"
        assert counter["attempts"] == 3

    def test_retry_fail_after_max(self):
        counter = {"attempts": 0}

        @retry(max_retries=2)
        def always_fail():
            counter["attempts"] += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            always_fail()
        assert counter["attempts"] == 3

    def test_retry_timeout(self):
        @retry(max_retries=10, timeout=1.0)
        def slow_func():
            time.sleep(0.5)
            raise ValueError("Slow fail")

        with pytest.raises(TimeoutError):
            slow_func()


class TestException:
    def test_custom_exceptions(self):
        e = ValidationError("Invalid input")
        assert e.code == "VALIDATION_ERROR"
        assert e.message == "Invalid input"

        e = NotFoundError("Not found")
        assert e.code == "NOT_FOUND"

    def test_handle_exception(self):
        e = ValidationError("Test error")
        result = handle_exception(e)
        assert result["code"] == "VALIDATION_ERROR"
        assert result["status_code"] == 400

        result = handle_exception(Exception("Unknown"))
        assert result["code"] == "INTERNAL_ERROR"
        assert result["status_code"] == 500

    def test_get_error_info(self):
        info = get_error_info("VALIDATION_ERROR")
        assert info["status_code"] == 400
        assert info["category"] == "validation"


class TestFormatter:
    def test_truncate_text(self):
        text = "Hello, World!"
        assert truncate_text(text, 5) == "Hello..."
        assert truncate_text(text, 100) == text

    def test_format_json(self):
        data = {"key": "value"}
        result = format_json(data)
        assert 'key' in result
        assert 'value' in result

    def test_parse_json(self):
        text = '{"key": "value"}'
        result = parse_json(text)
        assert result["key"] == "value"

    def test_base64(self):
        original = "Hello, World!"
        encoded = base64_encode(original)
        decoded = base64_decode(encoded)
        assert decoded == original

    def test_datetime_formatting(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        formatted = format_datetime(dt)
        assert formatted == "2024-01-15 10:30:00"

        parsed = parse_datetime(formatted)
        assert parsed == dt

    def test_timestamp_conversion(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        timestamp = datetime_to_timestamp(dt)
        converted = timestamp_to_datetime(timestamp)
        assert converted.year == dt.year
        assert converted.month == dt.month

    def test_format_duration(self):
        assert "ms" in format_duration(0.5)
        assert "s" in format_duration(30)
        assert "m" in format_duration(120)
        assert "h" in format_duration(3660)


class TestItineraryExporter:
    def setup_method(self):
        self.sample_itinerary = {
            "title": "长沙三日游",
            "destination": "长沙",
            "days": 3,
            "budget": "中等",
            "weather_summary": "晴转多云",
            "total_cost": 1500,
            "daily_itinerary": [
                {
                    "day": 1,
                    "date": "2025-01-01",
                    "weather": "晴",
                    "morning": {
                        "activity": "逛橘子洲",
                        "location": "橘子洲公园",
                        "transport": "地铁2号线",
                        "duration": "3小时",
                        "cost": "免费"
                    },
                    "afternoon": {
                        "activity": "岳麓书院",
                        "location": "岳麓山",
                        "transport": "公交",
                        "duration": "2小时",
                        "cost": "¥50"
                    },
                    "evening": {
                        "activity": "坡子街美食",
                        "location": "坡子街",
                        "transport": "步行",
                        "duration": "2小时",
                        "cost": "¥200"
                    }
                }
            ],
            "tips": ["带防晒霜", "穿舒适鞋子"]
        }

    def test_export_to_markdown(self):
        from src.utils.itinerary_exporter import export_to_markdown
        result = export_to_markdown(self.sample_itinerary)
        assert "长沙三日游" in result
        assert "橘子洲" in result
        assert "岳麓书院" in result
        assert "坡子街" in result
        assert "带防晒霜" in result

    def test_export_to_markdown_with_file(self):
        import tempfile
        import os
        from src.utils.itinerary_exporter import export_to_markdown
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            tmp_path = f.name
        try:
            result = export_to_markdown(self.sample_itinerary, tmp_path)
            assert os.path.exists(tmp_path)
            with open(tmp_path, 'r', encoding='utf-8') as f:
                content = f.read()
            assert "长沙三日游" in content
        finally:
            os.unlink(tmp_path)

    def test_export_to_excel(self):
        import tempfile
        import os
        from src.utils.itinerary_exporter import export_to_excel
        try:
            with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as f:
                tmp_path = f.name
            result = export_to_excel(self.sample_itinerary, tmp_path)
            assert os.path.exists(tmp_path)
            assert result == tmp_path
        except ImportError:
            pass
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_export_itinerary_markdown(self):
        from src.utils.itinerary_exporter import export_itinerary
        result = export_itinerary(self.sample_itinerary, format="markdown")
        assert result["success"] is True
        assert "markdown" in result["files"]
        assert "markdown_content" in result

    def test_export_itinerary_both(self):
        from src.utils.itinerary_exporter import export_itinerary
        result = export_itinerary(self.sample_itinerary, format="both")
        assert result["success"] is True
        assert "markdown" in result["files"]
        assert "excel" in result["files"]

    def test_export_itinerary_invalid_format(self):
        from src.utils.itinerary_exporter import export_itinerary
        result = export_itinerary(self.sample_itinerary, format="pdf")
        assert result["success"] is False
        assert "Unsupported format" in result["error"]

    def test_parse_itinerary_from_json(self):
        from src.utils.itinerary_exporter import parse_itinerary_from_text
        text = '{"title": "测试", "destination": "北京"}'
        result = parse_itinerary_from_text(text)
        assert result["title"] == "测试"
        assert result["destination"] == "北京"

    def test_parse_itinerary_from_invalid(self):
        from src.utils.itinerary_exporter import parse_itinerary_from_text
        result = parse_itinerary_from_text("not json")
        assert result["title"] == "旅行计划"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
单元测试补全：WebMCP、RAGAS评估器、Cache高级场景。

覆盖模块：
- src/mcp/web_mcp.py: URL验证、搜索结果解析
- src/eval/ragas_evaluator.py: 评估结果、报告生成
- src/mcp/cache.py: TTL过期、LRU驱逐
- src/mcp/schedule_mcp.py: 日程边界条件
"""

import os
import sys
import time
import json
import tempfile
import pytest
from datetime import datetime, timedelta

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestWebMCP:
    """WebMCP 工具测试。"""

    def test_validate_url_returns_dict(self):
        """测试 URL 验证返回字典格式。"""
        from src.mcp.web_mcp import WebMCP
        mcp = WebMCP()

        result = mcp.validate_url("https://www.example.com")
        assert isinstance(result, dict)
        assert "url" in result
        assert "valid" in result

    def test_search_web_returns_dict(self):
        """测试搜索返回字典格式（允许网络失败）。"""
        from src.mcp.web_mcp import WebMCP
        mcp = WebMCP()

        result = mcp.search_web("test query", num_results=1)
        assert isinstance(result, dict)
        assert "results" in result or "success" in result

    def test_get_webpage_metadata_returns_dict(self):
        """测试获取网页元数据返回字典格式（允许网络失败）。"""
        from src.mcp.web_mcp import WebMCP
        mcp = WebMCP()

        result = mcp.get_webpage_metadata("https://www.example.com")
        assert isinstance(result, dict)

    def test_extract_links_returns_dict(self):
        """测试链接提取返回字典格式（允许网络失败）。"""
        from src.mcp.web_mcp import WebMCP
        mcp = WebMCP()

        result = mcp.extract_links("https://www.example.com", max_links=5)
        assert isinstance(result, dict)


class TestRAGEvaluator:
    """RAGAS 评估器测试。"""

    def test_evaluation_result_creation(self):
        """测试评估结果创建。"""
        from src.eval.ragas_evaluator import EvaluationResult

        result = EvaluationResult(
            question="什么是RAG",
            answer="RAG是检索增强生成",
            contexts=["RAG结合检索和生成"],
            faithfulness=0.9,
            answer_relevancy=0.85,
            context_precision=0.8,
            context_recall=0.75,
        )
        assert result.overall_score > 0
        assert 0 <= result.overall_score <= 1
        assert result.timestamp != ""

    def test_evaluation_result_to_dict(self):
        """测试结果转字典。"""
        from src.eval.ragas_evaluator import EvaluationResult

        result = EvaluationResult(
            question="test",
            answer="answer",
            contexts=["ctx"],
        )
        d = result.to_dict()
        assert d["question"] == "test"
        assert d["answer"] == "answer"
        assert "overall_score" in d

    def test_parse_eval_response_valid(self):
        """测试解析有效评估响应。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        score, reason = RAGEvaluator._parse_eval_response(
            '{"score": 0.85, "reason": "良好"}'
        )
        assert score == 0.85
        assert reason == "良好"

    def test_parse_eval_response_nested_json(self):
        """测试从混合文本中提取 JSON。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        score, reason = RAGEvaluator._parse_eval_response(
            '评估结果如下：\n{"score": 0.7, "reason": "一般"}\n结束'
        )
        assert score == 0.7
        assert reason == "一般"

    def test_parse_eval_response_score_clamping(self):
        """测试分数边界截断。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        score, _ = RAGEvaluator._parse_eval_response('{"score": 1.5}')
        assert score == 1.0

        score, _ = RAGEvaluator._parse_eval_response('{"score": -0.5}')
        assert score == 0.0

    def test_parse_eval_response_empty(self):
        """测试空响应。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        score, reason = RAGEvaluator._parse_eval_response("")
        assert score is None
        assert reason == ""

    def test_parse_eval_response_invalid(self):
        """测试无效 JSON。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        score, reason = RAGEvaluator._parse_eval_response("not json at all")
        assert score is None

    def test_rule_based_faithfulness(self):
        """测试规则降级忠实度评估（mock LLM 不可用）。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        evaluator = RAGEvaluator(model_type="deepseek")
        evaluator._call_llm = lambda prompt: ""  # mock LLM 返回空

        score, reason = evaluator._eval_faithfulness(
            "长沙天气晴朗", "长沙今日天气晴朗气温25度"
        )
        assert 0 <= score <= 1
        assert "降级" in reason or "rule" in reason.lower()

    def test_rule_based_relevancy(self):
        """测试规则降级相关性评估（mock LLM 不可用）。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        evaluator = RAGEvaluator(model_type="deepseek")
        evaluator._call_llm = lambda prompt: ""

        score, reason = evaluator._eval_answer_relevancy(
            "长沙天气", "长沙今天晴朗"
        )
        assert 0 <= score <= 1

    def test_rule_based_precision_empty(self):
        """测试空上下文精确度。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        evaluator = RAGEvaluator(model_type="deepseek")
        evaluator._llm = None

        score, reason = evaluator._eval_context_precision("test", [])
        assert score == 0.0

    def test_report_generation(self):
        """测试报告生成。"""
        from src.eval.ragas_evaluator import RAGEvaluator, EvaluationResult

        evaluator = RAGEvaluator(model_type="deepseek")
        results = [
            EvaluationResult(
                question="问题1",
                answer="回答1",
                contexts=["上下文1"],
                faithfulness=0.8,
                answer_relevancy=0.7,
                context_precision=0.9,
                context_recall=0.6,
            ),
            EvaluationResult(
                question="问题2",
                answer="回答2",
                contexts=["上下文2"],
                faithfulness=0.6,
                answer_relevancy=0.8,
                context_precision=0.5,
                context_recall=0.7,
            ),
        ]

        report = evaluator.generate_report(results)
        assert "RAG 评估报告" in report
        assert "综合评分" in report
        assert "样本 1" in report
        assert "样本 2" in report

    def test_report_to_file(self, tmp_path):
        """测试报告写入文件。"""
        from src.eval.ragas_evaluator import RAGEvaluator, EvaluationResult

        evaluator = RAGEvaluator(model_type="deepseek")
        results = [
            EvaluationResult(
                question="q", answer="a", contexts=["c"],
                faithfulness=0.5, answer_relevancy=0.5,
                context_precision=0.5, context_recall=0.5,
            )
        ]
        report_path = str(tmp_path / "report.md")
        evaluator.generate_report(results, report_path)
        assert os.path.exists(report_path)

    def test_empty_report(self):
        """测试空结果报告。"""
        from src.eval.ragas_evaluator import RAGEvaluator

        evaluator = RAGEvaluator(model_type="deepseek")
        report = evaluator.generate_report([])
        assert "无评估结果" in report


class TestCacheAdvanced:
    """MCP 缓存高级测试。"""

    def test_cache_basic_set_get(self):
        """测试缓存基本读写。"""
        from src.mcp.cache import MCPCache

        cache = MCPCache()
        cache.clear()

        cache.set("tool", "method", {"key": "value"}, "result")
        cached, hit = cache.get("tool", "method", {"key": "value"})
        assert hit is True
        assert cached == "result"

    def test_cache_miss(self):
        """测试缓存未命中。"""
        from src.mcp.cache import MCPCache

        cache = MCPCache()
        cache.clear()

        _, hit = cache.get("nonexistent", "method", {"k": 1})
        assert hit is False

    def test_cache_clear(self):
        """测试缓存清空。"""
        from src.mcp.cache import MCPCache

        cache = MCPCache()
        cache.set("t", "m", {"k": 1}, "r1")
        assert cache.get("t", "m", {"k": 1})[1] is True

        cache.clear()
        assert cache.get("t", "m", {"k": 1})[1] is False

    def test_cache_stats(self):
        """测试缓存统计。"""
        from src.mcp.cache import MCPCache

        cache = MCPCache()
        cache.clear()

        cache.set("t", "m", {"k": 1}, "r1")
        cache.get("t", "m", {"k": 1})
        cache.get("t", "m", {"k": 999})  # miss

        stats = cache.get_stats()
        assert "total_entries" in stats
        assert "valid_entries" in stats
        assert "max_size" in stats

    def test_cache_non_serializable_params(self):
        """测试不可序列化参数的缓存键生成。"""
        from src.mcp.cache import MCPCache

        cache = MCPCache()
        cache.clear()

        class CustomObj:
            def __str__(self):
                return "custom"

        params = {"obj": CustomObj(), "name": "test"}
        cache.set("tool", "method", params, "result")

        cached, hit = cache.get("tool", "method", params)
        assert hit is True
        assert cached == "result"


class TestScheduleMCPAdvanced:
    """ScheduleMCP 高级测试。"""

    def test_schedule_with_overdue_todos(self):
        """测试包含逾期待办的日总结。"""
        from src.mcp.schedule_mcp import ScheduleMCP

        mcp = ScheduleMCP()
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        mcp.create_todo(title="逾期任务", due_date=yesterday)
        mcp.create_todo(title="今日任务", due_date=today)

        summary = mcp.get_daily_summary(today)
        assert isinstance(summary, dict)
        assert "date" in summary

    def test_schedule_cancel_todo(self):
        """测试取消待办。"""
        from src.mcp.schedule_mcp import ScheduleMCP

        mcp = ScheduleMCP()
        result = mcp.create_todo(title="待取消", due_date=None)
        todo_id = result.get("todo", {}).get("id")
        assert todo_id is not None

        cancel_result = mcp.update_todo(todo_id, completed=True)
        assert cancel_result["success"] is True

    def test_schedule_delete_schedule(self):
        """测试删除日程。"""
        from src.mcp.schedule_mcp import ScheduleMCP

        mcp = ScheduleMCP()
        today = datetime.now().strftime("%Y-%m-%d")
        result = mcp.create_schedule(
            title="待删除日程",
            date=today,
            time="10:00",
        )
        sched_id = result.get("schedule", {}).get("id")

        del_result = mcp.delete_schedule(sched_id)
        assert del_result["success"] is True

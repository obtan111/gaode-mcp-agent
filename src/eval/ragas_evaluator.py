"""
RAGAS 风格的 RAG 评估器。

该模块实现了轻量级的 RAG 评估系统，无需安装 RAGAS 库，
利用项目已有的 LLM 基础设施进行评估。

评估指标：
1. 忠实度（Faithfulness）：回答中的每个声明是否都能从检索上下文中找到支持
2. 答案相关性（Answer Relevancy）：回答是否直接针对用户问题
3. 上下文精确度（Context Precision）：检索到的文档中有多少与问题相关
4. 上下文召回率（Context Recall）：预期答案中的关键信息是否被检索到

评估流程：
1. 输入：用户问题、检索到的上下文、生成的回答、（可选）参考答案
2. 使用 LLM 对每个指标进行评分（0-1 分）
3. 输出：各指标分数 + 综合评分 + 评估报告
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json
import os

from src.config import Config
from src.utils.logger import setup_logger

logger = setup_logger("ragas_evaluator")


@dataclass
class EvaluationResult:
    """
    单次评估结果。

    属性：
    - question: 用户问题
    - answer: 生成的回答
    - contexts: 检索到的上下文列表
    - faithfulness: 忠实度分数（0-1）
    - answer_relevancy: 答案相关性分数（0-1）
    - context_precision: 上下文精确度分数（0-1）
    - context_recall: 上下文召回率分数（0-1）
    - overall_score: 综合评分（各指标加权平均）
    - details: 各指标的详细评估说明
    - timestamp: 评估时间
    """
    question: str
    answer: str
    contexts: List[str]
    faithfulness: float = 0.0
    answer_relevancy: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
    overall_score: float = 0.0
    details: Dict[str, str] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

        weights = {
            "faithfulness": 0.35,
            "answer_relevancy": 0.25,
            "context_precision": 0.20,
            "context_recall": 0.20,
        }
        self.overall_score = (
            self.faithfulness * weights["faithfulness"]
            + self.answer_relevancy * weights["answer_relevancy"]
            + self.context_precision * weights["context_precision"]
            + self.context_recall * weights["context_recall"]
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "question": self.question,
            "answer": self.answer,
            "contexts": self.contexts,
            "faithfulness": round(self.faithfulness, 4),
            "answer_relevancy": round(self.answer_relevancy, 4),
            "context_precision": round(self.context_precision, 4),
            "context_recall": round(self.context_recall, 4),
            "overall_score": round(self.overall_score, 4),
            "details": self.details,
            "timestamp": self.timestamp,
        }


class RAGEvaluator:
    """
    RAG 评估器。

    使用 LLM 对 RAG 管道的输出进行质量评估。
    支持自动降级：当 LLM 不可用时使用基于规则的基础评估。

    属性：
    - config: 配置对象
    - _llm: LLM 实例（延迟加载）
    - _model_type: 使用的模型类型
    """

    def __init__(self, model_type: str = "deepseek"):
        """
        初始化 RAG 评估器。

        参数：
        - model_type: 用于评估的 LLM 类型（默认 deepseek）
        """
        self.config = Config()
        self._model_type = model_type
        self._llm = None

    def _get_llm(self):
        """延迟加载 LLM 实例。"""
        if self._llm is None:
            try:
                from src.llm.model_factory import ModelFactory
                factory = ModelFactory()
                self._llm = factory.create_model(self._model_type)
                logger.info(f"RAG evaluator LLM loaded: {self._model_type}")
            except Exception as e:
                logger.warning(f"Failed to load LLM for evaluation: {e}")
                return None
        return self._llm

    def _call_llm(self, prompt: str) -> str:
        """
        调用 LLM 获取评估结果。

        参数：
        - prompt: 评估提示词

        返回：
        - LLM 返回的文本
        """
        llm = self._get_llm()
        if llm is None:
            return ""

        try:
            from langchain_core.messages import HumanMessage
            response = llm.invoke([HumanMessage(content=prompt)])
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.error(f"LLM evaluation call failed: {e}")
            return ""

    def evaluate(
        self,
        question: str,
        answer: str,
        contexts: List[str],
        reference_answer: Optional[str] = None,
    ) -> EvaluationResult:
        """
        执行完整的 RAG 评估。

        参数：
        - question: 用户问题
        - answer: RAG 系统生成的回答
        - contexts: 检索到的上下文文档列表
        - reference_answer: 参考答案（可选，提高召回率评估准确性）

        返回：
        - EvaluationResult 评估结果
        """
        logger.info(f"Starting RAG evaluation for question: {question[:50]}...")

        contexts_text = "\n---\n".join(contexts) if contexts else "（无检索上下文）"

        faithfulness, faith_detail = self._eval_faithfulness(answer, contexts_text)
        relevancy, rel_detail = self._eval_answer_relevancy(question, answer)
        precision, prec_detail = self._eval_context_precision(question, contexts)
        recall, rec_detail = self._eval_context_recall(
            question, contexts_text, reference_answer
        )

        result = EvaluationResult(
            question=question,
            answer=answer,
            contexts=contexts,
            faithfulness=faithfulness,
            answer_relevancy=relevancy,
            context_precision=precision,
            context_recall=recall,
            details={
                "faithfulness": faith_detail,
                "answer_relevancy": rel_detail,
                "context_precision": prec_detail,
                "context_recall": rec_detail,
            },
        )

        logger.info(
            f"RAG evaluation completed: "
            f"faithfulness={faithfulness:.2f}, relevancy={relevancy:.2f}, "
            f"precision={precision:.2f}, recall={recall:.2f}, "
            f"overall={result.overall_score:.2f}"
        )
        return result

    def _eval_faithfulness(self, answer: str, contexts: str) -> tuple:
        """
        评估忠实度：回答是否基于检索上下文。

        返回：(分数 0-1, 详细说明)
        """
        if not contexts or contexts == "（无检索上下文）":
            return 0.0, "无检索上下文，无法评估忠实度"

        prompt = f"""请评估以下回答对检索上下文的忠实度。

检索上下文：
{contexts[:3000]}

回答：
{answer[:2000]}

评估规则：
- 回答中的每个事实声明都能在上下文中找到支持 = 1.0
- 大部分声明有支持，但有少量推测 = 0.7
- 约一半声明有支持 = 0.5
- 大部分声明无法从上下文中找到支持 = 0.2
- 回答完全与上下文无关 = 0.0

请只输出一个JSON：{{"score": 分数, "reason": "简要说明"}}"""

        response = self._call_llm(prompt)
        score, reason = self._parse_eval_response(response)

        if score is None:
            answer_lower = answer.lower()
            contexts_lower = contexts.lower()
            overlap = sum(1 for w in answer_lower.split() if w in contexts_lower)
            total = max(len(answer_lower.split()), 1)
            score = min(overlap / total, 1.0)
            reason = f"规则降级评估：词汇重叠率 {score:.2f}"

        return score, reason

    def _eval_answer_relevancy(self, question: str, answer: str) -> tuple:
        """
        评估答案相关性：回答是否直接针对用户问题。

        返回：(分数 0-1, 详细说明)
        """
        prompt = f"""请评估以下回答对用户问题的相关性。

用户问题：
{question}

回答：
{answer[:2000]}

评估规则：
- 回答直接且完整地解决了问题 = 1.0
- 回答基本解决问题，有少量无关内容 = 0.8
- 回答部分解决问题 = 0.5
- 回答与问题有一定关联但不直接 = 0.3
- 回答与问题完全无关 = 0.0

请只输出一个JSON：{{"score": 分数, "reason": "简要说明"}}"""

        response = self._call_llm(prompt)
        score, reason = self._parse_eval_response(response)

        if score is None:
            q_words = set(question.lower().split())
            a_words = set(answer.lower().split())
            if not q_words:
                return 0.5, "无法计算关键词重叠"
            overlap = len(q_words & a_words) / len(q_words)
            score = min(overlap, 1.0)
            reason = f"规则降级评估：关键词覆盖率 {score:.2f}"

        return score, reason

    def _eval_context_precision(self, question: str, contexts: List[str]) -> tuple:
        """
        评估上下文精确度：检索到的文档中有多少与问题相关。

        返回：(分数 0-1, 详细说明)
        """
        if not contexts:
            return 0.0, "无检索结果"

        contexts_summary = "\n".join(
            f"[{i+1}] {ctx[:200]}..." for i, ctx in enumerate(contexts)
        )

        prompt = f"""请评估检索到的文档对用户问题的精确度。

用户问题：
{question}

检索到的文档（摘要）：
{contexts_summary}

评估规则：
- 所有文档都高度相关 = 1.0
- 大部分文档相关 = 0.7
- 约一半文档相关 = 0.5
- 大部分文档不相关 = 0.2
- 所有文档都不相关 = 0.0

请只输出一个JSON：{{"score": 分数, "reason": "简要说明"}}"""

        response = self._call_llm(prompt)
        score, reason = self._parse_eval_response(response)

        if score is None:
            q_words = set(question.lower().split())
            relevant = sum(
                1
                for ctx in contexts
                if len(q_words & set(ctx.lower().split())) > 0
            )
            score = relevant / len(contexts)
            reason = f"规则降级评估：{relevant}/{len(contexts)} 个文档包含问题关键词"

        return score, reason

    def _eval_context_recall(
        self, question: str, contexts: str, reference_answer: Optional[str]
    ) -> tuple:
        """
        评估上下文召回率：必要信息是否被检索到。

        返回：(分数 0-1, 详细说明)
        """
        if not contexts or contexts == "（无检索上下文）":
            return 0.0, "无检索上下文"

        ref_text = reference_answer or question

        prompt = f"""请评估检索上下文是否包含了回答问题所需的关键信息。

用户问题：
{question}

参考答案：
{ref_text[:1000]}

检索到的上下文：
{contexts[:3000]}

评估规则：
- 上下文包含了参考答案中的所有关键信息 = 1.0
- 包含大部分关键信息 = 0.7
- 包含约一半关键信息 = 0.5
- 只包含少量关键信息 = 0.2
- 完全未包含关键信息 = 0.0

请只输出一个JSON：{{"score": 分数, "reason": "简要说明"}}"""

        response = self._call_llm(prompt)
        score, reason = self._parse_eval_response(response)

        if score is None:
            ref_words = set(ref_text.lower().split())
            ctx_words = set(contexts.lower().split())
            if not ref_words:
                return 0.5, "无法计算关键词覆盖"
            overlap = len(ref_words & ctx_words) / len(ref_words)
            score = min(overlap, 1.0)
            reason = f"规则降级评估：参考答案关键词覆盖率 {score:.2f}"

        return score, reason

    @staticmethod
    def _parse_eval_response(response: str) -> tuple:
        """
        解析 LLM 评估响应。

        返回：(分数 or None, 原因 or "")
        """
        if not response:
            return None, ""

        import json as _json

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                data = _json.loads(response[start : end + 1])
                score = float(data.get("score", 0))
                score = max(0.0, min(1.0, score))
                reason = data.get("reason", "")
                return score, reason
        except (ValueError, _json.JSONDecodeError):
            pass

        return None, ""

    def generate_report(
        self,
        results: List[EvaluationResult],
        output_path: Optional[str] = None,
    ) -> str:
        """
        生成评估报告。

        参数：
        - results: 多次评估的结果列表
        - output_path: 报告输出路径（可选，默认打印到日志）

        返回：
        - Markdown 格式的评估报告
        """
        if not results:
            return "无评估结果。"

        n = len(results)
        avg_faith = sum(r.faithfulness for r in results) / n
        avg_rel = sum(r.answer_relevancy for r in results) / n
        avg_prec = sum(r.context_precision for r in results) / n
        avg_rec = sum(r.context_recall for r in results) / n
        avg_overall = sum(r.overall_score for r in results) / n

        report = f"""# RAG 评估报告

**评估时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**评估样本数**: {n}

## 综合指标

| 指标 | 平均分 | 说明 |
|------|--------|------|
| 忠实度 (Faithfulness) | {avg_faith:.4f} | 回答是否基于检索上下文 |
| 答案相关性 (Relevancy) | {avg_rel:.4f} | 回答是否针对用户问题 |
| 上下文精确度 (Precision) | {avg_prec:.4f} | 检索结果是否精准 |
| 上下文召回率 (Recall) | {avg_rec:.4f} | 是否检索到所有必要信息 |
| **综合评分** | **{avg_overall:.4f}** | 加权平均 |

## 详细结果

"""

        for i, r in enumerate(results, 1):
            report += f"### 样本 {i}\n\n"
            report += f"**问题**: {r.question[:100]}\n\n"
            report += f"**回答**: {r.answer[:200]}...\n\n"
            report += f"| 指标 | 分数 | 说明 |\n|------|------|------|\n"
            report += f"| 忠实度 | {r.faithfulness:.4f} | {r.details.get('faithfulness', '')} |\n"
            report += f"| 相关性 | {r.answer_relevancy:.4f} | {r.details.get('answer_relevancy', '')} |\n"
            report += f"| 精确度 | {r.context_precision:.4f} | {r.details.get('context_precision', '')} |\n"
            report += f"| 召回率 | {r.context_recall:.4f} | {r.details.get('context_recall', '')} |\n\n"

        if avg_overall >= 0.8:
            report += "## 结论\n\nRAG 系统整体表现优秀，各指标均达到较高水平。\n"
        elif avg_overall >= 0.6:
            report += "## 结论\n\nRAG 系统整体表现良好，但仍有改进空间。\n"
        else:
            report += "## 结论\n\nRAG 系统需要优化，建议检查检索策略和提示词。\n"

        if avg_faith < 0.5:
            report += "- 忠实度较低，回答可能包含上下文不支持的内容，建议优化生成提示词\n"
        if avg_rel < 0.5:
            report += "- 答案相关性较低，回答可能偏离问题，建议优化回答生成逻辑\n"
        if avg_prec < 0.5:
            report += "- 上下文精确度较低，检索到过多无关文档，建议调整检索参数或阈值\n"
        if avg_rec < 0.5:
            report += "- 上下文召回率较低，可能遗漏关键信息，建议增加检索数量或优化分词\n"

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(report)
            logger.info(f"Evaluation report saved to: {output_path}")

        return report


def evaluate_rag_pipeline(
    test_cases: List[Dict[str, Any]],
    model_type: str = "deepseek",
    report_path: Optional[str] = None,
) -> List[EvaluationResult]:
    """
    便捷函数：批量评估 RAG 管道。

    参数：
    - test_cases: 测试用例列表，每个用例包含：
      - question: 问题
      - answer: 生成的回答
      - contexts: 检索到的上下文列表
      - reference_answer: 参考答案（可选）
    - model_type: 评估用 LLM 类型
    - report_path: 报告输出路径（可选）

    返回：
    - 评估结果列表
    """
    evaluator = RAGEvaluator(model_type=model_type)
    results = []

    for i, case in enumerate(test_cases, 1):
        logger.info(f"Evaluating case {i}/{len(test_cases)}")
        result = evaluator.evaluate(
            question=case.get("question", ""),
            answer=case.get("answer", ""),
            contexts=case.get("contexts", []),
            reference_answer=case.get("reference_answer"),
        )
        results.append(result)

    if report_path:
        evaluator.generate_report(results, report_path)

    return results

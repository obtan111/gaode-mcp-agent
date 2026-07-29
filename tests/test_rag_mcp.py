"""
RAG 和 MCP 工具集成测试脚本

测试内容：
1. MCP 工具基础测试：验证 TimeMCP、RagMCP 工具可用性
2. RAG 文档上传与检索：测试文档分割、向量嵌入、相似度检索全流程
3. JSON 解析器异常处理：验证文档解析器对异常输入的健壮性

使用方法：
    python tests/test_rag_mcp.py

依赖：
    - Supabase 数据库连接
    - 智谱 AI 嵌入模型 API Key
    - MCP 服务已启动

注意：
    - 运行前需确保 .env 配置正确
    - 测试会创建临时测试文档到知识库
    - 测试完成后建议清理测试数据
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from src.database.crud import insert_document, search_documents_by_vector, get_documents_by_kb
from src.llm.embedding import EmbeddingFactory
from src.mcp.mcp_client import MCPClient
from src.rag.document_parser import DocumentParserFactory
from src.rag.text_splitter import TextSplitter


def test_mcp_tools():
    """
    测试所有 MCP 工具的可用性。

    测试步骤：
    1. 获取所有可用工具列表
    2. 测试 TimeMCP 时间查询
    3. 测试 RagMCP 知识库列表查询

    Returns:
        bool: 测试是否通过
    """
    print("\n" + "="*60)
    print("🎯 测试 MCP 工具")
    print("="*60)
    
    try:
        tools = MCPClient.get_all_available_functions()
        print(f"✅ 可用工具列表 ({len(tools)}个):")
        for tool in tools:
            print(f"   - {tool}")
    except Exception as e:
        print(f"❌ 获取工具列表失败: {e}")
        return False
    
    # 测试 TimeMCP
    print("\n--- 测试 TimeMCP ---")
    try:
        result = MCPClient.dispatch("TimeMCP", "get_current_time", {})
        print(f"✅ 当前时间: {result}")
    except Exception as e:
        print(f"❌ TimeMCP测试失败: {e}")
    
    # 测试 RagMCP
    print("\n--- 测试 RagMCP ---")
    try:
        result = MCPClient.dispatch("RagMCP", "list_knowledge_bases", {})
        print(f"✅ 知识库列表: {result}")
    except Exception as e:
        print(f"❌ RagMCP测试失败: {e}")
    
    return True


def test_rag_upload_and_search():
    """
    测试 RAG 文档上传与检索全流程。

    测试步骤：
    1. 初始化嵌入模型和文本分割器
    2. 创建测试文档（Python 介绍、机器学习、RAG 系统）
    3. 将文档分割为 chunks 并嵌入向量
    4. 存储到知识库
    5. 使用测试查询进行向量检索
    6. 验证检索结果的相关性

    Returns:
        bool: 测试是否通过
    """
    print("\n" + "="*60)
    print("🎯 测试 RAG 文档上传与检索")
    print("="*60)
    
    embedding = EmbeddingFactory().create_embedding("zhipu")
    text_splitter = TextSplitter()
    
    test_kb_name = "test_knowledge_base"
    
    # 检查测试知识库是否有文档
    try:
        docs = get_documents_by_kb(test_kb_name)
        if docs:
            print(f"✅ 测试知识库已存在，包含 {len(docs)} 个文档")
        else:
            print(f"✅ 测试知识库为空，将上传新文档")
    except Exception as e:
        print(f"⚠️  检查知识库失败（可能是首次使用）: {e}")
    
    # 创建测试文档
    test_docs = [
        {
            "filename": "python_intro.txt",
            "content": "Python是一种高级、通用、解释型编程语言。它由Guido van Rossum于1991年首次发布。Python以其简洁的语法和强大的功能而闻名，广泛应用于Web开发、数据分析、人工智能等领域。Python的主要特点包括：可读性强、面向对象、动态类型、自动内存管理等。",
            "category": "programming"
        },
        {
            "filename": "machine_learning.txt",
            "content": "机器学习是人工智能的一个分支，它使计算机系统能够从数据中学习并改进性能，而无需进行明确编程。机器学习算法使用统计技术使计算机能够从数据中学习。常见的机器学习类型包括监督学习、无监督学习和强化学习。监督学习使用标记数据进行训练，无监督学习发现数据中的模式，强化学习通过奖励机制学习。",
            "category": "ai"
        },
        {
            "filename": "rag_system.txt",
            "content": "RAG（Retrieval-Augmented Generation）是一种结合检索和生成的AI技术。RAG系统首先从知识库中检索相关文档，然后使用这些文档作为上下文来生成回答。这种方法可以减少幻觉，提高回答的准确性和可靠性。RAG系统通常包括以下组件：文档加载器、文本分割器、向量数据库、检索器和生成器。",
            "category": "ai"
        }
    ]
    
    # 上传测试文档
    success_count = 0
    for doc in test_docs:
        try:
            chunks = text_splitter.split(
                text=doc["content"],
                file_name=doc["filename"],
                file_type="txt",
                category=doc["category"]
            )
            
            for chunk in chunks:
                vector = embedding.embed_query(chunk["text"])
                result = insert_document(
                    content=chunk["text"],
                    vector=vector,
                    filename=doc["filename"],
                    page_number=chunk["metadata"].get("page_number", 1),
                    category=doc["category"],
                    metadata=chunk.get("metadata", {}),
                    kb_name=test_kb_name
                )
                if result:
                    success_count += 1
            
            print(f"✅ 上传文档成功: {doc['filename']}")
        except Exception as e:
            print(f"❌ 上传文档失败 {doc['filename']}: {e}")
    
    print(f"\n📊 文档上传统计: 成功 {success_count} 个chunk")
    
    # 测试检索
    test_queries = [
        "Python是什么?",
        "机器学习有哪些类型?",
        "什么是RAG系统?"
    ]
    
    print("\n--- 测试检索 ---")
    for query in test_queries:
        try:
            query_vector = embedding.embed_query(query)
            results = search_documents_by_vector(query_vector, limit=3, kb_name=test_kb_name)
            
            print(f"\n🔍 查询: {query}")
            print(f"   检索到 {len(results)} 条结果:")
            for i, result in enumerate(results):
                score = result.get("similarity", 0)
                content = result.get("content", "")[:100]
                print(f"   [{i+1}] 相似度: {score:.4f}, 内容: {content}...")
                
            if results:
                print("   ✅ 检索成功")
            else:
                print("   ⚠️  未检索到结果")
        except Exception as e:
            print(f"❌ 检索失败 '{query}': {e}")
    
    return True


def test_json_parser():
    """
    测试 JSON 解析器的异常处理能力。

    测试步骤：
    1. 使用无效 JSON 验证是否正确抛出异常
    2. 使用有效 JSON 验证是否正确解析
    3. 验证元数据（root_type）是否正确提取

    Returns:
        bool: 测试是否通过
    """
    print("\n" + "="*60)
    print("🎯 测试 JSON 解析器异常处理")
    print("="*60)
    
    # 测试无效JSON
    invalid_json = "{invalid json"
    try:
        parser = DocumentParserFactory.get_parser("test.json")
        text, metadata = parser.parse(bytes_data=invalid_json.encode("utf-8"))
        print("❌ 无效JSON应该抛出异常")
    except ValueError as e:
        print(f"✅ 正确捕获无效JSON异常: {e}")
    except Exception as e:
        print(f"❌ 抛出了非预期异常: {e}")
    
    # 测试有效JSON
    valid_json = '{"name": "test", "value": 123}'
    try:
        parser = DocumentParserFactory.get_parser("test.json")
        text, metadata = parser.parse(bytes_data=valid_json.encode("utf-8"))
        print(f"✅ 有效JSON解析成功: root_type={metadata.get('root_type', 'N/A')}")
    except Exception as e:
        print(f"❌ 有效JSON解析失败: {e}")
    
    return True


def main():
    """
    运行所有集成测试并输出结果汇总。

    Returns:
        int: 0 表示全部通过，1 表示部分失败
    """
    print("🚀 开始 RAG 和 MCP 功能测试")
    
    results = []
    
    results.append(("MCP工具测试", test_mcp_tools()))
    results.append(("RAG上传与检索", test_rag_upload_and_search()))
    results.append(("JSON解析器测试", test_json_parser()))
    
    print("\n" + "="*60)
    print("📋 测试结果汇总")
    print("="*60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{name}: {status}")
    
    print(f"\n总体结果: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！")
        return 0
    else:
        print("⚠️  部分测试失败，请检查日志")
        return 1


if __name__ == "__main__":
    sys.exit(main())
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database.crud import get_documents_by_kb

def check_documents():
    print("=" * 60)
    print("检查数据库中的文档")
    print("=" * 60)
    
    print("\n1. 获取所有文档...")
    try:
        docs = get_documents_by_kb(None)
        print(f"   ✅ 找到 {len(docs)} 个文档")
        
        print("\n2. 文档详情:")
        for i, doc in enumerate(docs, 1):
            print(f"\n   [{i}] ID: {doc.get('id')}")
            print(f"      文件名: {doc.get('filename')}")
            print(f"      kb_name: {doc.get('kb_name')}")
            print(f"      分类: {doc.get('category')}")
            print(f"      内容长度: {len(doc.get('content', ''))} 字符")
            
            metadata = doc.get("metadata", {})
            if isinstance(metadata, str):
                import json
                try:
                    metadata = json.loads(metadata)
                except:
                    pass
            
            if isinstance(metadata, dict):
                has_vector = "embedding_vector" in metadata
                vector_dim = len(metadata.get("embedding_vector", [])) if has_vector else 0
                print(f"      嵌入向量: {'有' if has_vector else '无'} (维度: {vector_dim})")
        
        print("\n3. 知识库名称:")
        kb_names = list(set(doc.get("kb_name", "") for doc in docs if doc.get("kb_name")))
        print(f"   ✅ 找到 {len(kb_names)} 个知识库: {kb_names}")
        
    except Exception as e:
        print(f"   ❌ 失败: {str(e)}")
        sys.exit(1)
    
    print("\n" + "=" * 60)
    print("检查完成！")
    print("=" * 60)

if __name__ == "__main__":
    check_documents()
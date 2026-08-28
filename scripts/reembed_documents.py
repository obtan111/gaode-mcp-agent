"""存量文档重嵌入脚本：按表内 content 重新生成 1024 维向量。

使用场景：
    scripts/migrate_vector_to_1024.sql 执行后，表内旧向量已置 NULL，
    运行本脚本把存量分片用智谱 embedding-2 重新向量化，恢复密集检索能力。

用法（项目根目录）：
    python scripts/reembed_documents.py            # 只处理 vector 为空的行
    python scripts/reembed_documents.py --all      # 强制重嵌入全部行

注意：必须先在 Supabase SQL Editor 执行迁移 SQL，否则会遇到
"expected 1536 dimensions, not 1024" 同样的报错（脚本会识别并提示）。
"""

import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import Config  # noqa: E402
from src.llm.embedding import EmbeddingFactory  # noqa: E402
from src.database.supabase_client import get_supabase_client  # noqa: E402
from src.utils.logger import setup_logger  # noqa: E402

logger = setup_logger("reembed_documents")


def main():
    force_all = "--all" in sys.argv

    client = get_supabase_client()
    embedding = EmbeddingFactory().create_embedding("zhipu")

    def fetch(sb):
        q = sb.table("documents").select("id, filename, kb_name, vector, content")
        if not force_all:
            q = q.filter("vector", "is", "null")
        return q.execute().data

    rows = client.execute_with_client(fetch)
    total = len(rows)
    print(f"待重嵌入: {total} 条{'（--all 全量）' if force_all else '（vector 为空）'}")
    if total == 0:
        print("没有需要处理的行，结束。")
        return

    ok = fail = 0
    for i, row in enumerate(rows, 1):
        doc_id = row["id"]
        content = (row.get("content") or "").strip()
        if not content:
            print(f"[{i}/{total}] {row.get('filename')} 内容为空，跳过")
            fail += 1
            continue
        try:
            vector = embedding.embed_query(content)

            def update(sb):
                return (
                    sb.table("documents")
                    .update({"vector": vector})
                    .eq("id", str(doc_id))
                    .execute()
                )

            client.execute_with_client(update)
            ok += 1
            print(f"[{i}/{total}] ✓ {row.get('filename')} ({row.get('kb_name')}) dim={len(vector)}")
        except Exception as exc:
            msg = str(exc)
            if "dimensions" in msg:
                print(
                    f"\n遇到维度不匹配报错：{msg[:120]}\n"
                    "=> 请先在 Supabase SQL Editor 执行 scripts/migrate_vector_to_1024.sql，"
                    "再重新运行本脚本。"
                )
                sys.exit(1)
            fail += 1
            print(f"[{i}/{total}] ✗ {row.get('filename')}: {msg[:100]}")
        time.sleep(0.2)  # 轻微限速，避免嵌入接口限流

    print(f"\n完成：成功 {ok}，失败 {fail}")
    if fail:
        sys.exit(2)


if __name__ == "__main__":
    main()

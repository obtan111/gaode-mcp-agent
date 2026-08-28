-- ============================================================
-- 向量维度迁移：documents.vector 1536 -> 1024
--
-- 背景：智谱 embedding-2 输出 1024 维向量，而当前列为 vector(1536)，
-- 导致所有知识库写入报错：expected 1536 dimensions, not 1024。
-- 表内 30 条旧向量来自已弃用的嵌入模型，对智谱查询无意义，直接清空，
-- 迁移后用 scripts/reembed_documents.py 按存量 content 重新嵌入。
--
-- 使用方法：Supabase 控制台 -> SQL Editor -> 粘贴执行（可重复执行）
-- ============================================================

-- 1) 删除依赖 vector 列的旧索引
DROP INDEX IF EXISTS idx_documents_vector;

-- 2) 允许 vector 为空，并清空失效的旧向量（content 保留，后续重新嵌入）
ALTER TABLE documents ALTER COLUMN vector DROP NOT NULL;
UPDATE documents SET vector = NULL;

-- 3) 列维度 1536 -> 1024（此时列内全为 NULL，可直接转换）
ALTER TABLE documents ALTER COLUMN vector TYPE vector(1024);

-- 4) 重建余弦相似度索引（ivfflat，数据量小时 lists=100 即可）
CREATE INDEX IF NOT EXISTS idx_documents_vector
    ON documents USING ivfflat (vector vector_cosine_ops)
    WITH (lists = 100);

-- 验证：应显示 vector(1024)
-- SELECT column_name, udt_name FROM information_schema.columns
-- WHERE table_name = 'documents' AND column_name = 'vector';

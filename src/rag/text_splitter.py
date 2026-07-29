import os
import re
import hashlib
import json
import csv
from typing import Dict, List, Any, Optional, Tuple

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import Config
from src.utils.logger import logger


class TextSplitter:
    def __init__(self, config: Config = None):
        self._config = config or Config()
        self._logger = logger
        self._strategies = self._load_strategies()

    def _load_strategies(self) -> Dict[str, Dict[str, Any]]:
        return {
            "pdf": {
                "chunk_size": self._config._get_env_int("PDF_CHUNK_SIZE", 1000),
                "chunk_overlap": self._config._get_env_int("PDF_CHUNK_OVERLAP", 100),
                "separators": ["\n\n", "\n", ". ", "。", "?", "？", "!", "！", ";", "；", ",", "，", " "],
            },
            "md": {
                "chunk_size": self._config._get_env_int("MD_CHUNK_SIZE", 800),
                "chunk_overlap": self._config._get_env_int("MD_CHUNK_OVERLAP", 80),
                "separators": ["\n## ", "\n### ", "\n#### ", "\n##### ", "\n###### ", "\n\n", "\n"],
            },
            "markdown": {
                "chunk_size": self._config._get_env_int("MD_CHUNK_SIZE", 800),
                "chunk_overlap": self._config._get_env_int("MD_CHUNK_OVERLAP", 80),
                "separators": ["\n## ", "\n### ", "\n#### ", "\n##### ", "\n###### ", "\n\n", "\n"],
            },
            "txt": {
                "chunk_size": self._config._get_env_int("TXT_CHUNK_SIZE", 800),
                "chunk_overlap": self._config._get_env_int("TXT_CHUNK_OVERLAP", 80),
                "separators": ["\n\n", "\n", ". ", "。", "?", "？", "!", "！"],
            },
            "csv": {
                "chunk_size": self._config._get_env_int("CSV_CHUNK_SIZE", 500),
                "chunk_overlap": self._config._get_env_int("CSV_CHUNK_OVERLAP", 0),
                "separators": ["\n"],
            },
            "json": {
                "chunk_size": self._config._get_env_int("JSON_CHUNK_SIZE", 1000),
                "chunk_overlap": self._config._get_env_int("JSON_CHUNK_OVERLAP", 100),
                "separators": ["\n}\n", "\n],\n", "\n},", "\n],", "\n{", "\n["],
            },
        }

    def _clean_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"\t+", " ", text)
        text = re.sub(r" {2,}", " ", text)
        text = re.sub(r"[^\x00-\x7F\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", "", text)
        text = text.strip()
        return text

    def _compute_hash(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def _split_by_strategy(self, text: str, file_type: str) -> List[str]:
        strategy = self._strategies.get(file_type)
        if not strategy:
            strategy = {
                "chunk_size": self._config.CHUNK_SIZE,
                "chunk_overlap": self._config.CHUNK_OVERLAP,
                "separators": ["\n\n", "\n", ". ", "。"],
            }

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=strategy["chunk_size"],
            chunk_overlap=strategy["chunk_overlap"],
            separators=strategy["separators"],
            length_function=len,
        )

        return splitter.split_text(text)

    def _split_csv_by_rows(self, text: str) -> List[str]:
        lines = text.strip().splitlines()
        if not lines:
            return []

        reader = csv.reader(lines)
        rows = list(reader)
        if not rows:
            return []

        header = rows[0]
        chunks = []
        current_chunk = [header]

        for row in rows[1:]:
            current_chunk.append(row)
            joined = "\n".join([",".join(r) for r in current_chunk])
            if len(joined) > self._strategies["csv"]["chunk_size"] and len(current_chunk) > 1:
                current_chunk.pop()
                chunks.append("\n".join([",".join(r) for r in current_chunk]))
                current_chunk = [header, row]

        if len(current_chunk) > 1:
            chunks.append("\n".join([",".join(r) for r in current_chunk]))

        return chunks

    def _split_json_by_structure(self, text: str) -> List[str]:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self._logger.warning("Invalid JSON, falling back to generic split")
            return self._split_by_strategy(text, "json")

        chunks = []

        def extract_objects(obj: Any, path: str = "") -> None:
            if isinstance(obj, dict):
                chunk = json.dumps(obj, ensure_ascii=False, indent=2)
                if len(chunk) <= self._strategies["json"]["chunk_size"]:
                    chunks.append(chunk)
                else:
                    for key, value in obj.items():
                        extract_objects(value, f"{path}.{key}" if path else key)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    extract_objects(item, f"{path}[{i}]")
            else:
                chunk = json.dumps({path: obj}, ensure_ascii=False)
                chunks.append(chunk)

        extract_objects(data)
        return chunks

    def _extract_pdf_pages(self, text: str) -> List[Tuple[int, str]]:
        pages = []
        current_page = 1
        current_text = ""
        page_separator = "\f"

        parts = text.split(page_separator)
        for part in parts:
            if part.strip():
                pages.append((current_page, part.strip()))
                current_page += 1

        if not pages:
            paragraphs = re.split(r"\n\n+", text)
            avg_paragraphs_per_page = max(1, len(paragraphs) // 10)
            current_page = 1
            current_text = ""
            for i, para in enumerate(paragraphs):
                if len(current_text) + len(para) > 2000:
                    if current_text:
                        pages.append((current_page, current_text.strip()))
                        current_page += 1
                    current_text = para
                else:
                    current_text += "\n\n" + para if current_text else para

            if current_text:
                pages.append((current_page, current_text.strip()))

        return pages

    def _split_pdf_by_pages(self, text: str) -> List[str]:
        """
        按页面切分PDF文本，保持页面完整性。
        
        每个页面作为一个chunk，如果页面内容过长，则按段落进一步切分，
        但保持段落边界不被截断。
        
        参数：
        - text: PDF文本
        
        返回：
        - chunk列表
        """
        pages = self._extract_pdf_pages(text)
        chunks = []
        chunk_size = self._strategies["pdf"]["chunk_size"]
        chunk_overlap = self._strategies["pdf"]["chunk_overlap"]
        
        for page_num, page_text in pages:
            if len(page_text) <= chunk_size:
                chunks.append(page_text)
            else:
                paragraphs = re.split(r"\n\n+", page_text)
                current_chunk = ""
                
                for para in paragraphs:
                    if not para.strip():
                        continue
                    
                    if len(current_chunk) + len(para) + 2 <= chunk_size:
                        if current_chunk:
                            current_chunk += "\n\n" + para
                        else:
                            current_chunk = para
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                            # 添加重叠部分
                            if chunk_overlap > 0:
                                overlap_start = max(0, len(current_chunk) - chunk_overlap)
                                current_chunk = current_chunk[overlap_start:] + "\n\n" + para
                            else:
                                current_chunk = para
                        else:
                            # 单个段落超过chunk_size，强制分割
                            chunks.append(para[:chunk_size])
                            remaining = para[chunk_size:]
                            while remaining:
                                chunks.append(remaining[:chunk_size])
                                remaining = remaining[chunk_size:]
                
                if current_chunk:
                    chunks.append(current_chunk)
        
        return chunks

    def _extract_md_sections(self, text: str) -> List[Tuple[str, str]]:
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
        headings = []

        for match in heading_pattern.finditer(text):
            level = len(match.group(1))
            title = match.group(2).strip()
            headings.append({
                "level": level,
                "title": title,
                "start": match.start(),
                "end": match.end(),
            })

        sections = []
        for i, heading in enumerate(headings):
            start = heading["end"]
            end = headings[i + 1]["start"] if i + 1 < len(headings) else len(text)
            content = text[start:end].strip()
            if content:
                sections.append((heading["title"], content))

        if not sections:
            sections.append(("全文", text))

        return sections

    def _split_md_by_sections(self, text: str) -> List[str]:
        """
        按章节切分Markdown文本，保持语义完整性。
        
        优先按标题层级切分，每个章节作为一个chunk。
        如果章节内容过长，则按段落进一步切分，保持段落边界。
        
        参数：
        - text: Markdown文本
        
        返回：
        - chunk列表
        """
        sections = self._extract_md_sections(text)
        chunks = []
        chunk_size = self._strategies["md"]["chunk_size"]
        chunk_overlap = self._strategies["md"]["chunk_overlap"]
        
        for section_title, section_content in sections:
            full_section = f"## {section_title}\n\n{section_content}"
            
            if len(full_section) <= chunk_size:
                chunks.append(full_section)
            else:
                paragraphs = re.split(r"\n\n+", section_content)
                current_chunk = f"## {section_title}\n\n"
                
                for para in paragraphs:
                    if not para.strip():
                        continue
                    
                    if len(current_chunk) + len(para) + 2 <= chunk_size:
                        if current_chunk != f"## {section_title}\n\n":
                            current_chunk += "\n\n" + para
                        else:
                            current_chunk += para
                    else:
                        if current_chunk != f"## {section_title}\n\n":
                            chunks.append(current_chunk)
                            # 添加重叠部分（保留标题）
                            current_chunk = f"## {section_title}\n\n"
                            if chunk_overlap > 0:
                                current_chunk += para[:chunk_overlap] + "\n\n"
                            current_chunk += para
                        else:
                            # 单个段落超过chunk_size，强制分割
                            chunks.append(f"## {section_title}\n\n" + para[:chunk_size])
                            remaining = para[chunk_size:]
                            while remaining:
                                chunks.append(f"## {section_title}（续）\n\n" + remaining[:chunk_size])
                                remaining = remaining[chunk_size:]
                
                if current_chunk != f"## {section_title}\n\n":
                    chunks.append(current_chunk)
        
        return chunks

    def split(
        self,
        text: str,
        file_name: str,
        file_type: str,
        category: str = "",
        **kwargs,
    ) -> List[Dict[str, Any]]:
        self._logger.info(f"Starting text splitting for {file_name} ({file_type})")

        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            self._logger.warning("Text is empty after cleaning")
            return []

        file_type = file_type.lower()
        raw_chunks: List[str] = []

        if file_type == "csv":
            raw_chunks = self._split_csv_by_rows(cleaned_text)
        elif file_type == "json":
            raw_chunks = self._split_json_by_structure(cleaned_text)
        elif file_type == "pdf":
            raw_chunks = self._split_pdf_by_pages(cleaned_text)
        elif file_type in ["md", "markdown"]:
            raw_chunks = self._split_md_by_sections(cleaned_text)
        else:
            raw_chunks = self._split_by_strategy(cleaned_text, file_type)

        self._logger.info(f"Generated {len(raw_chunks)} raw chunks")

        unique_chunks: List[str] = []
        seen_hashes: set = set()

        for chunk in raw_chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            chunk_hash = self._compute_hash(chunk)
            if chunk_hash not in seen_hashes:
                seen_hashes.add(chunk_hash)
                unique_chunks.append(chunk)

        self._logger.info(f"After deduplication: {len(unique_chunks)} unique chunks")

        results: List[Dict[str, Any]] = []
        page_info = None
        section_info = None

        if file_type == "pdf":
            page_info = self._extract_pdf_pages(cleaned_text)
        elif file_type in ["md", "markdown"]:
            section_info = self._extract_md_sections(cleaned_text)

        for idx, chunk in enumerate(unique_chunks):
            metadata: Dict[str, Any] = {
                "file_name": file_name,
                "file_type": file_type,
                "category": category,
                "chunk_number": idx + 1,
                "total_chunks": len(unique_chunks),
                "chunk_length": len(chunk),
            }

            if file_type == "pdf" and page_info:
                for page_num, page_text in page_info:
                    if chunk[:100] in page_text or page_text[:100] in chunk:
                        metadata["page_number"] = page_num
                        break

            elif file_type in ["md", "markdown"] and section_info:
                for section_title, section_content in section_info:
                    if chunk[:100] in section_content or section_content[:100] in chunk:
                        metadata["section"] = section_title
                        break

            metadata.update(kwargs)

            results.append({
                "text": chunk,
                "metadata": metadata,
            })

        self._logger.info(f"Text splitting completed, {len(results)} chunks generated")
        return results

    def update_strategy(self, file_type: str, **kwargs) -> None:
        strategy = self._strategies.get(file_type.lower())
        if strategy:
            strategy.update(kwargs)
            self._logger.info(f"Updated strategy for {file_type}: {kwargs}")
        else:
            self._strategies[file_type.lower()] = {
                "chunk_size": kwargs.get("chunk_size", self._config.CHUNK_SIZE),
                "chunk_overlap": kwargs.get("chunk_overlap", self._config.CHUNK_OVERLAP),
                "separators": kwargs.get("separators", ["\n\n", "\n", ". ", "。"]),
            }
            self._logger.info(f"Created new strategy for {file_type}: {self._strategies[file_type.lower()]}")

    def get_strategy(self, file_type: str) -> Optional[Dict[str, Any]]:
        return self._strategies.get(file_type.lower())
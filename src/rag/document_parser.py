import os
import re
import csv
import json
import chardet
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from src.utils.logger import logger
from src.utils.retry import retry


class DocumentParser(ABC):
    @abstractmethod
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        pass

    def _read_file_bytes(self, file_path: str) -> bytes:
        with open(file_path, "rb") as f:
            return f.read()


class PDFParser(DocumentParser):
    def __init__(self):
        self._logger = logger

    @retry(max_retries=2, backoff_factor=1.0)
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        try:
            import fitz
        except ImportError:
            self._logger.error("PyMuPDF (fitz) is not installed")
            raise ImportError("PyMuPDF (fitz) is required for PDF parsing")

        if bytes_data is None:
            if file_path is None:
                raise ValueError("Either file_path or bytes_data must be provided")
            bytes_data = self._read_file_bytes(file_path)

        doc = fitz.open(stream=bytes_data, filetype="pdf")
        pages = []
        metadata = {
            "parser": "PDFParser",
            "total_pages": doc.page_count,
            "pages": [],
        }

        for page_num in range(doc.page_count):
            page = doc[page_num]
            text = page.get_text()
            if text.strip():
                pages.append(text)
                metadata["pages"].append({
                    "page_number": page_num + 1,
                    "text_length": len(text),
                })

        doc.close()
        full_text = "\n\n".join(pages)
        self._logger.info(f"PDF parsed successfully, {len(pages)} pages, {len(full_text)} characters")
        return full_text, metadata


class MarkdownParser(DocumentParser):
    def __init__(self):
        self._logger = logger
        self._heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

    @retry(max_retries=2, backoff_factor=1.0)
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        if bytes_data is None:
            if file_path is None:
                raise ValueError("Either file_path or bytes_data must be provided")
            bytes_data = self._read_file_bytes(file_path)

        text = bytes_data.decode("utf-8")
        metadata = {
            "parser": "MarkdownParser",
            "headings": [],
            "sections": [],
        }

        headings = []
        for match in self._heading_pattern.finditer(text):
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
                sections.append({
                    "level": heading["level"],
                    "title": heading["title"],
                    "content_length": len(content),
                })

        metadata["headings"] = headings
        metadata["sections"] = sections
        self._logger.info(f"Markdown parsed successfully, {len(headings)} headings, {len(sections)} sections")
        return text, metadata


class TextParser(DocumentParser):
    def __init__(self):
        self._logger = logger
        self._encodings = ["utf-8", "gbk", "gb2312", "big5", "latin-1"]

    def _detect_encoding(self, bytes_data: bytes) -> str:
        result = chardet.detect(bytes_data)
        encoding = result["encoding"] or "utf-8"
        return encoding

    @retry(max_retries=2, backoff_factor=1.0)
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        if bytes_data is None:
            if file_path is None:
                raise ValueError("Either file_path or bytes_data must be provided")
            bytes_data = self._read_file_bytes(file_path)

        encoding = self._detect_encoding(bytes_data)
        for enc in [encoding] + self._encodings:
            try:
                text = bytes_data.decode(enc)
                metadata = {
                    "parser": "TextParser",
                    "encoding": enc,
                    "character_count": len(text),
                    "line_count": len(text.splitlines()),
                }
                self._logger.info(f"Text parsed successfully with encoding {enc}, {len(text)} characters")
                return text, metadata
            except UnicodeDecodeError:
                continue

        raise ValueError(f"Unable to decode text with encodings: {self._encodings}")


class CSVParser(DocumentParser):
    def __init__(self):
        self._logger = logger
        self._encodings = ["utf-8", "gbk", "gb2312", "big5", "latin-1"]

    def _detect_encoding(self, bytes_data: bytes) -> str:
        result = chardet.detect(bytes_data)
        encoding = result["encoding"] or "utf-8"
        return encoding

    @retry(max_retries=2, backoff_factor=1.0)
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        if bytes_data is None:
            if file_path is None:
                raise ValueError("Either file_path or bytes_data must be provided")
            bytes_data = self._read_file_bytes(file_path)

        encoding = self._detect_encoding(bytes_data)
        text = None
        for enc in [encoding] + self._encodings:
            try:
                text = bytes_data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        
        if text is None:
            raise ValueError(f"Unable to decode CSV with encodings: {self._encodings}")
        lines = text.strip().splitlines()
        reader = csv.reader(lines)
        rows = list(reader)

        has_header = len(rows) > 0
        headers = rows[0] if has_header else []
        data_rows = rows[1:] if has_header else rows

        metadata = {
            "parser": "CSVParser",
            "has_header": has_header,
            "headers": headers,
            "total_rows": len(data_rows),
            "columns": len(headers) if headers else (len(rows[0]) if rows else 0),
            "row_metadata": [],
        }

        for idx, row in enumerate(data_rows):
            metadata["row_metadata"].append({
                "row_number": idx + 1,
                "column_count": len(row),
            })

        self._logger.info(f"CSV parsed successfully, {len(data_rows)} rows, {len(headers)} columns")
        return text, metadata


class JSONParser(DocumentParser):
    def __init__(self):
        self._logger = logger

    def _extract_structure(self, data: Any, level: int = 0, path: str = "") -> List[Dict[str, Any]]:
        structure = []
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path}.{key}" if path else key
                node = {
                    "path": new_path,
                    "level": level,
                    "type": "object",
                    "key": key,
                }
                structure.append(node)
                structure.extend(self._extract_structure(value, level + 1, new_path))
        elif isinstance(data, list):
            new_path = f"{path}[]"
            node = {
                "path": new_path,
                "level": level,
                "type": "array",
                "length": len(data),
            }
            structure.append(node)
            if data:
                structure.extend(self._extract_structure(data[0], level + 1, new_path))
        else:
            node = {
                "path": path,
                "level": level,
                "type": type(data).__name__,
            }
            structure.append(node)
        return structure

    @retry(max_retries=2, backoff_factor=1.0)
    def parse(self, file_path: str = None, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        if bytes_data is None:
            if file_path is None:
                raise ValueError("Either file_path or bytes_data must be provided")
            bytes_data = self._read_file_bytes(file_path)

        text = bytes_data.decode("utf-8")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            self._logger.error(f"Invalid JSON format: {str(e)}")
            raise ValueError(f"Invalid JSON format: {str(e)}")

        structure = self._extract_structure(data)
        metadata = {
            "parser": "JSONParser",
            "root_type": type(data).__name__,
            "structure": structure,
            "depth": max(node["level"] for node in structure) + 1 if structure else 0,
        }

        self._logger.info(f"JSON parsed successfully, depth: {metadata['depth']}, structure nodes: {len(structure)}")
        return text, metadata


class DocumentParserFactory:
    _parsers: Dict[str, DocumentParser] = {}

    @classmethod
    def register_parser(cls, extension: str, parser: DocumentParser) -> None:
        cls._parsers[extension.lower()] = parser
        logger.info(f"Registered parser for .{extension}")

    @classmethod
    def get_parser(cls, file_path: str) -> DocumentParser:
        extension = os.path.splitext(file_path)[1].lower().lstrip(".")
        parser = cls._parsers.get(extension)
        if not parser:
            logger.warning(f"No parser found for .{extension}, using TextParser")
            return TextParser()
        return parser

    @classmethod
    def parse(cls, file_path: str, bytes_data: bytes = None) -> Tuple[str, Dict[str, Any]]:
        parser = cls.get_parser(file_path)
        logger.info(f"Using {parser.__class__.__name__} to parse {file_path}")
        return parser.parse(file_path, bytes_data)


DocumentParserFactory.register_parser("pdf", PDFParser())
DocumentParserFactory.register_parser("md", MarkdownParser())
DocumentParserFactory.register_parser("markdown", MarkdownParser())
DocumentParserFactory.register_parser("txt", TextParser())
DocumentParserFactory.register_parser("csv", CSVParser())
DocumentParserFactory.register_parser("json", JSONParser())

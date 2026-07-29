import requests
import json
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger

logger = setup_logger("web_mcp")


@MCPClient.register_tool("WebMCP")
class WebMCP(MCPClient):
    """
    网页操作 MCP 工具。
    
    提供网页抓取和联网搜索功能：
    - 网页内容抓取（提取文本、链接、标题）
    - 网页元数据获取
    - 网络搜索（模拟搜索请求）
    - URL 验证
    """
    
    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._timeout = 15
    
    def fetch_webpage(self, url: str, extract_text: bool = True, max_content_length: int = 50000) -> dict:
        """
        抓取网页内容。
        
        Args:
            url: 网页 URL
            extract_text: 是否提取纯文本内容
            max_content_length: 最大内容长度
        
        Returns:
            dict: 包含以下字段的字典：
                - url: 请求的 URL
                - final_url: 最终跳转后的 URL
                - status_code: HTTP 状态码
                - title: 网页标题
                - description: 网页描述
                - content: 提取的内容（HTML 或纯文本）
                - content_type: 内容类型
                - encoding: 编码
        """
        try:
            response = self._session.get(url, timeout=self._timeout, allow_redirects=True)
            response.raise_for_status()
            
            html = response.text
            
            # 提取标题
            title = ""
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
            
            # 提取描述
            description = ""
            desc_match = re.search(r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
            if desc_match:
                description = desc_match.group(1).strip()
            
            # 提取正文
            content = html
            if extract_text:
                # 移除脚本和样式
                content = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)
                # 移除 HTML 标签
                content = re.sub(r'<[^>]+>', '', content)
                # 清理空白
                content = re.sub(r'\s+', ' ', content).strip()
            
            # 截断过长内容
            if len(content) > max_content_length:
                content = content[:max_content_length] + "...(内容已截断)"
            
            result = {
                "url": url,
                "final_url": response.url,
                "status_code": response.status_code,
                "title": title,
                "description": description,
                "content": content,
                "content_type": response.headers.get("Content-Type", ""),
                "encoding": response.encoding,
            }
            
            logger.info(f"fetch_webpage: {url}, status={response.status_code}, length={len(content)}")
            return result
            
        except requests.Timeout:
            logger.error(f"Timeout fetching: {url}")
            raise TimeoutError(f"Timeout fetching: {url}")
        except requests.RequestException as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            raise
    
    def get_webpage_metadata(self, url: str) -> dict:
        """
        获取网页元数据。
        
        Args:
            url: 网页 URL
        
        Returns:
            dict: 包含以下字段的字典：
                - url: 请求的 URL
                - title: 网页标题
                - description: 网页描述
                - keywords: 关键词
                - author: 作者
                - og_tags: Open Graph 标签
                - links: 页面链接列表
        """
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
            
            html = response.text
            
            # 提取标题
            title = ""
            title_match = re.search(r'<title[^>]*>([^<]+)</title>', html, re.IGNORECASE)
            if title_match:
                title = title_match.group(1).strip()
            
            # 提取 meta 标签
            description = ""
            keywords = ""
            author = ""
            og_tags = {}
            
            for match in re.finditer(r'<meta[^>]+>', html, re.IGNORECASE):
                meta_tag = match.group(0)
                name_match = re.search(r'name=["\']([^"\']+)["\']', meta_tag, re.IGNORECASE)
                content_match = re.search(r'content=["\']([^"\']*)["\']', meta_tag, re.IGNORECASE)
                prop_match = re.search(r'property=["\']([^"\']+)["\']', meta_tag, re.IGNORECASE)
                
                if not content_match:
                    continue
                
                name = name_match.group(1).lower() if name_match else ""
                prop = prop_match.group(1).lower() if prop_match else ""
                value = content_match.group(1)
                
                if name == "description":
                    description = value
                elif name == "keywords":
                    keywords = value
                elif name == "author":
                    author = value
                elif prop.startswith("og:"):
                    og_tags[prop] = value
            
            # 提取链接
            links = []
            for match in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.IGNORECASE):
                href = match.group(1)
                text = match.group(2).strip()
                if href.startswith("http"):
                    links.append({"url": href, "text": text})
            
            result = {
                "url": url,
                "title": title,
                "description": description,
                "keywords": keywords,
                "author": author,
                "og_tags": og_tags,
                "links": links[:20],  # 限制返回数量
            }
            
            logger.info(f"get_webpage_metadata: {url}, links={len(links)}")
            return result
            
        except requests.RequestException as e:
            logger.error(f"Error fetching metadata for {url}: {str(e)}")
            raise
    
    def search_web(self, query: str, num_results: int = 5) -> dict:
        """
        模拟网络搜索。
        
        注意：此功能使用公开搜索引擎或知识图谱，不保证搜索质量。
        生产环境建议使用专业搜索 API（如百度搜索、谷歌搜索）。
        
        Args:
            query: 搜索关键词
            num_results: 返回结果数量（默认 5）
        
        Returns:
            dict: 包含以下字段的字典：
                - query: 搜索关键词
                - results: 搜索结果列表
                - total: 结果总数
                - note: 备注信息
        """
        # 使用 DuckDuckGo HTML 搜索（公开、无需 API Key）
        try:
            search_url = "https://html.duckduckgo.com/html/"
            response = self._session.post(
                search_url,
                data={"q": query, "kl": "cn-zh"},
                timeout=self._timeout
            )
            response.raise_for_status()
            
            html = response.text
            
            # 解析搜索结果
            results = []
            result_blocks = re.findall(
                r'<a[^>]*class=["\']result__a["\'][^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                html,
                re.IGNORECASE | re.DOTALL
            )
            
            for href, title_html in result_blocks[:num_results]:
                title = re.sub(r'<[^>]+>', '', title_html).strip()
                # 清理 DuckDuckGo 的重定向 URL
                if "duckduckgo.com/l/" in href:
                    from urllib.parse import parse_qs, urlparse
                    try:
                        parsed = urlparse(href)
                        params = parse_qs(parsed.query)
                        href = params.get("uddg", [href])[0]
                    except:
                        pass
                
                results.append({
                    "title": title,
                    "url": href,
                })
            
            result = {
                "query": query,
                "results": results,
                "total": len(results),
                "note": "使用 DuckDuckGo HTML 搜索，结果可能有限。",
            }
            
            logger.info(f"search_web: query='{query}', results={len(results)}")
            return result
            
        except requests.RequestException as e:
            logger.error(f"Error searching: {str(e)}")
            return {
                "query": query,
                "results": [],
                "total": 0,
                "note": f"搜索失败: {str(e)}",
            }
    
    def validate_url(self, url: str) -> dict:
        """
        验证 URL 是否有效可访问。
        
        Args:
            url: 要验证的 URL
        
        Returns:
            dict: 包含以下字段的字典：
                - url: 验证的 URL
                - valid: 是否有效
                - status_code: HTTP 状态码
                - final_url: 最终跳转后的 URL
                - response_time: 响应时间（秒）
                - error: 错误信息（如果无效）
        """
        import time
        
        start_time = time.time()
        error = None
        valid = False
        status_code = None
        final_url = url
        
        try:
            response = self._session.head(url, timeout=self._timeout, allow_redirects=True)
            status_code = response.status_code
            final_url = response.url
            valid = 200 <= status_code < 400
        except requests.RequestException as e:
            error = str(e)
        
        response_time = round(time.time() - start_time, 3)
        
        result = {
            "url": url,
            "valid": valid,
            "status_code": status_code,
            "final_url": final_url,
            "response_time": response_time,
            "error": error,
        }
        
        logger.info(f"validate_url: {url}, valid={valid}, time={response_time}s")
        return result
    
    def extract_links(self, url: str, max_links: int = 50) -> dict:
        """
        从网页中提取所有链接。
        
        Args:
            url: 网页 URL
            max_links: 最大提取链接数
        
        Returns:
            dict: 包含以下字段的字典：
                - url: 源 URL
                - links: 提取的链接列表
                - total: 总链接数
        """
        try:
            response = self._session.get(url, timeout=self._timeout)
            response.raise_for_status()
            
            html = response.text
            
            links = []
            for match in re.finditer(r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', html, re.IGNORECASE):
                href = match.group(1)
                text = match.group(2).strip()
                
                # 只返回外部链接和相对链接
                if href.startswith("http") or href.startswith("/"):
                    links.append({
                        "url": href,
                        "text": text,
                        "is_external": href.startswith("http"),
                    })
                
                if len(links) >= max_links:
                    break
            
            result = {
                "url": url,
                "links": links,
                "total": len(links),
            }
            
            logger.info(f"extract_links: {url}, links={len(links)}")
            return result
            
        except requests.RequestException as e:
            logger.error(f"Error extracting links from {url}: {str(e)}")
            raise

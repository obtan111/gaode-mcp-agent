"""
私人助手应用主入口文件。

该文件包含 Gradio Web 界面的完整实现，分为两个主要功能模块：
1. 私人助手模块：支持多模态对话（文本、语音、图片）、会话管理、模型选择
2. 知识库管理模块：支持知识库创建、文件上传、向量化存储、检索调试

核心架构：
- 会话缓存机制：SESSION_CACHE 使用 30 秒 TTL 避免数据库同步阻塞
- 异步设计：数据库写操作使用后台线程，不阻塞 Gradio 队列
- 并发保护：_chat_in_progress 锁防止重复提交聊天请求
- TTS 容错：支持列表内容类型、空文本检测、绝对路径保存

全局变量说明：
- CHAT_SESSIONS: 内存中存储的聊天会话字典，key 为 session_id，value 为消息列表
- CURRENT_SESSION_ID: 当前活跃会话的 ID
- SESSION_CACHE: 会话下拉框缓存，包含 choices、selected_value、updated_at、lock

依赖组件：
- AgentGraph: 智能代理工作流图，处理工具调用和 LLM 推理
- SpeechRecognition: 语音识别组件，将音频转为文本（智谱 ASR）
- TextToSpeech: 文本转语音组件，将回答转为语音（智谱 TTS）
- EmbeddingFactory: 嵌入模型工厂，用于生成文本向量
- TextSplitter: 文本分割器，用于文档切分
"""

import os
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"

import sys
import io
import base64
import uuid
import threading
import time
import tempfile
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime
from src.utils.file_utils import extract_file_info, get_file_extension, is_valid_file_type, is_file_size_valid

TEMP_DIR = tempfile.gettempdir()

import huggingface_hub
if not hasattr(huggingface_hub, 'HfFolder'):
    class HfFolder:
        @staticmethod
        def save_token(token):
            pass
        @staticmethod
        def get_token():
            return None
    huggingface_hub.HfFolder = HfFolder

import gradio as gr

# 配置模块
from src.config.settings import Config, load_and_validate_config
# 数据库 CRUD 操作
from src.database.crud import (
    insert_document, get_documents_by_kb, delete_documents_by_filename,
    create_session, list_sessions, get_session_by_id, update_session, delete_session,
    get_knowledge_base_names,
)
from src.database.supabase_client import get_supabase_client
# LLM 相关组件
from src.llm.model_factory import ModelFactory
from src.llm.speech import SpeechRecognition, TextToSpeech
from src.llm.embedding import EmbeddingFactory
# RAG 相关组件
from src.rag.document_parser import DocumentParserFactory
from src.rag.text_splitter import TextSplitter
from src.rag.retrieval_pipeline import RetrievalPipeline
# 智能代理工作流
from src.agent.graph import AgentGraph
# 日志工具
from src.utils.logger import setup_logger

# 初始化日志记录器
logger = setup_logger("app")
# 加载并验证配置
config = load_and_validate_config()

# 初始化核心组件
agent_graph = AgentGraph()           # 智能代理工作流图
speech_recognizer = SpeechRecognition()  # 语音识别
text_to_speech = TextToSpeech(engine="zhipu")  # 文本转语音
embedding_factory = EmbeddingFactory()  # 嵌入模型工厂
text_splitter = TextSplitter(config)   # 文本分割器

# 全局会话状态管理
CHAT_SESSIONS: Dict[str, List[Dict[str, Any]]] = {}  # 内存会话缓存
CURRENT_SESSION_ID: str = ""  # 当前活跃会话 ID

# 会话下拉框缓存（用于快速响应，避免阻塞 Gradio 队列）
SESSION_CACHE: Dict[str, Any] = {
    "choices": [],
    "selected_value": None,
    "updated_at": 0.0,
    "lock": threading.Lock(),
}
SESSION_CACHE_TTL = 30.0

# 会话收藏状态（内存中维护，key 为 session_id）
FAVORITE_SESSIONS: Dict[str, bool] = {}
# 会话标签（内存中维护，key 为 session_id，value 为标签文本）
SESSION_TAGS: Dict[str, str] = {}
# 主题状态（False=亮色，True=暗色）
_theme_dark = False

_chat_in_progress = False
_chat_lock = threading.Lock()


def _format_session_label(session):
    """
    格式化会话标签，生成友好的显示名称。

    格式规则：
    1. 如果有自定义标题且非默认"新对话"，使用标题
    2. 否则使用创建时间，格式为 "新对话 MM-DD HH:MM"
    3. 最后兜底使用 "新对话"
    4. 如果会话有标签，显示为 "[标签名] 原标题"
    5. 如果会话已收藏，标签前加 ⭐ 前缀

    参数：
    - session: 会话字典，包含 id、title、created_at 等字段

    返回：
    - Tuple[str, str]: (显示标签, 会话ID)
    """
    session_id = str(session["id"])
    title = session.get("title", "")
    created_at = session.get("created_at", "")

    # 如果有标题且不是默认的"新对话"，直接使用标题
    if title and title != "新对话":
        label = title
    else:
        # 否则用时间作为标签
        label = "新对话"
        try:
            if created_at:
                from datetime import datetime
                dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                label = f"新对话 {dt.strftime('%m-%d %H:%M')}"
        except:
            pass

    # 添加标签前缀
    if session_id in SESSION_TAGS:
        label = f"[{SESSION_TAGS[session_id]}] {label}"

    # 添加收藏前缀
    if session_id in FAVORITE_SESSIONS:
        label = f"⭐ {label}"

    return label, session_id


def create_chat_tab(demo):
    """
    创建私人助手聊天界面标签页。
    
    界面布局（参考豆包设计）：
    - 左侧面板（scale=1）：会话管理 + 模型选择
    - 右侧面板（scale=4）：聊天窗口 + 输入区域
    
    功能组件：
    1. 会话管理：新建对话、历史会话下拉列表、清空、删除
    2. 模型选择：DeepSeek / 智谱 GLM-4
    3. 聊天窗口：Chatbot 组件显示对话历史
    4. 多模态输入：文本框、附件按钮、麦克风按钮、TTS 按钮
    5. 隐藏组件：图片输入、音频输入、TTS 音频输出（用于上传文件和播放语音）
    
    参数：
    - demo: Gradio Blocks 对象，用于注册界面组件和事件
    """
    session_choices = [("新对话", "")]
    try:
        client = get_supabase_client()
        def list_func(sb_client):
            result = sb_client.table("chat_session").select("*").order("created_at", desc=True).range(0, 9).execute()
            return result.data
        sessions = client.execute_with_client(list_func)
        session_choices = []
        for s in sessions:
            label, session_id = _format_session_label(s)
            session_choices.append((label, session_id))
        with SESSION_CACHE["lock"]:
            SESSION_CACHE["choices"] = session_choices
            SESSION_CACHE["updated_at"] = time.time()
    except Exception as e:
        logger.warning(f"Failed to preload sessions: {str(e)}")
        session_choices = [("新对话", "")]
        with SESSION_CACHE["lock"]:
            SESSION_CACHE["choices"] = session_choices
            SESSION_CACHE["updated_at"] = 0.0
    
    # 创建"私人助手"标签页
    with gr.Tab("私人助手"):
        with gr.Row():
            # 左侧面板：会话管理和模型选择
            with gr.Column(scale=1, min_width=260):
                # 新建对话按钮
                new_session_btn = gr.Button("+ 新建对话", variant="primary", size="sm")
                
                gr.Markdown("### 历史会话")
                session_list = gr.Dropdown(
                    choices=session_choices,
                    interactive=True,
                    label="选择会话",
                    allow_custom_value=True,
                )
                
                # 会话操作按钮
                with gr.Row():
                    clear_btn = gr.Button("清空", size="sm")          # 清空当前会话
                    delete_session_btn = gr.Button("删除", variant="stop", size="sm")  # 删除会话
                    cleanup_btn = gr.Button("清理旧的", size="sm")    # 清理旧会话

                # 导出和收藏按钮
                with gr.Row():
                    export_btn = gr.Button("📤 导出", size="sm")      # 导出当前会话为 Markdown
                    favorite_btn = gr.Button("⭐ 收藏", size="sm")    # 收藏当前会话
                export_file = gr.File(visible=False, label="导出文件")  # 导出文件下载组件
                
                # 模型选择下拉框
                gr.Markdown("### 模型选择")
                model_selector = gr.Dropdown(
                    label="选择模型",
                    choices=[
                        ("DeepSeek (deepseek-v4-flash)", "deepseek"),
                        ("DeepSeek 视觉 (deepseek-vl)", "deepseek-vl"),
                        ("智谱 GLM-4", "zhipu"),
                        ("智谱 GLM-4V 视觉", "zhipu-4v"),
                    ],
                    value="deepseek",
                    interactive=True,
                )

                # 会话标签输入框
                tag_input = gr.Textbox(
                    label="会话标签",
                    placeholder="为当前会话添加标签（回车保存）...",
                )

                # 主题切换按钮
                theme_btn = gr.Button("🌙 暗色", size="sm")

            # 右侧面板：聊天窗口和输入区域
            with gr.Column(scale=4):
                # 聊天窗口
                chatbot = gr.Chatbot(
                    height=500,
                )

                # 输入区域：多模态输入组件
                with gr.Row():
                    # 附件上传按钮
                    attach_btn = gr.Button("📎", size="md", min_width=48)
                    # 麦克风语音输入按钮
                    mic_btn = gr.Button("🎤", size="md", min_width=48)
                    # 链接输入按钮
                    link_btn = gr.Button("🔗", size="md", min_width=48)
                    # 文本输入框
                    user_input = gr.Textbox(
                        placeholder="输入消息...",
                        container=False,
                        scale=10,
                    )
                    # 语音播放按钮
                    tts_btn = gr.Button("🔊", size="md", min_width=48)
                    # 发送按钮
                    send_btn = gr.Button("发送", variant="primary", size="md", min_width=72)
                
                # 图片上传区域（默认隐藏，点击附件按钮后显示）
                with gr.Row(visible=False) as image_upload_row:
                    image_input = gr.Image(
                        type="filepath",
                        sources=["upload"],
                        label="上传图片",
                    )
                    cancel_image_btn = gr.Button("取消", size="sm")
                
                # 音频录制区域（默认隐藏，点击麦克风按钮后显示）
                with gr.Row(visible=False) as audio_record_row:
                    audio_input = gr.Audio(
                        type="filepath",
                        label="录制语音",
                    )
                    cancel_audio_btn = gr.Button("取消", size="sm")
                
                tts_audio = gr.Audio(
                    label="语音回复",
                    visible=False,
                )

    def _detect_image_mime_type(image_data: bytes, file_path: str = "") -> str:
        """
        检测图片文件的 MIME 类型。
        
        优先使用文件魔数（magic bytes）精确检测，避免仅靠扩展名判断。
        支持常见图片格式：JPEG, PNG, WebP, GIF, BMP, TIFF, SVG, ICO。
        
        参数：
        - image_data: 图片文件的二进制数据
        - file_path: 文件路径（用于扩展名回退检测）
        
        返回：
        - MIME 类型子类型（如 "jpeg", "png", "webp"）
        """
        if not image_data:
            return "png"
        
        try:
            if image_data[:4] == b'\x89PNG':
                return "png"
            if image_data[:2] == b'\xff\xd8':
                return "jpeg"
            if image_data[:4] == b'RIFF' and image_data[8:12] == b'WEBP':
                return "webp"
            if image_data[:6] in (b'GIF87a', b'GIF89a'):
                return "gif"
            if image_data[:2] == b'BM':
                return "bmp"
            if image_data[:4] in (b'II\x2a\x00', b'MM\x00\x2a'):
                return "tiff"
            if image_data[:4] == b'\x00\x00\x01\x00':
                return "ico"
            if image_data[:5] == b'<?xml' or image_data[:4] == b'<svg':
                return "svg+xml"
        except (IndexError, ValueError):
            pass
        
        ext = ""
        if file_path and "." in file_path:
            ext = file_path.rsplit(".", 1)[-1].lower()
        
        mime_map = {
            "jpg": "jpeg",
            "jpeg": "jpeg",
            "png": "png",
            "webp": "webp",
            "gif": "gif",
            "bmp": "bmp",
            "tiff": "tiff",
            "tif": "tiff",
            "svg": "svg+xml",
            "ico": "ico",
        }
        return mime_map.get(ext, "jpeg")

    def file_to_base64(filepath) -> str:
        """
        将图片文件转换为 Base64 编码字符串。
        
        支持 Gradio 6.x ImageData/FileData 对象（具有 path 属性）和字符串路径。
        使用文件魔数（magic bytes）精确检测 MIME 类型，而非依赖扩展名。
        
        参数：
        - filepath: 图片文件路径（str）或 Gradio ImageData/FileData 对象
        
        返回：
        - Base64 编码的 data URI 字符串（格式：data:image/{mime_type};base64,...）
        """
        if not filepath:
            return ""
        
        file_path = None
        
        if isinstance(filepath, str):
            file_path = filepath
        elif hasattr(filepath, 'path'):
            file_path = filepath.path
        elif hasattr(filepath, 'name'):
            file_path = filepath.name
        elif hasattr(filepath, 'file_path'):
            file_path = filepath.file_path
        elif hasattr(filepath, 'orig_name') and hasattr(filepath, 'url'):
            file_path = getattr(filepath, 'path', None) or filepath.orig_name
        
        if not file_path or not isinstance(file_path, str):
            logger.warning(f"Invalid image path: type={type(filepath)}, value={filepath}")
            return ""
        
        if not os.path.isfile(file_path):
            logger.warning(f"Image file not found: {file_path}")
            return ""
        
        try:
            with open(file_path, "rb") as f:
                image_data = f.read()
            
            if len(image_data) == 0:
                logger.warning(f"Image file is empty: {file_path}")
                return ""
            
            encoded = base64.b64encode(image_data).decode("utf-8")
            
            mime_type = _detect_image_mime_type(image_data, file_path)
            
            logger.info(f"Image encoded: path={file_path}, size={len(image_data)}bytes, mime={mime_type}")
            
            return f"data:image/{mime_type};base64,{encoded}"
        except Exception as e:
            logger.error(f"Failed to encode image: {str(e)}", exc_info=True)
            return ""

    def audio_to_text(audio_path) -> str:
        """
        将音频文件转换为文本（语音识别）。
        
        支持 Gradio 6.x FileData 对象（具有 path 属性）和字符串路径。
        
        参数：
        - audio_path: 音频文件路径（str）或 Gradio FileData 对象
        
        返回：
        - 识别出的文本，如果失败返回错误提示
        """
        if not audio_path:
            return ""
        
        file_path = None
        
        if isinstance(audio_path, str):
            file_path = audio_path
        elif hasattr(audio_path, 'path'):
            file_path = audio_path.path
        elif hasattr(audio_path, 'name'):
            file_path = audio_path.name
        elif hasattr(audio_path, 'file_path'):
            file_path = audio_path.file_path
        
        if not file_path or not isinstance(file_path, str):
            logger.warning(f"Invalid audio path: type={type(audio_path)}, value={audio_path}")
            return ""
        
        if not os.path.isfile(file_path):
            logger.warning(f"Audio file not found: {file_path}")
            return ""
            
        try:
            text = speech_recognizer.recognize(file_path)
            logger.info(f"ASR result: {text}")
            return text
        except Exception as e:
            logger.error(f"ASR failed: {str(e)}")
            return f"语音识别失败: {str(e)}"

    def get_session_title(messages: List[Dict[str, Any]]) -> str:
        """
        根据会话消息生成会话标题。
        
        取第一条用户消息的前 30 个字符作为标题，如果没有消息则返回"无标题会话"。
        
        参数：
        - messages: 会话消息列表
        
        返回：
        - 会话标题字符串
        """
        for msg in messages:
            if msg["role"] == "user":
                content = msg["content"]
                if isinstance(content, str) and len(content) > 0:
                    return content[:30] + "..." if len(content) > 30 else content
        return "无标题会话"

    def create_new_session():
        """
        创建新的聊天会话。
        
        流程：
        1. 生成新的 UUID 作为会话 ID
        2. 更新全局会话状态
        3. 在后台线程中创建数据库会话记录（不阻塞）
        4. 更新历史会话下拉列表
        
        返回：
        - 空消息列表（用于清空聊天窗口）
        - 空字符串（用于清空输入框）
        - 会话列表更新
        """
        global CURRENT_SESSION_ID, CHAT_SESSIONS
        session_id = str(uuid.uuid4())
        CURRENT_SESSION_ID = session_id
        CHAT_SESSIONS[session_id] = []
        
        # 异步创建数据库会话
        def create_session_async():
            try:
                create_session(title="新对话", messages=[], session_id=session_id)
                logger.info(f"New session created in DB: {session_id}")
            except Exception as e:
                logger.warning(f"Failed to create session in DB: {str(e)}")
        
        threading.Thread(target=create_session_async, daemon=True).start()
        
        try:
            return [], "", update_session_dropdown(force_refresh=True)
        except Exception:
            return [], "", gr.update()

    def _build_session_choices(sessions, current_session_id=None):
        """
        将会话列表构建为下拉框选项。
        
        参数：
        - sessions: 会话列表
        - current_session_id: 当前选中的会话 ID
        
        返回：
        - Tuple: (choices, selected_value)
        """
        choices = []
        seen_values = set()
        for s in sessions:
            label, session_id = _format_session_label(s)
            if session_id not in seen_values:
                seen_values.add(session_id)
                choices.append((label, session_id))
        
        current_value = current_session_id or CURRENT_SESSION_ID or ""
        
        # 如果当前值不在列表中，添加它
        valid_values = [c[1] for c in choices]
        if current_value and current_value not in valid_values:
            if current_value in CHAT_SESSIONS:
                messages = CHAT_SESSIONS[current_value]
                title = get_session_title(messages) if messages else "新对话"
            else:
                title = "新对话"
            choices.insert(0, (title, current_value))
        
        valid_values = [c[1] for c in choices]
        if current_value and current_value in valid_values:
            selected_value = current_value
        elif choices:
            selected_value = choices[0][1]
        else:
            selected_value = None
        
        return choices, selected_value

    def _refresh_session_cache_async():
        """
        异步刷新会话缓存（不阻塞调用方）。

        在后台线程中查询数据库并更新 SESSION_CACHE，
        避免在用户交互过程中因数据库慢查询而阻塞 Gradio 队列。
        """
        def refresh():
            try:
                client = get_supabase_client()
                def list_func(sb_client):
                    result = sb_client.table("chat_session").select("*").order("created_at", desc=True).range(0, 9).execute()
                    return result.data
                sessions = client.execute_with_client(list_func)
                with SESSION_CACHE["lock"]:
                    choices, selected_value = _build_session_choices(sessions, CURRENT_SESSION_ID)
                    SESSION_CACHE["choices"] = choices
                    SESSION_CACHE["selected_value"] = selected_value
                    SESSION_CACHE["updated_at"] = time.time()
                logger.info(f"Session cache refreshed: {len(choices)} sessions")
            except Exception as e:
                logger.warning(f"Failed to refresh session cache: {str(e)}")

        threading.Thread(target=refresh, daemon=True).start()

    def update_session_dropdown(force_refresh: bool = False):
        """
        更新历史会话下拉列表的选项（快速非阻塞版本）。
        
        使用内存缓存，命中时直接返回；缓存过期时异步刷新，
        避免在 Gradio queue 流中因数据库慢查询而阻塞。
        
        参数：
        - force_refresh: 是否强制同步刷新（仅用于新建/删除等必须立即生效的场景）
        
        返回：
        - 使用 gr.update() 更新 Dropdown 组件
        """
        now = time.time()
        with SESSION_CACHE["lock"]:
            cache_age = now - SESSION_CACHE["updated_at"]
            cached_choices = list(SESSION_CACHE["choices"])
            cached_selected = SESSION_CACHE["selected_value"]

        if not force_refresh and cached_choices and cache_age < SESSION_CACHE_TTL:
            current_value = CURRENT_SESSION_ID or cached_selected
            valid_values = [c[1] for c in cached_choices]
            selected = current_value if current_value in valid_values else (cached_selected or None)
            return gr.update(choices=cached_choices, value=selected)

        if force_refresh:
            try:
                client = get_supabase_client()
                def list_func(sb_client):
                    result = sb_client.table("chat_session").select("*").order("created_at", desc=True).range(0, 9).execute()
                    return result.data
                sessions = client.execute_with_client(list_func)
                choices, selected_value = _build_session_choices(sessions, CURRENT_SESSION_ID)
                with SESSION_CACHE["lock"]:
                    SESSION_CACHE["choices"] = choices
                    SESSION_CACHE["selected_value"] = selected_value
                    SESSION_CACHE["updated_at"] = time.time()
                logger.info(f"update_session_dropdown (forced): choices={len(choices)}")
                return gr.update(choices=choices, value=selected_value)
            except Exception as e:
                logger.warning(f"Failed to list sessions (force): {str(e)}")
                if cached_choices:
                    return gr.update(choices=cached_choices, value=cached_selected)
                return gr.update()
        else:
            _refresh_session_cache_async()
            current_value = CURRENT_SESSION_ID or cached_selected
            if cached_choices:
                valid_values = [c[1] for c in cached_choices]
                selected = current_value if current_value in valid_values else (cached_selected or None)
                return gr.update(choices=cached_choices, value=selected)
            return gr.update()

    def load_session(session_id: str):
        """
        加载指定会话的历史消息，并同步更新标签和收藏按钮状态。

        参数：
        - session_id: 会话 ID

        返回：
        - Tuple: (消息列表, 标签文本, 收藏按钮更新)
        """
        global CURRENT_SESSION_ID, CHAT_SESSIONS
        if not session_id:
            return [], "", gr.update()
        CURRENT_SESSION_ID = session_id
        try:
            from uuid import UUID
            session = get_session_by_id(UUID(session_id))
            if session:
                messages = session.get("messages", [])
                CHAT_SESSIONS[session_id] = messages
                tag = SESSION_TAGS.get(session_id, "")
                fav_label = "⭐ 已收藏" if session_id in FAVORITE_SESSIONS else "⭐ 收藏"
                return messages, tag, gr.update(value=fav_label)
        except (ValueError, Exception) as e:
            logger.error(f"Failed to load session: {str(e)}")
        return [], "", gr.update()

    def clear_current_session():
        """
        清空当前会话的所有消息。
        
        返回：
        - 空消息列表（用于清空聊天窗口）
        - 会话列表更新
        """
        global CHAT_SESSIONS, CURRENT_SESSION_ID
        if CURRENT_SESSION_ID:
            CHAT_SESSIONS[CURRENT_SESSION_ID] = []
            try:
                update_session(
                    CURRENT_SESSION_ID,
                    title="新对话",
                    summary=None,
                    append_message=None,
                )
            except Exception as e:
                logger.warning(f"Failed to clear session in DB: {str(e)}")
        return [], update_session_dropdown(force_refresh=True)

    def delete_current_session(session_id: str):
        """
        删除指定会话。
        
        参数：
        - session_id: 要删除的会话 ID
        
        返回：
        - 空消息列表（用于清空聊天窗口）
        - 会话列表更新（更新下拉框）
        """
        global CURRENT_SESSION_ID, CHAT_SESSIONS
        if session_id and session_id != "":
            try:
                from uuid import UUID
                delete_session(UUID(session_id))
            except (ValueError, Exception) as e:
                logger.error(f"Failed to delete session: {str(e)}")
            if CURRENT_SESSION_ID == session_id:
                CURRENT_SESSION_ID = ""
                CHAT_SESSIONS.pop(session_id, None)
                new_session_id = str(uuid.uuid4())
                CURRENT_SESSION_ID = new_session_id
                CHAT_SESSIONS[new_session_id] = []
                try:
                    create_session(title="新对话", messages=[], session_id=new_session_id)
                except Exception:
                    pass
                return [], gr.update(choices=[("新对话", new_session_id)], value=new_session_id)
        return [], update_session_dropdown(force_refresh=True)

    def chat_response(
        message: str,
        history: List[Dict[str, Any]],
        image_path: Optional[str] = None,
        audio_path: Optional[str] = None,
        model_type: str = "deepseek",
    ) -> Tuple[str, List[Dict[str, Any]], Any, Any]:
        """
        处理用户消息并生成响应（核心对话函数）。
        
        支持多模态输入：文本、语音、图片。
        使用 AgentGraph 进行工具调用和 LLM 推理。
        
        参数：
        - message: 用户输入的文本消息
        - history: 当前对话历史消息列表
        - image_path: 上传的图片文件路径（可选）
        - audio_path: 上传的音频文件路径（可选）
        - model_type: 选择的大模型类型（deepseek / zhipu）
        
        返回：
        - Tuple: (输入框内容, 更新后的历史消息, TTS音频数据, 会话列表更新)
        
        执行流程：
        1. 处理多模态输入（语音转文字、图片转 Base64）
        2. 拼接完整消息
        3. 如果没有活跃会话，创建新会话
        4. 将用户消息添加到历史
        5. 在聊天框中显示处理状态
        6. 调用 AgentGraph 运行代理工作流
        7. 流式输出回答内容（包含响应时间）
        8. 更新数据库会话记录
        9. 生成 TTS 语音（可选，非阻塞）
        """
        global CHAT_SESSIONS, CURRENT_SESSION_ID, _chat_in_progress

        with _chat_lock:
            if _chat_in_progress:
                yield "", history, None, gr.update()
                return
            _chat_in_progress = True

        try:
            import time

            audio_text = audio_to_text(audio_path) if audio_path else ""
            image_base64 = file_to_base64(image_path) if image_path else ""

            full_message = message
            if audio_text:
                full_message += f"\n[语音内容]: {audio_text}"
            if image_base64:
                full_message += f"\n[图片已上传]"

            if not full_message.strip():
                return "", history, None, gr.update()

            if not CURRENT_SESSION_ID:
                try:
                    create_new_session()
                except Exception as e:
                    logger.warning(f"Failed to create session: {str(e)}")
                    if not CURRENT_SESSION_ID:
                        session_id = str(uuid.uuid4())
                        CURRENT_SESSION_ID = session_id
                        CHAT_SESSIONS[session_id] = []

            history.append({"role": "user", "content": full_message})
            try:
                dropdown_update = update_session_dropdown()
            except Exception:
                dropdown_update = gr.update()
            yield "", history, None, dropdown_update

            total_start_time = time.time()

            try:
                history.append({"role": "assistant", "content": "⏳ 正在处理您的请求..."})
                yield "", history, None, gr.update()
                
                history[-1]["content"] = "🔍 正在分析问题意图..."
                yield "", history, None, gr.update()
                
                step_start = time.time()
                image_urls = [image_base64] if image_base64 else []
                history_for_llm = CHAT_SESSIONS.get(CURRENT_SESSION_ID, [])[-20:]
                
                result_container = {}
                error_container = {}
                
                def run_agent():
                    try:
                        result_container["result"] = agent_graph.run(
                            full_message, CURRENT_SESSION_ID, model_type, image_urls, history_for_llm
                        )
                    except Exception as e:
                        error_container["error"] = e
                
                agent_thread = threading.Thread(target=run_agent, daemon=True)
                agent_thread.start()
                agent_thread.join(timeout=120)
                
                if agent_thread.is_alive():
                    logger.error("agent_graph.run() timed out after 120s")
                    history[-1]["content"] = "抱歉，请求处理超时，请重试。"
                    elapsed_time = time.time() - total_start_time
                    yield "", history, None, gr.update()
                    return
                
                if "error" in error_container:
                    raise error_container["error"]
                
                result = result_container.get("result", {})
                step_end = time.time()
                logger.info(f"agent_graph.run() completed in {step_end - step_start:.2f} seconds")
                
                answer = result.get("final_answer", "抱歉，没有生成回答。")
                
                if not answer or not answer.strip():
                    answer = "抱歉，模型未能生成有效回答，请重试。"

                elapsed_time = time.time() - total_start_time
                logger.info(f"Total response time: {elapsed_time:.2f} seconds")
                answer_with_time = f"{answer}\n\n<span style='font-size: 12px; color: #999;'>⏱️ {elapsed_time:.2f}秒</span>"

                if CURRENT_SESSION_ID not in CHAT_SESSIONS:
                    CHAT_SESSIONS[CURRENT_SESSION_ID] = []
                full_history = CHAT_SESSIONS[CURRENT_SESSION_ID]
                full_history.append({"role": "user", "content": full_message})
                full_history.append({"role": "assistant", "content": answer})

                session_title = get_session_title(full_history)

                def update_db_async():
                    try:
                        update_session(
                            CURRENT_SESSION_ID,
                            title=session_title,
                            append_messages=[
                                {"role": "user", "content": full_message},
                                {"role": "assistant", "content": answer},
                            ],
                        )
                        logger.info(f"Session title updated to: {session_title}")
                    except Exception as e:
                        logger.warning(f"Failed to update session in DB: {str(e)}")

                db_thread = threading.Thread(target=update_db_async, daemon=True)
                db_thread.start()

                history[-1]["content"] = ""
                for i in range(len(answer)):
                    history[-1]["content"] = answer[:i+1]
                    yield "", history, None, gr.update()
                
                history[-1]["content"] = answer_with_time
                try:
                    dropdown_update = update_session_dropdown()
                except Exception:
                    dropdown_update = gr.update()
                yield "", history, None, dropdown_update

                try:
                    if len(answer.strip()) >= 2:
                        def generate_tts_async():
                            try:
                                audio_data = text_to_speech.synthesize(answer, output_format="mp3")
                                if audio_data and len(audio_data) > 0:
                                    audio_path = os.path.join(TEMP_DIR, f"tmp_audio_{uuid.uuid4().hex[:8]}.mp3")
                                    with open(audio_path, "wb") as f:
                                        f.write(audio_data)
                                    logger.info(f"TTS generated async: {audio_path}")
                            except Exception as e:
                                logger.warning(f"Async TTS failed: {str(e)}")
                        
                        tts_thread = threading.Thread(target=generate_tts_async, daemon=True)
                        tts_thread.start()
                except Exception as e:
                    logger.warning(f"TTS scheduling failed: {str(e)}")

            except Exception as e:
                elapsed_time = time.time() - total_start_time
                logger.error(f"Chat response error: {str(e)}", exc_info=True)
                error_msg = f"抱歉，处理请求时出错：{str(e)}\n\n<span style='font-size: 12px; color: #999;'>⏱️ {elapsed_time:.2f}秒</span>"
                if history and history[-1]["role"] == "assistant":
                    history[-1]["content"] = error_msg
                else:
                    history.append({"role": "assistant", "content": error_msg})
                yield "", history, None, gr.update()

        finally:
            with _chat_lock:
                _chat_in_progress = False

    def play_tts(message: str, history: List[Dict[str, Any]]):
        """
        播放最后一条助手消息的语音。

        功能特性：
        - 支持列表内容类型（Gradio Chatbot 可能返回 list 格式内容）
        - 空文本安全处理，返回 gr.update() 不触发错误
        - 使用绝对路径保存音频文件，确保 Gradio 可正确加载
        - 通过 gr.update(value=..., visible=True) 显示音频播放器

        参数：
        - message: 用户当前输入（未使用，保留接口兼容）
        - history: 聊天历史记录列表

        返回：
        - gr.update(): Gradio 组件更新指令，包含音频文件路径和可见性设置
        """
        if not history:
            return gr.update()
        last_message = history[-1] if history else None
        if not last_message or last_message.get("role") != "assistant":
            return gr.update()
        last_answer = last_message.get("content", "")
        if isinstance(last_answer, list):
            text_parts = []
            for item in last_answer:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            last_answer = " ".join(text_parts)
        if not last_answer or not isinstance(last_answer, str) or len(last_answer.strip()) < 2:
            return gr.update()
        try:
            audio_data = text_to_speech.synthesize(last_answer, output_format="mp3")
            if not audio_data or len(audio_data) == 0:
                logger.warning("play_tts: TTS returned empty data")
                return gr.update()
            audio_path = os.path.join(TEMP_DIR, f"tmp_tts_{uuid.uuid4().hex[:8]}.mp3")
            with open(audio_path, "wb") as f:
                f.write(audio_data)
            logger.info(f"TTS audio saved to {audio_path}")
            return gr.update(value=audio_path, visible=True)
        except Exception as e:
            logger.error(f"TTS failed: {str(e)}")
            return gr.update()

    # ========== 事件绑定 ==========
    
    def on_chat_tab_load():
        global CURRENT_SESSION_ID, CHAT_SESSIONS
        session_id = str(uuid.uuid4())
        CURRENT_SESSION_ID = session_id
        CHAT_SESSIONS[session_id] = []
        
        def init_session_async():
            try:
                create_session(title="新对话", messages=[], session_id=session_id)
                logger.info("Session created on page load")
            except Exception as e:
                logger.warning(f"Failed to create session on load: {str(e)}")
        
        load_thread = threading.Thread(target=init_session_async, daemon=True)
        load_thread.start()
        
        _refresh_session_cache_async()
        
        with SESSION_CACHE["lock"]:
            cached_choices = list(SESSION_CACHE["choices"])
            cached_selected = SESSION_CACHE["selected_value"]
        
        if cached_choices:
            current_value = session_id
            valid_values = [c[1] for c in cached_choices]
            if current_value not in valid_values:
                cached_choices.insert(0, ("新对话", session_id))
            return [], "", gr.update(choices=cached_choices, value=session_id)
        else:
            return [], "", gr.update(choices=[("新对话", session_id)], value=session_id)
    
    demo.load(
        on_chat_tab_load,
        outputs=[chatbot, user_input, session_list],
    )
    
    # 新建对话按钮：点击后清空聊天窗口和输入框，并更新会话列表
    new_session_btn.click(create_new_session, outputs=[chatbot, user_input, session_list])
    
    # 清空按钮：清空当前会话的所有消息，并更新会话列表
    clear_btn.click(clear_current_session, outputs=[chatbot, session_list])
    
    # 删除按钮：删除选中的会话
    delete_session_btn.click(
        delete_current_session,
        inputs=[session_list],
        outputs=[chatbot, session_list],
    )
    
    # 清理旧会话按钮：删除除当前会话外的所有会话
    def cleanup_old_sessions():
        global CURRENT_SESSION_ID, CHAT_SESSIONS
        try:
            client = get_supabase_client()
            def list_func(sb_client):
                result = sb_client.table("chat_session").select("id").execute()
                return result.data
            all_sessions = client.execute_with_client(list_func)
            
            current_id = CURRENT_SESSION_ID
            deleted_count = 0
            for s in all_sessions:
                sid = str(s["id"])
                if sid != current_id:
                    try:
                        from uuid import UUID
                        delete_session(UUID(sid))
                        CHAT_SESSIONS.pop(sid, None)
                        deleted_count += 1
                    except Exception:
                        pass
            
            logger.info(f"Cleaned up {deleted_count} old sessions")
        except Exception as e:
            logger.error(f"Failed to cleanup old sessions: {str(e)}")
        
        return [], update_session_dropdown(force_refresh=True)
    
    cleanup_btn.click(
        cleanup_old_sessions,
        outputs=[chatbot, session_list],
    )
    
    # 会话列表变更：加载选中会话的历史消息，并同步标签和收藏状态
    session_list.change(load_session, inputs=[session_list], outputs=[chatbot, tag_input, favorite_btn])

    # 导出按钮：将当前会话导出为 Markdown 文件
    def export_current_session():
        if not CURRENT_SESSION_ID:
            return gr.update()
        messages = CHAT_SESSIONS.get(CURRENT_SESSION_ID, [])
        if not messages:
            return gr.update()
        content = "# 会话导出\n\n"
        for msg in messages:
            role = msg.get("role", "")
            msg_content = msg.get("content", "")
            if isinstance(msg_content, list):
                text_parts = []
                for item in msg_content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif isinstance(item, str):
                        text_parts.append(item)
                msg_content = " ".join(text_parts)
            if role == "user":
                content += f"## 用户\n{msg_content}\n\n"
            elif role == "assistant":
                content += f"## 助手\n{msg_content}\n\n"
        filename = f"chat_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        filepath = os.path.join(TEMP_DIR, filename)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Session exported to {filepath}")
            return gr.update(value=filepath, visible=True)
        except Exception as e:
            logger.error(f"Export failed: {str(e)}")
            return gr.update()

    export_btn.click(
        export_current_session,
        outputs=[export_file],
    )

    # 收藏按钮：标记当前会话为收藏状态
    def toggle_favorite(session_id):
        if not session_id:
            return gr.update(), gr.update()
        if session_id in FAVORITE_SESSIONS:
            del FAVORITE_SESSIONS[session_id]
            btn_label = "⭐ 收藏"
        else:
            FAVORITE_SESSIONS[session_id] = True
            btn_label = "⭐ 已收藏"
        return gr.update(value=btn_label), update_session_dropdown(force_refresh=True)

    favorite_btn.click(
        toggle_favorite,
        inputs=[session_list],
        outputs=[favorite_btn, session_list],
    )

    # 标签输入框：为当前会话添加标签（回车保存）
    def save_session_tag(tag_text, session_id):
        if not session_id:
            return gr.update()
        tag = tag_text.strip() if tag_text else ""
        if tag:
            SESSION_TAGS[session_id] = tag
        else:
            SESSION_TAGS.pop(session_id, None)
        return update_session_dropdown(force_refresh=True)

    tag_input.submit(
        save_session_tag,
        inputs=[tag_input, session_list],
        outputs=[session_list],
    )

    # 主题切换按钮：切换暗色/亮色主题
    def toggle_theme():
        global _theme_dark
        _theme_dark = not _theme_dark
        if _theme_dark:
            return gr.update(value="☀️ 亮色")
        else:
            return gr.update(value="🌙 暗色")

    theme_btn.click(
        fn=toggle_theme,
        js="() => { document.documentElement.classList.toggle('dark'); }",
        outputs=[theme_btn],
    )

    # 附件按钮：显示图片上传区域
    def on_attach_click():
        logger.info("Attach button clicked!")
        return gr.update(visible=True)
    
    attach_btn.click(
        on_attach_click,
        outputs=[image_upload_row],
    )
    
    # 取消图片上传按钮：隐藏图片上传区域，清空图片输入
    cancel_image_btn.click(
        lambda: [gr.update(visible=False), None],
        outputs=[image_upload_row, image_input],
    )
    
    # 麦克风按钮：显示音频录制区域
    def on_mic_click():
        logger.info("Mic button clicked!")
        return gr.update(visible=True)
    
    mic_btn.click(
        on_mic_click,
        outputs=[audio_record_row],
    )
    
    # 取消音频录制按钮：隐藏音频录制区域，清空音频输入
    cancel_audio_btn.click(
        lambda: [gr.update(visible=False), None],
        outputs=[audio_record_row, audio_input],
    )
    
    # 链接按钮：清空输入框并提示用户输入链接
    def on_link_click():
        logger.info("Link button clicked!")
        return "请输入链接..."
    
    link_btn.click(
        on_link_click,
        outputs=[user_input],
    )

    # 发送按钮：处理用户消息并生成响应
    send_btn.click(
        chat_response,
        inputs=[user_input, chatbot, image_input, audio_input, model_selector],
        outputs=[user_input, chatbot, tts_audio, session_list],
    )
    # 发送后隐藏上传区域（合并为一个处理器）
    def on_send_hide():
        return [
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            None,
        ]
    
    send_btn.click(
        on_send_hide,
        outputs=[image_upload_row, audio_record_row, image_input, audio_input],
    )
    
    # 输入框回车：同样触发消息发送
    user_input.submit(
        chat_response,
        inputs=[user_input, chatbot, image_input, audio_input, model_selector],
        outputs=[user_input, chatbot, tts_audio, session_list],
    )
    # 回车后隐藏上传区域（合并为一个处理器）
    def on_submit_hide():
        return [
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            None,
        ]
    
    user_input.submit(
        on_submit_hide,
        outputs=[image_upload_row, audio_record_row, image_input, audio_input],
    )

    # TTS 按钮：播放最后一条助手回答的语音
    tts_btn.click(
        play_tts,
        inputs=[user_input, chatbot],
        outputs=[tts_audio],
    )


def create_kb_tab(demo):
    """
    创建知识库管理界面标签页。
    
    界面布局：
    - 左侧面板（scale=1）：知识库管理 + 文件上传
    - 右侧面板（scale=2）：检索调试
    
    功能组件：
    1. 知识库管理：创建知识库、删除知识库、知识库列表
    2. 文件上传：支持 PDF、MD、TXT、CSV、JSON 格式，批量上传
    3. 检索调试：输入查询文本，测试检索效果，查看结果和分数
    
    参数：
    - demo: Gradio Blocks 对象，用于注册界面组件和事件
    """
    with gr.Tab("知识库管理"):
        with gr.Row():
            # 左侧面板：知识库管理和文件上传
            with gr.Column(scale=1, min_width=250):
                # 知识库名称输入框
                kb_name_input = gr.Textbox(label="知识库名称", placeholder="输入知识库名称")
                
                # 知识库操作按钮
                with gr.Row():
                    create_kb_btn = gr.Button("创建知识库", variant="primary")  # 创建知识库
                    delete_kb_btn = gr.Button("删除知识库", variant="stop")    # 删除知识库
                    view_kb_btn = gr.Button("查看内容", variant="secondary")  # 查看知识库内容

                # 知识库列表下拉框
                kb_list = gr.Dropdown(label="选择知识库", choices=[], interactive=True, allow_custom_value=True)
                refresh_kb_btn = gr.Button("刷新知识库列表")

                # 文件上传区域
                gr.Markdown("### 文件上传")
                file_upload = gr.File(
                    label="上传文档",
                    file_types=[".pdf", ".md", ".txt", ".csv", ".json"],
                    file_count="multiple",
                    type="filepath",
                )
                upload_btn = gr.Button("上传并向量化", variant="primary")
                upload_status = gr.Textbox(label="上传状态", interactive=False)

            # 右侧面板：检索调试 + 知识库内容查看
            with gr.Column(scale=2):
                with gr.Tab("知识库内容"):
                    view_kb_content = gr.Dataframe(
                        headers=["序号", "文件名", "内容预览", "页码", "字符数"],
                        datatype=["number", "str", "str", "str", "number"],
                        row_count=(0, 200),
                        column_count=(5, 5),
                        interactive=True,
                        label="知识库文档列表（点击行查看完整内容）",
                    )
                    view_kb_detail = gr.Markdown(
                        label="文档详情",
                        value="点击上方表格中的任意一行，查看该分片的完整内容",
                    )
                    # 保存完整文档数据的状态
                    kb_docs_state = gr.State(value=[])
                
                with gr.Tab("检索调试"):
                    query_input = gr.Textbox(label="测试查询", placeholder="输入测试文本")
                    search_btn = gr.Button("检索", variant="primary")
                    top_k_slider = gr.Slider(label="返回数量", minimum=1, maximum=20, value=5)

                    retrieval_results = gr.JSON(label="检索结果")   # 完整检索结果（JSON格式）
                    result_preview = gr.Markdown(label="结果预览")    # 结果预览（Markdown格式）

    def list_kbs():
        """
        获取所有知识库名称列表。
        
        使用高效查询获取 distinct kb_name，避免全表扫描。
        
        返回：
        - kb_names: 知识库名称列表（用于更新 Dropdown 组件）
        """
        try:
            kb_names = get_knowledge_base_names()
            logger.info(f"List KBs returned: {kb_names}")
            return kb_names
        except Exception as e:
            logger.error(f"Failed to list KBs: {str(e)}")
            return []

    def handle_file_upload(files, kb_name: str):
        """
        处理文件上传并向量化。
        
        处理流程：
        1. 验证文件和知识库名称
        2. 创建嵌入模型
        3. 遍历每个文件：
           - 验证文件有效性（空文件、大小限制、类型限制）
           - 使用 DocumentParserFactory 解析文件内容
           - 使用 TextSplitter 切分为 chunks
           - 对每个 chunk 生成向量
           - 将 chunk 和向量插入数据库
        4. 返回处理结果统计
        
        参数：
        - files: 上传的文件列表（兼容 Gradio 5/6 各种对象类型）
        - kb_name: 目标知识库名称
        
        返回：
        - 处理状态消息（成功/失败数量及失败原因）
        """
        if not files:
            return "❌ 请选择文件"
        if not kb_name:
            return "❌ 请输入知识库名称"

        # 规范化 files 为列表（处理 Gradio 可能传递单个对象的情况）
        if not isinstance(files, (list, tuple)):
            files = [files]

        logger.info(f"handle_file_upload called: files_count={len(files)}, types={[type(f).__name__ for f in files]}")

        try:
            embedding = embedding_factory.create_embedding("zhipu")
        except Exception as e:
            logger.error(f"Failed to create embedding model: {str(e)}")
            return f"❌ 嵌入模型初始化失败: {str(e)}"

        total_files = len(files)
        success_count = 0
        fail_count = 0
        fail_reasons = []
        MAX_FILE_SIZE_MB = 50
        MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
        ALLOWED_EXTENSIONS = {"txt", "md", "markdown", "pdf", "json", "csv"}

        for idx, file in enumerate(files):
            try:
                # 使用兼容层提取文件信息（支持 Gradio 5/6 各种对象类型）
                file_path, file_name, file_content = extract_file_info(file)
                
                logger.info(f"Processing file {idx+1}/{total_files}: type={type(file).__name__}, path={file_path}, name={file_name}, size={len(file_content)}B")
                
                if not file_path or not os.path.isfile(file_path):
                    fail_count += 1
                    fail_reasons.append(f"{file_name or file_path or '未知文件'}: 文件对象无效 (type={type(file).__name__})")
                    continue
                
                if not file_name:
                    file_name = os.path.basename(file_path)

                file_ext = get_file_extension(file_name)
                
                if file_ext not in ALLOWED_EXTENSIONS:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 不支持的文件类型 '{file_ext}'，仅支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}")
                    continue
                
                if not file_content:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 文件为空")
                    continue

                if not is_file_size_valid(file_content, MAX_FILE_SIZE_BYTES):
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 文件大小 {len(file_content)/1024/1024:.1f}MB 超过限制 {MAX_FILE_SIZE_MB}MB")
                    continue

                try:
                    text, metadata = DocumentParserFactory.parse(file_name, file_content)
                except Exception as parse_error:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 解析失败 - {str(parse_error)[:100]}")
                    logger.error(f"Failed to parse file {file_name}: {str(parse_error)}")
                    continue

                if not text or not text.strip():
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 解析后内容为空")
                    continue

                try:
                    chunks = text_splitter.split(
                        text=text,
                        file_name=file_name,
                        file_type=file_ext,
                        category=kb_name,
                    )
                except Exception as split_error:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 切分失败 - {str(split_error)[:100]}")
                    logger.error(f"Failed to split file {file_name}: {str(split_error)}")
                    continue

                if not chunks:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 切分后无有效内容")
                    continue

                chunk_success = 0
                chunk_fail = 0
                
                for chunk in chunks:
                    try:
                        chunk_text = chunk.get("text", "")
                        chunk_metadata = chunk.get("metadata", {})
                        
                        if not chunk_text or not chunk_text.strip():
                            continue
                        
                        try:
                            vector = embedding.embed_query(chunk_text)
                        except Exception as embed_error:
                            chunk_fail += 1
                            logger.error(f"Failed to embed chunk in {file_name}: {str(embed_error)}")
                            continue

                        try:
                            insert_document(
                                content=chunk_text,
                                vector=vector,
                                filename=file_name,
                                page_number=chunk_metadata.get("page_number"),
                                category=kb_name,
                                metadata=chunk_metadata,
                                kb_name=kb_name,
                            )
                            chunk_success += 1
                        except Exception as db_error:
                            chunk_fail += 1
                            logger.error(f"Failed to insert chunk in {file_name}: {str(db_error)}")
                            continue
                            
                    except Exception as chunk_error:
                        chunk_fail += 1
                        logger.error(f"Unexpected error processing chunk in {file_name}: {str(chunk_error)}")
                        continue

                if chunk_success > 0:
                    success_count += 1
                    logger.info(f"Successfully processed file: {file_name}, {chunk_success} chunks inserted")
                    if chunk_fail > 0:
                        fail_reasons.append(f"{file_name}: 部分chunk失败 ({chunk_fail}/{len(chunks)})")
                else:
                    fail_count += 1
                    fail_reasons.append(f"{file_name}: 所有chunk处理失败")
                    
            except Exception as e:
                fail_count += 1
                fail_reasons.append(f"{file_name or '未知文件'}: 未知错误 - {str(e)[:100]}")
                logger.error(f"Unexpected error processing file {file_name}: {str(e)}", exc_info=True)

        result_msg = f"✅ 处理完成：成功 {success_count} 个，失败 {fail_count} 个"
        
        if fail_reasons:
            result_msg += "\n\n❌ 失败详情："
            result_msg += "\n".join([f"  • {reason}" for reason in fail_reasons[:10]])
            if len(fail_reasons) > 10:
                result_msg += f"\n  • ... 还有 {len(fail_reasons) - 10} 个失败"

        return result_msg

    def handle_search(query: str, kb_name: str, top_k: float):
        """
        执行知识库检索。
        
        使用 RetrievalPipeline 进行检索，支持多路径检索（向量检索 + BM25）。
        
        参数：
        - query: 查询文本
        - kb_name: 知识库名称（可选，为空则检索所有知识库）
        - top_k: 返回结果数量（从 Slider 组件获取，为浮点数）
        
        返回：
        - Tuple: (检索结果列表, 结果预览文本)
        """
        if not query:
            return [], "请输入查询文本"

        try:
            # 将 top_k 转换为整数（Slider 组件返回浮点数）
            top_k_int = int(top_k)
            
            # 创建检索管道并执行检索
            pipeline = RetrievalPipeline(top_k=top_k_int)
            results = pipeline.retrieve(query, kb_name)

            # 生成结果预览文本
            preview_text = ""
            for i, result in enumerate(results, 1):
                preview_text += f"## 结果 {i} (分数: {result['score']:.4f})\n\n"
                preview_text += f"{result['content'][:300]}...\n\n"
                if result.get("metadata"):
                    meta = result["metadata"]
                    preview_text += f"来源: {meta.get('file_name', '')} | "
                    preview_text += f"类型: {meta.get('file_type', '')}\n\n"

            return results, preview_text if preview_text else "没有找到相关结果"

        except Exception as e:
            logger.error(f"Search failed: {str(e)}")
            return [], f"检索失败：{str(e)}"

    def handle_create_kb(kb_name: str):
        """
        创建知识库。
        
        实际上是创建一个空的知识库名称，真正的数据会在上传文件时添加。
        
        参数：
        - kb_name: 知识库名称
        
        返回：
        - Tuple: (状态消息, 更新后的知识库列表)
        """
        if not kb_name:
            return "请输入知识库名称", gr.update(choices=list_kbs())
        try:
            logger.info(f"Creating KB: {kb_name}")
            return f"知识库 '{kb_name}' 已创建（上传文件后生效）", gr.update(choices=list_kbs())
        except Exception as e:
            return f"创建失败：{str(e)}", gr.update(choices=list_kbs())

    def handle_delete_kb(kb_name: str):
        """
        删除知识库及其所有文档。
        
        通过删除该知识库下的所有文档来实现知识库删除。
        
        参数：
        - kb_name: 知识库名称
        
        返回：
        - Tuple: (状态消息, 更新后的知识库列表)
        """
        if not kb_name:
            return "请选择知识库", gr.update(choices=list_kbs())
        try:
            documents = get_documents_by_kb(kb_name)
            filenames = list(set(doc.get("filename", "") for doc in documents))
            
            for filename in filenames:
                delete_documents_by_filename(filename)
            
            return f"知识库 '{kb_name}' 已删除", gr.update(choices=list_kbs())
        except Exception as e:
            return f"删除失败：{str(e)}", gr.update(choices=list_kbs())

    def handle_view_kb(kb_name: str):
        """
        查看知识库内容。
        
        获取指定知识库的所有文档，以表格形式展示。
        
        参数：
        - kb_name: 知识库名称
        
        返回：
        - Tuple: (表格数据, 状态信息, 完整文档数据)
        """
        if not kb_name:
            return [], "", []
        try:
            documents = get_documents_by_kb(kb_name)
            
            # 按文件名分组统计
            file_stats = {}
            for doc in documents:
                filename = doc.get("filename", "未知文件")
                if filename not in file_stats:
                    file_stats[filename] = {"count": 0, "total_chars": 0}
                file_stats[filename]["count"] += 1
                file_stats[filename]["total_chars"] += len(doc.get("content", ""))
            
            # 构建表格数据
            table_data = []
            for i, doc in enumerate(documents):
                filename = doc.get("filename", "未知文件")
                content = doc.get("content", "")
                page_number = doc.get("page_number", "")
                
                # 内容预览：截取前300个字符
                content_preview = content[:300] + "..." if len(content) > 300 else content
                
                table_data.append([i+1, filename, content_preview, page_number or "-", len(content)])
            
            # 生成状态信息
            total_chunks = len(documents)
            total_files = len(file_stats)
            status_msg = f"共 {total_chunks} 条文档（来自 {total_files} 个文件）"
            
            # 添加文件统计
            file_info = "\n📁 文件统计："
            for fname, stats in file_stats.items():
                file_info += f"\n  • {fname}: {stats['count']} 个分片, {stats['total_chars']} 字符"
            status_msg += file_info
            
            logger.info(f"View KB '{kb_name}': {total_chunks} documents from {total_files} files")
            return table_data, status_msg, documents
        except Exception as e:
            logger.error(f"Failed to view KB: {str(e)}")
            return [], f"查看失败：{str(e)}", []

    def handle_select_row(selected_row, docs_state):
        """
        点击表格行时显示完整内容。
        
        参数：
        - selected_row: 选中行的信息（Gradio 6.x 格式）
        - docs_state: 完整文档数据
        
        返回：
        - 选中文档的完整内容
        """
        if not docs_state:
            return "⚠️ 请先点击「查看内容」按钮加载知识库"
        
        try:
            # Gradio 6.x Dataframe select 事件返回的格式
            row_idx = None
            
            if isinstance(selected_row, dict):
                # {'row_index': 0, 'column_1': 'value', ...}
                row_idx = selected_row.get("row_index", None)
                if row_idx is None and "index" in selected_row:
                    row_idx = selected_row["index"]
            elif isinstance(selected_row, list) and len(selected_row) > 0:
                # [[col1, col2, col3], ...] 或 [row_idx]
                if isinstance(selected_row[0], int):
                    row_idx = selected_row[0]
                elif isinstance(selected_row[0], list) and len(selected_row) > 0:
                    # 可能是 [[row_idx, ...], ...] 格式
                    row_idx = selected_row[0][0] if isinstance(selected_row[0][0], int) else None
            
            # 如果无法确定索引，尝试从表格第一列（序号）推断
            if row_idx is None and isinstance(selected_row, dict):
                # 尝试从"序号"列获取
                for key in selected_row:
                    if key in ("序号", "row_index", "index"):
                        try:
                            row_idx = int(selected_row[key]) - 1  # 序号从1开始，转为0索引
                        except (ValueError, TypeError):
                            pass
                        break
            
            if row_idx is None:
                return "❌ 无法确定选中的行，请重新点击表格"
            
            row_idx = int(row_idx)
            if row_idx < 0:
                row_idx += 1  # 修正序号偏差
            
            if 0 <= row_idx < len(docs_state):
                doc = docs_state[row_idx]
                content = doc.get("content", "")
                filename = doc.get("filename", "未知文件")
                page_number = doc.get("page_number", "")
                chunk_index = doc.get("chunk_index", "")
                metadata = doc.get("metadata", {})
                
                # 构建详细显示
                header = f"📄 **文件**: {filename}"
                if chunk_index:
                    header += f" | **分片**: {chunk_index}"
                if page_number:
                    header += f" | **页码**: {page_number}"
                header += f"\n📏 **字符数**: {len(content)}"
                if metadata:
                    meta_str = " | ".join([f"{k}: {v}" for k, v in metadata.items() if v])
                    if meta_str:
                        header += f"\n🏷️ **元数据**: {meta_str}"
                header += "\n" + "=" * 50 + "\n\n"
                
                # 格式化为 Markdown
                result = header + content
                
                # 如果内容很长，添加截断提示
                if len(content) > 5000:
                    result += "\n\n---\n*（内容超过 5000 字符，已截断显示）*"
                
                return result
            else:
                return f"❌ 行索引 {row_idx} 超出范围（共 {len(docs_state)} 条文档）"
        except Exception as e:
            import traceback
            logger.error(f"Failed to select row: {str(e)}\n{traceback.format_exc()}")
            return f"❌ 显示失败：{str(e)}\n\n请尝试重新点击表格行"

    # ========== 事件绑定 ==========
    
    # 刷新按钮：更新知识库列表
    refresh_kb_btn.click(
        lambda: gr.update(choices=list_kbs()),
        outputs=[kb_list],
    )
    
    # 创建知识库按钮：创建新知识库并更新列表
    create_kb_btn.click(
        handle_create_kb,
        inputs=[kb_name_input],
        outputs=[upload_status, kb_list],
    )
    
    # 删除知识库按钮：删除选中知识库并更新列表
    delete_kb_btn.click(
        handle_delete_kb,
        inputs=[kb_list],
        outputs=[upload_status, kb_list],
    )
    
    # 查看知识库按钮：显示知识库内容
    view_kb_btn.click(
        handle_view_kb,
        inputs=[kb_list],
        outputs=[view_kb_content, view_kb_detail, kb_docs_state],
    )
    
    # 点击表格行：显示完整文档内容
    view_kb_content.select(
        handle_select_row,
        inputs=[kb_docs_state],
        outputs=[view_kb_detail],
    )
    
    # 上传按钮：处理文件上传并向量化
    upload_btn.click(
        handle_file_upload,
        inputs=[file_upload, kb_name_input],
        outputs=[upload_status],
    )
    
    # 检索按钮：执行知识库检索
    search_btn.click(
        handle_search,
        inputs=[query_input, kb_list, top_k_slider],
        outputs=[retrieval_results, result_preview],
    )

    # 页面加载时：初始化知识库列表
    demo.load(
        lambda: gr.update(choices=list_kbs()),
        outputs=[kb_list],
    )


def main():
    """
    应用程序主入口函数。
    
    执行流程：
    1. 配置自定义 CSS 样式（参考豆包界面设计）
    2. 创建 Gradio Blocks 应用
    3. 注册两个标签页：私人助手和知识库管理
    4. 启动 Gradio 服务器
    
    CSS 样式说明：
    - 整体布局：最大宽度 1400px，居中显示，全屏高度
    - 聊天窗口：圆角边框，用户消息渐变背景，助手消息白色卡片
    - 标签导航：白色背景，选中标签紫色高亮
    - 按钮样式：主按钮渐变紫色，停止按钮红色
    - 输入框：圆角边框，聚焦时紫色高亮
    - 左侧面板：浅灰色背景，右侧面板白色背景
    """
    logger.info("Starting Gradio application...")

    # 自定义 CSS 样式，优化界面美观度
    custom_css = """
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    html, body {
        height: 100% !important;
        width: 100% !important;
        overflow: auto !important;
    }
    .gradio-container {
        max-width: 100% !important;
        width: 100% !important;
        height: 100vh !important;
        margin: 0 !important;
        padding: 0 !important;
        display: flex;
        flex-direction: column;
        overflow: visible !important;
    }
    .gradio-container > .main {
        height: calc(100vh - 60px) !important;
        width: 100% !important;
        padding: 8px !important;
    }
    .gradio-container .gr-tab {
        padding: 0 !important;
    }
    .gradio-container .gr-row {
        gap: 8px !important;
    }
    .gradio-container .gr-col {
        padding: 0 !important;
    }
    .chatbot {
        border-radius: 12px;
        background: #fafafa;
        border: 1px solid #e0e0e0;
    }
    .chatbot .message {
        border-radius: 12px;
        padding: 4px 8px;
        margin-bottom: 2px;
        max-width: 80%;
        width: fit-content !important;
        min-width: 60px;
        font-size: 13px;
        line-height: 1.4;
        word-wrap: break-word;
        overflow-wrap: break-word;
    }
    .chatbot .user-message {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        margin-left: auto !important;
        border-bottom-right-radius: 4px;
        align-self: flex-end;
    }
    .chatbot .assistant-message {
        background: white;
        color: #333;
        margin-right: auto !important;
        border-bottom-left-radius: 4px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        border: 1px solid #f0f0f0;
        align-self: flex-start;
    }
    .gr-chatbot .bubble {
        max-width: 80% !important;
        width: fit-content !important;
        min-width: auto !important;
        padding: 4px 8px !important;
        margin-bottom: 2px !important;
        margin-top: 2px !important;
        border-radius: 12px !important;
        line-height: 1.4 !important;
    }
    .gr-chatbot .message-row {
        margin-bottom: 2px !important;
        padding-bottom: 0 !important;
    }
    .gr-chatbot .bubble.user {
        margin-left: auto !important;
        align-self: flex-end;
    }
    .gr-chatbot .bubble.assistant {
        margin-right: auto !important;
        align-self: flex-start;
    }
    .tab-nav {
        background: white;
        border-bottom: 2px solid #f0f0f0;
        padding: 0 20px;
    }
    .tab-nav button {
        font-weight: 600;
        color: #666;
        border-radius: 8px 8px 0 0;
        padding: 12px 32px;
        margin-right: 16px;
        font-size: 16px;
    }
    .tab-nav button.active {
        color: #667eea;
        border-bottom: 3px solid #667eea;
        background: #f8f9ff;
    }
    .button-primary {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        border: none !important;
        color: white !important;
        font-weight: 600 !important;
        border-radius: 8px !important;
    }
    .gr-textbox {
        border-radius: 12px !important;
        border: 1px solid #e0e0e0 !important;
        padding: 8px 16px !important;
        font-size: 15px !important;
    }
    .gr-textbox:focus {
        border-color: #667eea !important;
        box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.2) !important;
    }
    .gr-chatbot {
        padding: 8px !important;
        overflow-y: auto !important;
    }
    .button-stop {
        background: #ef4444 !important;
        border: none !important;
        color: white !important;
        border-radius: 8px !important;
    }
    .textbox {
        border-radius: 12px !important;
        border: 1px solid #e0e0e0 !important;
        transition: all 0.3s ease;
        padding: 10px 16px !important;
    }
    .textbox:focus {
        border-color: #667eea !important;
        box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1) !important;
        outline: none !important;
    }
    .dropdown {
        border-radius: 8px !important;
        border: 1px solid #e0e0e0 !important;
        width: 100% !important;
    }
    .column:first-child {
        background: #fafafa;
        border-right: 1px solid #e0e0e0;
        padding: 16px !important;
    }
    .column:first-child .markdown-text {
        font-size: 13px !important;
        color: #888 !important;
        margin-bottom: 8px !important;
    }
    .column:last-child {
        padding: 16px !important;
    }
    /* 暗色主题样式 */
    html.dark, html.dark body {
        background: #1a1a2e !important;
        color: #e0e0e0 !important;
    }
    html.dark .gradio-container {
        background: #1a1a2e !important;
    }
    html.dark .chatbot {
        background: #16213e !important;
        border-color: #30475e !important;
    }
    html.dark .chatbot .assistant-message {
        background: #16213e !important;
        color: #e0e0e0 !important;
        border-color: #30475e !important;
    }
    html.dark .chatbot .user-message {
        color: white !important;
    }
    html.dark .tab-nav {
        background: #16213e !important;
        border-bottom-color: #30475e !important;
    }
    html.dark .tab-nav button {
        color: #e0e0e0 !important;
    }
    html.dark .tab-nav button.active {
        background: #1a1a2e !important;
        color: #8b9dc3 !important;
    }
    html.dark .column:first-child {
        background: #16213e !important;
        border-right-color: #30475e !important;
    }
    html.dark .column:first-child .markdown-text {
        color: #a0a0a0 !important;
    }
    html.dark .gr-textbox,
    html.dark .textbox {
        background: #16213e !important;
        border-color: #30475e !important;
        color: #e0e0e0 !important;
    }
    html.dark .dropdown {
        background: #16213e !important;
        border-color: #30475e !important;
        color: #e0e0e0 !important;
    }
    html.dark .markdown-text {
        color: #e0e0e0 !important;
    }
    """

    def preload_components():
        """
        预加载所有组件，避免首次对话时的初始化延迟。
        
        在应用启动时执行以下预加载：
        1. 加载 LLM 模型实例（deepseek 和 zhipu）
        2. 初始化检索管道（RetrievalPipeline）
        3. 编译 LangGraph 工作流
        4. 建立数据库连接
        """
        import time
        
        start_time = time.time()
        logger.info("=" * 60)
        logger.info("Starting preload of components...")
        logger.info("=" * 60)
        
        # 1. 预加载 LLM 模型（分别加载，避免一个失败影响另一个）
        model_factory = ModelFactory()
        loaded_models = []
        for model_type in ["deepseek", "deepseek-vl", "zhipu", "zhipu-4v"]:
            try:
                model = model_factory.create_model(model_type)
                loaded_models.append(model_type)
                logger.info(f"✅ {model_type} model loaded")
            except Exception as e:
                logger.warning(f"⚠️  Failed to preload {model_type} model: {str(e)}")
        
        # 2. 预加载检索管道
        try:
            from src.rag.retrieval_pipeline import RetrievalPipeline
            pipeline = RetrievalPipeline()
            logger.info("✅ RetrievalPipeline initialized")
        except Exception as e:
            logger.warning(f"⚠️  Failed to preload RetrievalPipeline: {str(e)}")
        
        # 3. 预编译 LangGraph 工作流
        try:
            agent_graph.compile(force_recompile=True)
            logger.info("✅ AgentGraph compiled")
        except Exception as e:
            logger.warning(f"⚠️  Failed to compile AgentGraph: {str(e)}")
        
        # 4. 预建立数据库连接
        try:
            from src.database.supabase_client import SupabaseClient
            client = SupabaseClient()
            logger.info("✅ Database connection established")
        except Exception as e:
            logger.warning(f"⚠️  Failed to establish database connection: {str(e)}")
        
        # 5. 预加载 MCP 工具
        try:
            from src.mcp.mcp_client import MCPClient
            tools = MCPClient.get_all_available_functions()
            logger.info(f"✅ MCP tools loaded: {len(tools)} tools")
        except Exception as e:
            logger.warning(f"⚠️  Failed to load MCP tools: {str(e)}")
        
        elapsed_time = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"Preload completed in {elapsed_time:.2f} seconds")
        logger.info(f"Loaded: {loaded_models}")
        logger.info("=" * 60)

    # 预加载组件（在启动 Gradio 之前）
    preload_components()

    # 创建 Gradio Blocks 应用
    with gr.Blocks(title="私人助手") as demo:
        # 页面标题
        gr.Markdown("# 🤖 私人助手")
        gr.Markdown("基于 LLM 的智能对话助手，支持多模态输入和知识库检索")

        # 注册两个标签页
        create_chat_tab(demo)    # 私人助手聊天界面
        create_kb_tab(demo)      # 知识库管理界面

    demo.queue()

    server_port = int(os.environ.get("PORT", "7860"))
    server_name = os.environ.get("HOST", "0.0.0.0")

    demo.launch(
        server_name=server_name,
        server_port=server_port,
        share=False,
        debug=False,
        css=custom_css,
        show_error=True,
    )


if __name__ == "__main__":
    """
    当脚本直接运行时，调用 main() 函数启动应用。

    环境变量：
    - PORT: 服务端口（默认 7860）
    - HOST: 监听地址（默认 0.0.0.0）
    - HF_ENDPOINT: HuggingFace 镜像地址
    """
    main()
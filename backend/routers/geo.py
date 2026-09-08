"""地理坐标接口：批量把地点文本解析为经纬度（小程序地图 markers 用）。

复用 src/mcp 的 AmapMCP（POI 搜索优先、地理编码兜底），高德密钥只存在于
后端，不暴露到小程序代码；坐标解析结果同时写入 MCP 缓存，重复查询零成本。
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger

logger = setup_logger("geo_router")

router = APIRouter(prefix="/api/geo", tags=["geo"])

# 高德 MCP 注册名（src/mcp/amap_mcp.py）
_AMAP_TOOL = "AmapMCP"
_MAX_PARALLEL = 6


class PlaceItem(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    city: Optional[str] = None


class CoordsRequest(BaseModel):
    places: List[PlaceItem] = Field(..., max_length=60)


def _parse_location(location: str) -> Optional[Dict[str, float]]:
    """高德返回的 location 格式为 '经度,纬度'，解析失败返回 None。"""
    if not location:
        return None
    lng, _, lat = location.partition(",")
    try:
        return {"lng": float(lng), "lat": float(lat)}
    except (TypeError, ValueError):
        return None


def _resolve_one(item: PlaceItem) -> Dict[str, Any]:
    """解析单个地点：优先 POI 搜索（精确到景点/餐饮），失败回退地理编码。"""
    name = item.name.strip()
    city = (item.city or "").strip()

    # 1) POI 搜索优先（高德 /place/text）
    poi_params: Dict[str, Any] = {"keyword": name, "page_size": 1}
    if city:
        poi_params["city"] = city
    try:
        resp = MCPClient.dispatch(
            tool_name=_AMAP_TOOL,
            method_name="search_poi",
            parameters=poi_params,
            session_id=None,
        )
        data = (resp or {}).get("data") or {}
        pois = data.get("pois") or []
        if pois:
            loc = _parse_location(pois[0].get("location") or "")
            if loc:
                return {
                    "name": name,
                    "lng": loc["lng"],
                    "lat": loc["lat"],
                    "address": pois[0].get("address", "") or "",
                }
    except Exception as exc:
        logger.warning(f"POI search failed for {name}: {exc}")

    # 2) 地理编码兜底（/geocode/geo）
    geo_params: Dict[str, Any] = {"address": name}
    if city:
        geo_params["city"] = city
    try:
        resp = MCPClient.dispatch(
            tool_name=_AMAP_TOOL,
            method_name="geocode",
            parameters=geo_params,
            session_id=None,
        )
        data = (resp or {}).get("data") or {}
        geocodes = data.get("geocodes") or []
        if geocodes:
            loc = _parse_location(geocodes[0].get("location") or "")
            if loc:
                return {
                    "name": name,
                    "lng": loc["lng"],
                    "lat": loc["lat"],
                    "address": geocodes[0].get("formatted_address", "") or "",
                }
    except Exception as exc:
        logger.warning(f"Geocode failed for {name}: {exc}")

    return {"name": name, "lng": None, "lat": None}


@router.post("/coords")
async def batch_coords(req: CoordsRequest) -> Dict[str, Any]:
    """批量解析地点坐标（并行，最多 6 路；未解析到坐标的地点 lng/lat 为 None）。"""
    places = req.places
    if not places:
        return {"coords": [], "resolved": 0, "total": 0}

    sem = asyncio.Semaphore(_MAX_PARALLEL)

    async def wrapped(item: PlaceItem) -> Dict[str, Any]:
        async with sem:
            return await asyncio.to_thread(_resolve_one, item)

    coords = list(await asyncio.gather(*(wrapped(p) for p in places)))
    resolved = sum(1 for c in coords if c.get("lng") is not None)
    logger.info(f"Geo coords resolved {resolved}/{len(coords)}")
    return {"coords": coords, "resolved": resolved, "total": len(coords)}

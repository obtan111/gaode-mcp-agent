import requests
from typing import Optional, List, Dict, Any

from src.mcp.mcp_client import MCPClient
from src.utils.logger import setup_logger
from src.utils.retry import retry

logger = setup_logger("amap_mcp")


@MCPClient.register_tool("AmapMCP")
class AmapMCP(MCPClient):
    def __init__(self):
        super().__init__()
        self.api_key = self.config.AMAP_API_KEY
        self.base_url = "https://restapi.amap.com/v3"
        
        if not self.api_key:
            logger.warning("AMAP_API_KEY not configured, AmapMCP may not work properly")

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def get_weather(self, city: str, date: Optional[str] = None) -> dict:
        """
        获取城市天气预报
        
        获取指定城市的实时天气和未来天气预报。
        
        Args:
            city: 城市名称，如 "北京"、"上海"、"广州"。支持中国大部分城市。
            date: 查询日期，格式为 "YYYY-MM-DD"。如果不提供，则返回未来几天的预报。
        
        Returns:
            dict: 包含天气信息的字典，主要字段：
                - status: 接口状态（1表示成功）
                - count: 返回结果数量
                - info: 状态信息
                - forecasts: 天气预报列表，每个元素包含：
                    - city: 城市名称
                    - date: 日期
                    - week: 星期
                    - dayweather: 白天天气
                    - nightweather: 夜间天气
                    - daytemp: 白天温度
                    - nighttemp: 夜间温度
                    - daywind: 白天风向
                    - nightwind: 夜间风向
                    - daypower: 白天风力
                    - nightpower: 夜间风力
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        url = f"{self.base_url}/weather/weatherInfo"
        params = {
            "key": self.api_key,
            "city": city,
            "extensions": "all",
            "output": "JSON",
        }
        
        logger.info(f"get_weather called, city={city}, date={date}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                logger.error(f"Weather API error: {data.get('info', 'Unknown error')}")
                return {"error": data.get("info", "Failed to get weather")}
            
            result = {
                "status": int(data["status"]),
                "count": int(data["count"]),
                "info": data.get("info", ""),
                "forecasts": data.get("forecasts", []),
            }
            
            logger.info(f"get_weather succeeded, found {len(result['forecasts'])} forecasts")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Weather API request failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_poi(self, keyword: str, city: str, types: Optional[str] = None, page_size: int = 10) -> dict:
        """
        景点 POI 检索
        
        根据关键词搜索指定城市的 POI（兴趣点），支持景点、餐饮、酒店等多种类型。
        
        Args:
            keyword: 搜索关键词，如 "故宫"、"餐厅"、"酒店"
            city: 城市名称，如 "北京"、"上海"
            types: POI类型编码，多个类型用 "|" 分隔。常用类型：
                - 110000: 景点
                - 050000: 餐饮服务
                - 090000: 住宿服务
                - 080000: 购物服务
                如果不提供，则搜索全部类型。
            page_size: 返回结果数量，默认为10，最大为50。
        
        Returns:
            dict: 包含POI搜索结果的字典：
                - status: 接口状态（1表示成功）
                - count: 返回结果数量
                - pois: POI列表，每个元素包含：
                    - id: POI唯一标识
                    - name: POI名称
                    - type: POI类型
                    - address: 地址
                    - location: 经纬度（格式：经度,纬度）
                    - tel: 电话
                    - distance: 距离（如果有定位）
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        url = f"{self.base_url}/place/text"
        params = {
            "key": self.api_key,
            "keywords": keyword,
            "city": city,
            "types": types or "",
            "offset": min(page_size, 50),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        
        logger.info(f"search_poi called, keyword={keyword}, city={city}, types={types}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                logger.error(f"POI API error: {data.get('info', 'Unknown error')}")
                return {"error": data.get("info", "Failed to search POI")}
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "pois": data.get("pois", []),
            }
            
            logger.info(f"search_poi succeeded, found {result['count']} POIs")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"POI API request failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def get_route(self, start: str, end: str, city: str, type: str = "bus") -> dict:
        """
        获取地铁/公交路线规划
        
        获取从起点到终点的公共交通路线规划，支持公交、地铁、驾车等多种方式。
        
        Args:
            start: 起点地址或名称，如 "天安门"、"北京市朝阳区xxx"
            end: 终点地址或名称，如 "故宫"、"北京市东城区xxx"
            city: 城市名称，如 "北京"、"上海"
            type: 路线类型，可选值：
                - bus: 公交路线（默认）
                - subway: 地铁路线
                - drive: 驾车路线
                - walk: 步行路线
        
        Returns:
            dict: 包含路线规划结果的字典：
                - status: 接口状态（1表示成功）
                - info: 状态信息
                - routes: 路线列表，每个路线包含：
                    - distance: 距离（米）
                    - duration: 预计耗时（秒）
                    - transit_mode: 交通方式
                    - steps: 步骤详情列表
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        type_map = {
            "bus": "bus",
            "subway": "subway",
            "drive": "driving",
            "walk": "walking",
        }
        
        route_type = type_map.get(type, "bus")
        
        url = f"{self.base_url}/direction/{route_type}"
        params = {
            "key": self.api_key,
            "origin": start,
            "destination": end,
            "city": city,
            "output": "JSON",
        }
        
        logger.info(f"get_route called, start={start}, end={end}, city={city}, type={type}")
        
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                logger.error(f"Route API error: {data.get('info', 'Unknown error')}")
                return {"error": data.get("info", "Failed to get route")}
            
            result = {
                "status": int(data["status"]),
                "info": data.get("info", ""),
                "routes": data.get("route", {}).get("paths", []),
            }
            
            logger.info(f"get_route succeeded, found {len(result['routes'])} routes")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Route API request failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def geocode(self, address: str, city: Optional[str] = None) -> dict:
        """
        地理编码转换（地址转经纬度）
        
        将中文地址转换为经纬度坐标。
        
        Args:
            address: 详细地址，如 "北京市朝阳区建国路88号"
            city: 城市名称，用于缩小搜索范围，如 "北京"。如果不提供，则自动识别。
        
        Returns:
            dict: 包含地理编码结果的字典：
                - status: 接口状态（1表示成功）
                - count: 返回结果数量
                - geocodes: 地理编码列表，每个元素包含：
                    - formatted_address: 格式化地址
                    - province: 省份
                    - city: 城市
                    - district: 区县
                    - street: 街道
                    - number: 门牌号
                    - location: 经纬度（格式：经度,纬度）
                    - level: 匹配级别
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        url = f"{self.base_url}/geocode/geo"
        params = {
            "key": self.api_key,
            "address": address,
            "city": city or "",
            "output": "JSON",
        }
        
        logger.info(f"geocode called, address={address}, city={city}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                logger.error(f"Geocode API error: {data.get('info', 'Unknown error')}")
                return {"error": data.get("info", "Failed to geocode")}
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "geocodes": data.get("geocodes", []),
            }
            
            logger.info(f"geocode succeeded, found {result['count']} results")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Geocode API request failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_hotel(
        self,
        city: str,
        keyword: Optional[str] = None,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        price_range: Optional[str] = None,
        page_size: int = 10,
    ) -> dict:
        """
        搜索酒店/住宿。
        
        Args:
            city: 城市名称，如 "长沙"
            keyword: 关键词（酒店名、品牌等）
            check_in: 入住日期（格式：YYYY-MM-DD）
            check_out: 退房日期（格式：YYYY-MM-DD）
            price_range: 价格范围，如 "0-300"、"300-600"、"600+"
            page_size: 返回结果数量
        
        Returns:
            dict: 酒店搜索结果
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        params = {
            "key": self.api_key,
            "city": city,
            "types": "100101|100102|100103",  # 酒店/宾馆/酒店式公寓
            "offset": min(page_size, 50),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        
        if keyword:
            params["keywords"] = keyword
        
        url = f"{self.base_url}/place/text"
        
        logger.info(f"search_hotel called, city={city}, keyword={keyword}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                return {"error": data.get("info", "Failed to search hotels")}
            
            hotels = data.get("pois", [])
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "hotels": hotels,
                "search_params": {
                    "city": city,
                    "check_in": check_in,
                    "check_out": check_out,
                    "price_range": price_range,
                }
            }
            
            logger.info(f"search_hotel succeeded, found {result['count']} hotels")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Hotel search failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_food(
        self,
        city: str,
        keyword: Optional[str] = None,
        food_type: Optional[str] = None,
        page_size: int = 10,
    ) -> dict:
        """
        搜索美食/餐厅。
        
        Args:
            city: 城市名称，如 "长沙"
            keyword: 关键词（餐厅名、菜品等）
            food_type: 菜系类型，如 "湘菜"、"粤菜"、"火锅"
            page_size: 返回结果数量
        
        Returns:
            dict: 美食搜索结果
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        # 美食类型编码
        type_mapping = {
            "中餐": "050000",
            "湘菜": "050100",
            "粤菜": "050200",
            "川菜": "050300",
            "鲁菜": "050400",
            "淮扬菜": "050500",
            "西餐": "050700",
            "日料": "050800",
            "韩餐": "050900",
            "火锅": "050102",
            "小吃": "050103",
            "甜点": "050104",
        }
        
        params = {
            "key": self.api_key,
            "city": city,
            "types": "050000",  # 餐饮服务
            "offset": min(page_size, 50),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        
        if keyword:
            params["keywords"] = keyword
        elif food_type and food_type in type_mapping:
            params["types"] = type_mapping[food_type]
        
        url = f"{self.base_url}/place/text"
        
        logger.info(f"search_food called, city={city}, keyword={keyword}, food_type={food_type}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                return {"error": data.get("info", "Failed to search food")}
            
            foods = data.get("pois", [])
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "restaurants": foods,
                "search_params": {
                    "city": city,
                    "keyword": keyword,
                    "food_type": food_type,
                }
            }
            
            logger.info(f"search_food succeeded, found {result['count']} restaurants")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Food search failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_ticket(
        self,
        city: str,
        keyword: Optional[str] = None,
        ticket_type: Optional[str] = None,
        page_size: int = 10,
    ) -> dict:
        """
        搜索旅游景点/门票。
        
        Args:
            city: 城市名称，如 "长沙"
            keyword: 关键词（景点名等）
            ticket_type: 景点类型，如 "自然风景"、"历史古迹"、"主题乐园"
            page_size: 返回结果数量
        
        Returns:
            dict: 景点搜索结果
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        # 景点类型编码
        type_mapping = {
            "自然风景": "140100",
            "山岳": "140101",
            "湖泊": "140102",
            "瀑布": "140103",
            "森林": "140104",
            "草原": "140105",
            "沙滩": "140106",
            "历史古迹": "140200",
            "古城": "140201",
            "遗址": "140202",
            "陵墓": "140203",
            "寺庙": "140204",
            "教堂": "140205",
            "博物馆": "140300",
            "主题乐园": "140400",
            "动物园": "140500",
            "植物园": "140600",
            "游乐园": "140401",
            "公园": "140700",
        }
        
        params = {
            "key": self.api_key,
            "city": city,
            "types": "140000",  # 风景名胜
            "offset": min(page_size, 50),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        
        if keyword:
            params["keywords"] = keyword
        elif ticket_type and ticket_type in type_mapping:
            params["types"] = type_mapping[ticket_type]
        
        url = f"{self.base_url}/place/text"
        
        logger.info(f"search_ticket called, city={city}, keyword={keyword}, ticket_type={ticket_type}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                return {"error": data.get("info", "Failed to search tickets")}
            
            spots = data.get("pois", [])
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "spots": spots,
                "search_params": {
                    "city": city,
                    "keyword": keyword,
                    "ticket_type": ticket_type,
                }
            }
            
            logger.info(f"search_ticket succeeded, found {result['count']} spots")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Ticket search failed: {e}")
            raise

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0)
    def search_nearby(
        self,
        location: str,
        type: str,
        radius: int = 3000,
        page_size: int = 10,
    ) -> dict:
        """
        周边搜索（根据经纬度搜索附近 POI）。
        
        Args:
            location: 中心点经纬度（格式：经度,纬度），如 "116.481488,39.990464"
            type: POI 类型编码，如 "100101"（酒店）、"050100"（中餐）
            radius: 搜索半径（米），默认 3000
            page_size: 返回结果数量
        
        Returns:
            dict: 周边 POI 搜索结果
        """
        if not self.api_key:
            return {"error": "AMAP_API_KEY not configured"}
        
        params = {
            "key": self.api_key,
            "location": location,
            "types": type,
            "radius": radius,
            "offset": min(page_size, 50),
            "page": 1,
            "extensions": "all",
            "output": "JSON",
        }
        
        url = f"{self.base_url}/place/around"
        
        logger.info(f"search_nearby called, location={location}, type={type}, radius={radius}")
        
        try:
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get("status") != "1":
                return {"error": data.get("info", "Failed to search nearby")}
            
            pois = data.get("pois", [])
            
            result = {
                "status": int(data["status"]),
                "count": int(data.get("count", 0)),
                "pois": pois,
                "search_params": {
                    "location": location,
                    "type": type,
                    "radius": radius,
                }
            }
            
            logger.info(f"search_nearby succeeded, found {result['count']} POIs")
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Nearby search failed: {e}")
            raise

    def get_budget_estimate(
        self,
        days: int = 3,
        travelers: int = 1,
        budget_level: str = "medium",
        city: Optional[str] = None,
    ) -> dict:
        """
        估算旅游预算。
        
        Args:
            days: 旅游天数
            travelers: 出行人数
            budget_level: 预算等级（economy/medium/luxury）
            city: 目标城市（可选，用于获取当地消费水平）
        
        Returns:
            dict: 预算估算详情
        """
        # 不同预算等级的日均消费（单人）
        daily_costs = {
            "economy": {
                "accommodation": 150,
                "food": 100,
                "transport": 50,
                "tickets": 100,
                "misc": 50,
                "daily_total": 450,
            },
            "medium": {
                "accommodation": 400,
                "food": 250,
                "transport": 100,
                "tickets": 200,
                "misc": 150,
                "daily_total": 1100,
            },
            "luxury": {
                "accommodation": 1000,
                "food": 500,
                "transport": 200,
                "tickets": 400,
                "misc": 300,
                "daily_total": 2400,
            },
        }
        
        costs = daily_costs.get(budget_level, daily_costs["medium"])
        
        # 计算总费用
        accommodation_cost = int(costs["accommodation"] * (days - 1) * travelers)  # 住宿天数 = 总天数 - 1
        food_cost = int(costs["food"] * days * travelers)
        transport_cost = int(costs["transport"] * days * travelers)
        tickets_cost = int(costs["tickets"] * days * travelers * 0.8)  # 门票不是每天都有
        misc_cost = int(costs["misc"] * days * travelers)
        
        total_cost = accommodation_cost + food_cost + transport_cost + tickets_cost + misc_cost
        per_person_cost = int(total_cost / travelers) if travelers > 0 else total_cost
        
        result = {
            "budget_level": budget_level,
            "days": days,
            "travelers": travelers,
            "city": city,
            "daily_breakdown": {
                "accommodation": costs["accommodation"],
                "food": costs["food"],
                "transport": costs["transport"],
                "tickets": costs["tickets"],
                "misc": costs["misc"],
            },
            "total_breakdown": {
                "accommodation": accommodation_cost,
                "food": food_cost,
                "transport": transport_cost,
                "tickets": tickets_cost,
                "misc": misc_cost,
            },
            "total_cost": total_cost,
            "per_person_cost": per_person_cost,
            "accommodation_days": days - 1,
            "note": f"预算等级：{budget_level}，基于人均每日消费估算，实际费用可能因城市、季节等因素有所浮动。",
        }
        
        logger.info(f"get_budget_estimate: {days}天, {travelers}人, {budget_level}, 总计{total_cost}元")
        return result

    def export_itinerary(
        self,
        itinerary: Dict[str, Any],
        format: str = "markdown",
        output_dir: Optional[str] = None,
    ) -> dict:
        """
        导出行程计划为 Markdown 或 Excel 文件。

        Args:
            itinerary: 行程数据字典，包含 title, destination, days, budget, daily_itinerary 等字段
            format: 导出格式，可选 "markdown"、"excel" 或 "both"（默认 markdown）
            output_dir: 输出目录（可选，默认输出到项目 exports 目录）

        Returns:
            dict: 导出结果，包含 success 状态、生成文件路径和 Markdown 内容
        """
        from src.utils.itinerary_exporter import export_itinerary as _export

        logger.info(f"export_itinerary called, format={format}")

        result = _export(
            itinerary=itinerary,
            format=format,
            output_dir=output_dir,
        )

        return result
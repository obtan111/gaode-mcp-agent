import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from src.utils.logger import setup_logger

logger = setup_logger("itinerary_exporter")


def _ensure_output_dir(file_path: str) -> None:
    """确保输出文件的目录存在。"""
    dir_path = os.path.dirname(file_path)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)


def export_to_markdown(itinerary: Dict[str, Any], output_path: Optional[str] = None) -> str:
    """
    将行程数据导出为 Markdown 格式。

    Args:
        itinerary: 行程数据字典，格式参考 TRAVEL_PLAN_PROMPT
        output_path: 输出文件路径（可选），不提供则只返回字符串

    Returns:
        str: Markdown 格式的行程内容
    """
    lines = []

    title = itinerary.get("title", "旅行计划")
    destination = itinerary.get("destination", "")
    days = itinerary.get("days", "")
    budget = itinerary.get("budget", "")
    weather_summary = itinerary.get("weather_summary", "")

    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"> **目的地**: {destination} | **天数**: {days} | **预算**: {budget}")
    if weather_summary:
        lines.append(f"> **天气概览**: {weather_summary}")
    lines.append("")
    lines.append("---")
    lines.append("")

    daily_itinerary = itinerary.get("daily_itinerary", [])
    for day_plan in daily_itinerary:
        day = day_plan.get("day", "")
        date = day_plan.get("date", "")
        weather = day_plan.get("weather", "")

        lines.append(f"## 第{day}天 ({date})")
        if weather:
            lines.append(f"🌤️ 天气: {weather}")
        lines.append("")

        for period_key, period_label in [("morning", "上午"), ("afternoon", "下午"), ("evening", "晚上")]:
            period = day_plan.get(period_key, {})
            if not period:
                continue

            activity = period.get("activity", "")
            location = period.get("location", "")
            transport = period.get("transport", "")
            duration = period.get("duration", "")
            cost = period.get("cost", "")

            lines.append(f"### {period_label}: {activity}")
            lines.append("")
            lines.append(f"- **地点**: {location}")
            if transport:
                lines.append(f"- **交通**: {transport}")
            if duration:
                lines.append(f"- **时长**: {duration}")
            if cost:
                lines.append(f"- **费用**: {cost}")
            lines.append("")

    tips = itinerary.get("tips", [])
    if tips:
        lines.append("---")
        lines.append("")
        lines.append("## 💡 旅行小贴士")
        lines.append("")
        for i, tip in enumerate(tips, 1):
            lines.append(f"{i}. {tip}")
        lines.append("")

    total_cost = itinerary.get("total_cost")
    if total_cost:
        lines.append("---")
        lines.append("")
        lines.append(f"💰 **预估总费用**: ¥{total_cost}")
        lines.append("")

    content = "\n".join(lines)

    if output_path:
        _ensure_output_dir(output_path)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Markdown itinerary exported to: {output_path}")

    return content


def export_to_excel(itinerary: Dict[str, Any], output_path: str) -> str:
    """
    将行程数据导出为 Excel 格式。

    Args:
        itinerary: 行程数据字典
        output_path: 输出 Excel 文件路径

    Returns:
        str: 输出文件路径
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
        from openpyxl.utils import get_column_letter
    except ImportError:
        raise ImportError("openpyxl is required for Excel export. Install with: pip install openpyxl")

    wb = Workbook()
    ws = wb.active
    ws.title = "行程概览"

    header_font = Font(bold=True, size=14, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    cell_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )

    title = itinerary.get("title", "旅行计划")
    ws.merge_cells("A1:F1")
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=18)
    ws["A1"].alignment = Alignment(horizontal="center")

    info_data = [
        ["目的地", itinerary.get("destination", "")],
        ["天数", itinerary.get("days", "")],
        ["预算等级", itinerary.get("budget", "")],
        ["天气概览", itinerary.get("weather_summary", "")],
        ["预估总费用", f"¥{itinerary.get('total_cost', 'N/A')}"],
    ]

    for i, (key, value) in enumerate(info_data, start=3):
        ws.cell(row=i, column=1, value=key).font = Font(bold=True)
        ws.cell(row=i, column=2, value=value)
        ws.cell(row=i, column=1).border = thin_border
        ws.cell(row=i, column=2).border = thin_border

    daily_itinerary = itinerary.get("daily_itinerary", [])

    if daily_itinerary:
        ws_day = wb.create_sheet(title="每日行程")

        headers = ["天数", "日期", "时段", "活动", "地点", "交通", "时长", "费用"]
        for col, header in enumerate(headers, 1):
            cell = ws_day.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border

        row = 2

        for day_plan in daily_itinerary:
            day = day_plan.get("day", "")
            date = day_plan.get("date", "")
            weather = day_plan.get("weather", "")

            for period_key, period_label in [("morning", "上午"), ("afternoon", "下午"), ("evening", "晚上")]:
                period = day_plan.get(period_key, {})
                if not period:
                    continue

                ws_day.cell(row=row, column=1, value=f"第{day}天").border = thin_border
                ws_day.cell(row=row, column=2, value=date).border = thin_border
                ws_day.cell(row=row, column=3, value=period_label).border = thin_border
                ws_day.cell(row=row, column=4, value=period.get("activity", "")).border = thin_border
                ws_day.cell(row=row, column=5, value=period.get("location", "")).border = thin_border
                ws_day.cell(row=row, column=6, value=period.get("transport", "")).border = thin_border
                ws_day.cell(row=row, column=7, value=period.get("duration", "")).border = thin_border
                ws_day.cell(row=row, column=8, value=period.get("cost", "")).border = thin_border

                for col in range(1, 9):
                    ws_day.cell(row=row, column=col).alignment = cell_alignment

                row += 1

        for col in range(1, 9):
            ws_day.column_dimensions[get_column_letter(col)].width = 18

    tips = itinerary.get("tips", [])
    if tips:
        ws_tips = wb.create_sheet(title="小贴士")
        ws_tips.cell(row=1, column=1, value="序号").font = header_font
        ws_tips.cell(row=1, column=2, value="内容").font = header_font
        ws_tips.cell(row=1, column=1).fill = header_fill
        ws_tips.cell(row=1, column=2).fill = header_fill
        ws_tips.cell(row=1, column=1).alignment = header_alignment
        ws_tips.cell(row=1, column=2).alignment = header_alignment

        for i, tip in enumerate(tips, 1):
            ws_tips.cell(row=i + 1, column=1, value=i).border = thin_border
            ws_tips.cell(row=i + 1, column=2, value=tip).border = thin_border
            ws_tips.cell(row=i + 1, column=2).alignment = cell_alignment

        ws_tips.column_dimensions["A"].width = 8
        ws_tips.column_dimensions["B"].width = 60

    ws.column_dimensions["A"].width = 15
    ws.column_dimensions["B"].width = 30

    _ensure_output_dir(output_path)
    wb.save(output_path)
    logger.info(f"Excel itinerary exported to: {output_path}")

    return output_path


def export_itinerary(
    itinerary: Dict[str, Any],
    format: str = "markdown",
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    统一的行程导出接口。

    Args:
        itinerary: 行程数据字典
        format: 导出格式，支持 "markdown"、"excel"、"both"
        output_dir: 输出目录，不提供则使用默认目录

    Returns:
        dict: 导出结果，包含文件路径和内容
    """
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "exports")

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = itinerary.get("title", "travel_plan").replace(" ", "_")
    base_name = f"{title}_{timestamp}"

    result = {
        "success": True,
        "format": format,
        "files": {},
    }

    try:
        if format in ("markdown", "md"):
            md_path = os.path.join(output_dir, f"{base_name}.md")
            md_content = export_to_markdown(itinerary, md_path)
            result["files"]["markdown"] = md_path
            result["markdown_content"] = md_content

        elif format in ("excel", "xlsx"):
            xlsx_path = os.path.join(output_dir, f"{base_name}.xlsx")
            export_to_excel(itinerary, xlsx_path)
            result["files"]["excel"] = xlsx_path

        elif format == "both":
            md_path = os.path.join(output_dir, f"{base_name}.md")
            md_content = export_to_markdown(itinerary, md_path)
            result["files"]["markdown"] = md_path
            result["markdown_content"] = md_content

            xlsx_path = os.path.join(output_dir, f"{base_name}.xlsx")
            export_to_excel(itinerary, xlsx_path)
            result["files"]["excel"] = xlsx_path

        else:
            result["success"] = False
            result["error"] = f"Unsupported format: {format}. Use 'markdown', 'excel', or 'both'."

    except ImportError as e:
        result["success"] = False
        result["error"] = str(e)
    except Exception as e:
        result["success"] = False
        result["error"] = f"Export failed: {str(e)}"
        logger.error(f"Itinerary export failed: {str(e)}", exc_info=True)

    return result


def parse_itinerary_from_text(text: str) -> Dict[str, Any]:
    """
    从文本中解析行程数据（支持 JSON 格式或自然语言描述）。

    Args:
        text: 行程文本，优先为 JSON 格式

    Returns:
        dict: 解析后的行程数据
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    return {
        "title": "旅行计划",
        "destination": "",
        "days": "",
        "budget": "",
        "weather_summary": "",
        "daily_itinerary": [],
        "tips": [],
    }

"""Dedicated Project Excel Service for Construction CRM.

Strict Rule: Only projects have Excels.
Each project has its own Excel workbook pre-populated with required fields
(standard columns + dynamic custom fields from project_field_definitions).
Supports:
1. Generating styled .xlsx binary workbooks.
2. Structured JSON payload for in-browser real-time interactive spreadsheet grid.
3. Ingesting spreadsheet row edits/inserts with schema validation and read-back verification.
"""
from datetime import date, datetime
import io
import json
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from services.database import execute_query, get_db_connection


# Core columns per record type
CORE_FIELDS_BY_TYPE = {
    "daily_log": [
        {"name": "record_date", "title": "Date", "type": "date", "required": True},
        {"name": "title", "title": "Log Title", "type": "text", "required": True},
        {"name": "description", "title": "Notes / Summary", "type": "text", "required": False},
    ],
    "expense": [
        {"name": "record_date", "title": "Date", "type": "date", "required": True},
        {"name": "title", "title": "Expense Title", "type": "text", "required": True},
        {"name": "amount", "title": "Amount", "type": "numeric", "required": True},
        {"name": "unit", "title": "Currency / Unit", "type": "text", "required": False, "default": "INR"},
        {"name": "description", "title": "Description", "type": "text", "required": False},
    ],
    "equipment_log": [
        {"name": "record_date", "title": "Date", "type": "date", "required": True},
        {"name": "title", "title": "Log Title", "type": "text", "required": True},
        {"name": "description", "title": "Operational Notes", "type": "text", "required": False},
    ],
}


def get_project_fields(project_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """Retrieve all fields (core + custom from project_field_definitions) by record_type."""
    custom_rows = execute_query(
        """
        SELECT record_type, field_name, field_type, required, default_value, validation_rules
        FROM public.project_field_definitions
        WHERE project_id = %s
        ORDER BY record_type, field_name
        """,
        (project_id,),
    )

    fields_by_type: Dict[str, List[Dict[str, Any]]] = {}
    for rtype in ("daily_log", "expense", "equipment_log"):
        fields_by_type[rtype] = [dict(f) for f in CORE_FIELDS_BY_TYPE[rtype]]

    for crow in custom_rows:
        rtype = crow["record_type"]
        if rtype not in fields_by_type:
            fields_by_type[rtype] = []
        # Add custom field
        fields_by_type[rtype].append({
            "name": crow["field_name"],
            "title": crow["field_name"].replace("_", " ").title(),
            "type": crow["field_type"],
            "required": bool(crow.get("required")),
            "default": crow.get("default_value"),
            "is_custom": True,
        })

    return fields_by_type


def get_project_spreadsheet_data(project_id: str) -> Dict[str, Any]:
    """Return complete schema and rows for in-browser Excel spreadsheet editor."""
    proj_rows = execute_query(
        "SELECT id, project_name, project_code, location, status, created_at FROM public.projects WHERE id = %s",
        (project_id,),
    )
    if not proj_rows:
        raise ValueError(f"Project {project_id} not found")
    project = proj_rows[0]

    fields_by_type = get_project_fields(project_id)

    records = execute_query(
        """
        SELECT id, project_id, record_type, record_date, title, description, amount, unit, data, created_at, updated_at
        FROM public.project_records
        WHERE project_id = %s
        ORDER BY record_date DESC, created_at DESC
        """,
        (project_id,),
    )

    sheets_data: Dict[str, Any] = {}
    for rtype, sheet_name in (
        ("daily_log", "Daily Logs"),
        ("expense", "Expenses"),
        ("equipment_log", "Equipment Logs"),
    ):
        cols = fields_by_type.get(rtype, [])
        type_records = [r for r in records if r["record_type"] == rtype]
        
        rows = []
        for r in type_records:
            row_dict = {
                "id": str(r["id"]),
                "record_type": rtype,
                "record_date": r["record_date"].isoformat() if isinstance(r["record_date"], (date, datetime)) else str(r["record_date"]),
                "title": r.get("title") or "",
                "description": r.get("description") or "",
                "amount": float(r["amount"]) if r.get("amount") is not None else None,
                "unit": r.get("unit") or "",
            }
            # Unpack custom data
            custom_data = r.get("data") or {}
            for col in cols:
                cname = col["name"]
                if col.get("is_custom"):
                    row_dict[cname] = custom_data.get(cname, "")
            rows.append(row_dict)

        sheets_data[rtype] = {
            "sheet_name": sheet_name,
            "columns": cols,
            "rows": rows,
        }

    return {
        "project": {
            "id": str(project["id"]),
            "project_name": project["project_name"],
            "project_code": project["project_code"],
            "location": project.get("location"),
            "status": project.get("status"),
        },
        "sheets": sheets_data,
        "total_records": len(records),
    }


def generate_project_excel(project_id: str) -> bytes:
    """Generate a styled .xlsx binary workbook for the project."""
    data = get_project_spreadsheet_data(project_id)
    project = data["project"]

    wb = openpyxl.Workbook()
    # Remove default sheet
    default_sheet = wb.active
    wb.remove(default_sheet)

    # Styles
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")  # Slate 800
    header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Segoe UI", size=10, color="0F172A")
    border_thin = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(top=border_thin, left=border_thin, right=border_thin, bottom=border_thin)

    sheet_configs = [
        ("daily_log", "Daily Logs"),
        ("expense", "Expenses"),
        ("equipment_log", "Equipment Logs"),
    ]

    for rtype, sheet_title in sheet_configs:
        sheet_info = data["sheets"].get(rtype, {})
        columns = sheet_info.get("columns", [])
        rows = sheet_info.get("rows", [])

        ws = wb.create_sheet(title=sheet_title)
        ws.views.sheetView[0].showGridLines = True

        # Row 1: Title Banner
        ws.merge_cells("A1:G1")
        title_cell = ws["A1"]
        title_cell.value = f"{project['project_name']} ({project['project_code']}) — {sheet_title}"
        title_cell.font = Font(name="Segoe UI", size=13, bold=True, color="1E3A8A")
        ws.row_dimensions[1].height = 26

        # Row 3: Table Headers
        header_row_idx = 3
        ws.row_dimensions[header_row_idx].height = 24
        
        headers = ["Record ID"] + [c["title"] for c in columns]
        col_names = ["id"] + [c["name"] for c in columns]

        for col_idx, header in enumerate(headers, 1):
            cell = ws.cell(row=header_row_idx, column=col_idx, value=header)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = cell_border

        # Populate Data Rows
        current_row = header_row_idx + 1
        for r in rows:
            ws.row_dimensions[current_row].height = 20
            for col_idx, key in enumerate(col_names, 1):
                val = r.get(key)
                cell = ws.cell(row=current_row, column=col_idx, value=val)
                cell.font = data_font
                cell.border = cell_border
                cell.alignment = Alignment(vertical="center")

                # Format amounts and dates
                if key == "amount" and isinstance(val, (int, float)):
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif key == "record_date":
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                elif key == "id":
                    cell.alignment = Alignment(horizontal="center", vertical="center")
                    cell.font = Font(name="Segoe UI", size=8, color="64748B")

            current_row += 1

        # Auto-adjust column widths
        for col_idx in range(1, len(headers) + 1):
            col_letter = get_column_letter(col_idx)
            max_len = max(
                len(str(ws.cell(row=r, column=col_idx).value or ""))
                for r in range(header_row_idx, current_row)
            )
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def sync_excel_row_to_supabase(
    project_id: str,
    row_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Upsert a row from the Excel spreadsheet into public.project_records with read-back verification."""
    # 1. Validate project existence
    proj_rows = execute_query("SELECT id FROM public.projects WHERE id = %s", (project_id,))
    if not proj_rows:
        return {"success": False, "error": f"Project {project_id} not found"}

    record_id = row_data.get("id") or row_data.get("record_id")
    if record_id:
        try:
            import uuid
            uuid.UUID(str(record_id))
        except (ValueError, AttributeError):
            record_id = None
    record_type = row_data.get("record_type")
    if record_type not in ("daily_log", "expense", "equipment_log"):
        return {"success": False, "error": f"Invalid record_type: '{record_type}'"}

    record_date = row_data.get("record_date")
    if not record_date:
        record_date = date.today().isoformat()
    elif isinstance(record_date, (date, datetime)):
        record_date = record_date.isoformat()[:10]

    title = str(row_data.get("title") or "").strip()
    description = str(row_data.get("description") or "").strip() or None
    
    amount = row_data.get("amount")
    if amount is not None and str(amount).strip() != "":
        try:
            amount = float(amount)
        except ValueError:
            return {"success": False, "error": f"Amount '{amount}' must be a valid number"}
    else:
        amount = None

    unit = row_data.get("unit") or ("INR" if record_type == "expense" else None)

    # 2. Extract and validate custom fields
    fields_by_type = get_project_fields(project_id)
    known_cols = fields_by_type.get(record_type, [])
    
    custom_data: Dict[str, Any] = {}
    for col in known_cols:
        cname = col["name"]
        if col.get("is_custom"):
            val = row_data.get(cname)
            if col.get("required") and (val is None or str(val).strip() == ""):
                return {"success": False, "error": f"Required field '{col['title']}' is missing"}
            if val is not None:
                custom_data[cname] = val

    # 3. Write to Supabase with read-back verification envelope
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if record_id:
                # Update existing row
                cur.execute(
                    """
                    UPDATE public.project_records
                    SET record_date = %s,
                        title = %s,
                        description = %s,
                        amount = %s,
                        unit = %s,
                        data = COALESCE(data, '{}'::jsonb) || %s::jsonb,
                        updated_at = now()
                    WHERE id = %s AND project_id = %s
                    RETURNING id, project_id, record_type, record_date, title, description, amount, unit, data
                    """,
                    (
                        record_date,
                        title,
                        description,
                        amount,
                        unit,
                        json.dumps(custom_data),
                        record_id,
                        project_id,
                    ),
                )
            else:
                # Insert new row
                cur.execute(
                    """
                    INSERT INTO public.project_records
                        (project_id, record_type, record_date, title, description, amount, unit, data)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id, project_id, record_type, record_date, title, description, amount, unit, data
                    """,
                    (
                        project_id,
                        record_type,
                        record_date,
                        title,
                        description,
                        amount,
                        unit,
                        json.dumps(custom_data),
                    ),
                )

            verified = cur.fetchone()
            if not verified:
                return {"success": False, "error": "Read-back verification failed: record was not saved."}

            verified_dict = dict(verified)
            if isinstance(verified_dict.get("record_date"), (date, datetime)):
                verified_dict["record_date"] = verified_dict["record_date"].isoformat()
            if verified_dict.get("amount") is not None:
                verified_dict["amount"] = float(verified_dict["amount"])

            return {
                "success": True,
                "record": verified_dict,
                "message": "Row synchronized successfully with database",
            }

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
import re
from typing import Any, Dict, List, Optional, Tuple
import uuid

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


def create_new_project(
    project_name: str,
    project_code: Optional[str] = None,
    location: Optional[str] = None,
    status: str = "active",
) -> Dict[str, Any]:
    """Create a new project in public.projects and initialize default custom field definitions."""
    name = str(project_name or "").strip()
    if not name:
        raise ValueError("Project name is required")

    code = str(project_code or "").strip()
    if not code:
        words = re.findall(r"[A-Za-z0-9]+", name)
        code_prefix = "".join(w[0].upper() for w in words)[:4] or "PROJ"
        code = f"{code_prefix}-01"

    loc = str(location or "").strip() or None
    stat = str(status or "active").strip().lower()
    if stat not in ("active", "on_hold", "completed", "archived"):
        stat = "active"

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.projects (project_name, project_code, location, status)
                VALUES (%s, %s, %s, %s)
                RETURNING id, project_name, project_code, location, status, created_at
                """,
                (name, code, loc, stat),
            )
            proj = dict(cur.fetchone())
            proj_id = str(proj["id"])

            default_fields = [
                ("expense", "category", "text"),
                ("expense", "payment_mode", "text"),
                ("daily_log", "weather", "text"),
                ("daily_log", "workers_count", "integer"),
                ("equipment_log", "equipment_name", "text"),
                ("equipment_log", "hours_operated", "numeric"),
            ]
            for rtype, fname, ftype in default_fields:
                cur.execute(
                    """
                    INSERT INTO public.project_field_definitions
                        (project_id, record_type, field_name, field_type, required)
                    VALUES (%s, %s, %s, %s, false)
                    ON CONFLICT (project_id, record_type, field_name) DO NOTHING
                    """,
                    (proj_id, rtype, fname, ftype),
                )

    if isinstance(proj.get("created_at"), (date, datetime)):
        proj["created_at"] = proj["created_at"].isoformat()
    proj["id"] = proj_id

    return {
        "success": True,
        "project": proj,
        "message": f"Project '{name}' [{code}] created successfully",
    }


def import_project_excel(
    file_bytes: bytes,
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    project_code: Optional[str] = None,
    location: Optional[str] = None,
) -> Dict[str, Any]:
    """Import an Excel workbook, updating project metadata, registering new fields, and reconciling records.

    Rules:
    1. If project_id is None, deduce project name and code from sheet banner or params and create project.
    2. Any custom fields in the Excel sheets not yet in project_field_definitions will be created automatically.
    3. Reconcile project_records:
       - Update matching existing IDs.
       - Insert new rows (blank / NEW id).
       - Delete records present in Supabase whose IDs are missing from the uploaded sheet.
    """
    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)

    # 1. Project Resolution / Creation / Update
    banner_text = ""
    for sname in wb.sheetnames:
        first_cell = wb[sname]["A1"].value
        if first_cell and isinstance(first_cell, str) and ("—" in first_cell or "-" in first_cell):
            banner_text = first_cell
            break

    parsed_name = project_name
    parsed_code = project_code
    if banner_text:
        m = re.match(r"^(.*?)(?:\s*\((.*?)\))?\s*[—\-]", banner_text)
        if m:
            if not parsed_name:
                parsed_name = m.group(1).strip()
            if not parsed_code and m.group(2):
                parsed_code = m.group(2).strip()

    if not project_id:
        p_name = parsed_name or "Imported Project"
        p_code = parsed_code or "IMP-01"
        res = create_new_project(p_name, p_code, location=location)
        project_id = res["project"]["id"]
        proj_info = res["project"]
    else:
        proj_rows = execute_query(
            "SELECT id, project_name, project_code, location, status FROM public.projects WHERE id = %s",
            (project_id,),
        )
        if not proj_rows:
            raise ValueError(f"Project {project_id} not found")
        proj_info = dict(proj_rows[0])

        update_fields = {}
        if parsed_name and parsed_name != proj_info.get("project_name"):
            update_fields["project_name"] = parsed_name
        if parsed_code and parsed_code != proj_info.get("project_code"):
            update_fields["project_code"] = parsed_code
        if location and location != proj_info.get("location"):
            update_fields["location"] = location

        if update_fields:
            set_clauses = [f"{k} = %s" for k in update_fields.keys()]
            vals = list(update_fields.values()) + [project_id]
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        f"UPDATE public.projects SET {', '.join(set_clauses)} WHERE id = %s RETURNING id, project_name, project_code, location, status",
                        vals,
                    )
                    proj_info = dict(cur.fetchone())

    proj_id = str(project_id)

    sheet_name_map = {
        "daily log": "daily_log",
        "daily logs": "daily_log",
        "dailylog": "daily_log",
        "dailylogs": "daily_log",
        "expense": "expense",
        "expenses": "expense",
        "equipment log": "equipment_log",
        "equipment logs": "equipment_log",
        "equipmentlog": "equipment_log",
        "equipmentlogs": "equipment_log",
        "equipment": "equipment_log",
    }

    created_records = 0
    updated_records = 0
    deleted_records = 0
    new_fields_created: List[Dict[str, str]] = []

    for sheetname in wb.sheetnames:
        clean_sname = sheetname.strip().lower()
        record_type = sheet_name_map.get(clean_sname)
        if not record_type:
            for k, v in sheet_name_map.items():
                if k in clean_sname:
                    record_type = v
                    break
        if not record_type:
            continue

        ws = wb[sheetname]

        header_row_idx = None
        header_cols: Dict[int, str] = {}
        for r_idx in range(1, min(ws.max_row + 1, 10)):
            row_vals = [str(ws.cell(row=r_idx, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
            row_vals_lower = [v.lower() for v in row_vals]
            if any(term in row_vals_lower for term in ("record id", "date", "log title", "expense title", "title", "amount")):
                header_row_idx = r_idx
                for c_idx in range(1, ws.max_column + 1):
                    val = ws.cell(row=r_idx, column=c_idx).value
                    if val is not None and str(val).strip():
                        header_cols[c_idx] = str(val).strip()
                break

        if not header_row_idx or not header_cols:
            continue

        col_to_field: Dict[int, Dict[str, Any]] = {}
        standard_header_map = {
            "record id": ("id", "uuid"),
            "id": ("id", "uuid"),
            "date": ("record_date", "date"),
            "record date": ("record_date", "date"),
            "log title": ("title", "text"),
            "expense title": ("title", "text"),
            "title": ("title", "text"),
            "description": ("description", "text"),
            "notes": ("description", "text"),
            "notes / summary": ("description", "text"),
            "operational notes": ("description", "text"),
            "amount": ("amount", "numeric"),
            "currency / unit": ("unit", "text"),
            "unit": ("unit", "text"),
            "currency": ("unit", "text"),
        }

        existing_defs = execute_query(
            "SELECT field_name, field_type FROM public.project_field_definitions WHERE project_id = %s AND record_type = %s",
            (proj_id, record_type),
        )
        existing_fields_map = {f["field_name"]: f["field_type"] for f in existing_defs}

        for c_idx, raw_title in header_cols.items():
            clean_title = re.sub(r"\s*\*+$", "", raw_title).strip()
            clean_title = re.sub(r"\[.*?\]", "", clean_title).strip()
            clean_lower = clean_title.lower()

            if clean_lower in standard_header_map:
                fname, ftype = standard_header_map[clean_lower]
                col_to_field[c_idx] = {"name": fname, "type": ftype, "is_custom": False, "title": clean_title}
            else:
                norm_name = re.sub(r"[^a-z0-9]+", "_", clean_lower).strip("_")
                if not norm_name:
                    norm_name = f"custom_col_{c_idx}"

                norm_type = "numeric" if any(w in norm_name for w in ("count", "amount", "density", "hours", "rate", "cost", "qty", "quantity")) else "text"

                if norm_name not in existing_fields_map:
                    with get_db_connection() as conn:
                        with conn.cursor() as cur:
                            cur.execute(
                                """
                                INSERT INTO public.project_field_definitions
                                    (project_id, record_type, field_name, field_type, required)
                                VALUES (%s, %s, %s, %s, false)
                                ON CONFLICT (project_id, record_type, field_name) DO NOTHING
                                """,
                                (proj_id, record_type, norm_name, norm_type),
                            )
                    existing_fields_map[norm_name] = norm_type
                    new_fields_created.append({"record_type": record_type, "field_name": norm_name, "field_type": norm_type})

                col_to_field[c_idx] = {"name": norm_name, "type": existing_fields_map.get(norm_name, norm_type), "is_custom": True, "title": clean_title}

        sheet_uploaded_ids: set[str] = set()

        with get_db_connection() as conn:
            with conn.cursor() as cur:
                for r_idx in range(header_row_idx + 1, ws.max_row + 1):
                    row_cells = [ws.cell(row=r_idx, column=c).value for c in header_cols.keys()]
                    if all(v is None or str(v).strip() == "" for v in row_cells):
                        continue

                    row_record: Dict[str, Any] = {}
                    row_custom_data: Dict[str, Any] = {}
                    row_id: Optional[str] = None

                    for c_idx, meta in col_to_field.items():
                        cell_val = ws.cell(row=r_idx, column=c_idx).value
                        fname = meta["name"]
                        ftype = meta["type"]

                        if fname == "id":
                            if cell_val:
                                try:
                                    s_val = str(cell_val).strip()
                                    uuid.UUID(s_val)
                                    row_id = s_val
                                except (ValueError, AttributeError):
                                    row_id = None
                        elif meta["is_custom"]:
                            if cell_val is not None:
                                if ftype in ("numeric", "integer"):
                                    try:
                                        row_custom_data[fname] = float(cell_val)
                                    except (ValueError, TypeError):
                                        row_custom_data[fname] = str(cell_val)
                                else:
                                    row_custom_data[fname] = str(cell_val).strip()
                        else:
                            if fname == "record_date":
                                if isinstance(cell_val, (date, datetime)):
                                    row_record["record_date"] = cell_val.isoformat()[:10]
                                elif cell_val:
                                    row_record["record_date"] = str(cell_val).strip()[:10]
                                else:
                                    row_record["record_date"] = date.today().isoformat()
                            elif fname == "amount":
                                if cell_val is not None and str(cell_val).strip() != "":
                                    try:
                                        row_record["amount"] = float(cell_val)
                                    except (ValueError, TypeError):
                                        row_record["amount"] = None
                                else:
                                    row_record["amount"] = None
                            else:
                                row_record[fname] = str(cell_val).strip() if cell_val is not None else None

                    rec_date = row_record.get("record_date") or date.today().isoformat()
                    title = row_record.get("title") or "Log Entry"
                    desc = row_record.get("description")
                    amt = row_record.get("amount")
                    unit = row_record.get("unit") or ("INR" if record_type == "expense" else None)

                    if row_id:
                        cur.execute(
                            "SELECT id FROM public.project_records WHERE id = %s AND project_id = %s",
                            (row_id, proj_id),
                        )
                        exists = cur.fetchone()
                        if exists:
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
                                RETURNING id
                                """,
                                (rec_date, title, desc, amt, unit, json.dumps(row_custom_data), row_id, proj_id),
                            )
                            sheet_uploaded_ids.add(row_id)
                            updated_records += 1
                            continue

                    cur.execute(
                        """
                        INSERT INTO public.project_records
                            (project_id, record_type, record_date, title, description, amount, unit, data)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        RETURNING id
                        """,
                        (proj_id, record_type, rec_date, title, desc, amt, unit, json.dumps(row_custom_data)),
                    )
                    inserted = cur.fetchone()
                    if inserted:
                        sheet_uploaded_ids.add(str(inserted["id"]))
                        created_records += 1

                # Reconcile / Delete omitted records
                cur.execute(
                    "SELECT id FROM public.project_records WHERE project_id = %s AND record_type = %s",
                    (proj_id, record_type),
                )
                existing_db_records = cur.fetchall()
                for dbrec in existing_db_records:
                    rec_id = str(dbrec["id"])
                    if rec_id not in sheet_uploaded_ids:
                        cur.execute(
                            "DELETE FROM public.project_records WHERE id = %s AND project_id = %s",
                            (rec_id, proj_id),
                        )
                        deleted_records += 1

    reconciliation = {
        "inserted": created_records,
        "updated": updated_records,
        "deleted": deleted_records,
        "custom_fields_added": len(new_fields_created),
    }

    return {
        "success": True,
        "project_id": proj_id,
        "project": proj_info,
        "reconciliation": reconciliation,
        "created_records": created_records,
        "updated_records": updated_records,
        "deleted_records": deleted_records,
        "new_fields_created": new_fields_created,
        "message": f"Workbook imported successfully for {proj_info.get('project_name')}: {created_records} added, {updated_records} updated, {deleted_records} deleted, {len(new_fields_created)} custom fields registered.",
    }


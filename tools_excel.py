import os
from datetime import datetime
import openpyxl
from openpyxl.styles import Font, PatternFill

ANALYTICS_CATALOG = {
    "sales_revenue_analytics": "Sales & Revenue Endurance Analytics",
    "student_fees_analytics": "Student Fees & Collection Analytics",
    "inventory_stock_analytics": "Inventory & Stock Turnover Analytics",
    "employee_payroll_analytics": "Employee Payroll & Attendance Analytics",
}


def create_fees_register(filename="Fees_Register.xlsx"):
    abs_path = os.path.abspath(filename)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Fees_Register"
    headers = ["Student ID", "Student Name", "Program", "Total Fees", "Paid", "Balance", "Status"]
    ws.append(headers)
    header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    for cell in ws[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill

    rows = [
        ["STU-001", "Amina Hassan", "BSc Computer Science", 120000, 120000, "=D2-E2", "Cleared"],
        ["STU-002", "Brian Kamau", "BSc Software Eng", 120000, 85000, "=D3-E3", "Partial"],
        ["STU-003", "Faith Wanjiku", "BCom Finance", 95000, 95000, "=D4-E4", "Cleared"],
    ]
    for r in rows:
        ws.append(r)
    wb.save(abs_path)
    return f"Created Excel workbook '{abs_path}'."


def run_analytics_cycle(analytics_key="sales_revenue_analytics", cycle_num=1, filename=None):
    target_file = filename or f"{analytics_key}.xlsx"
    abs_path = os.path.abspath(target_file)
    os.makedirs(os.path.dirname(abs_path) or ".", exist_ok=True)

    if os.path.exists(abs_path):
        wb = openpyxl.load_workbook(abs_path)
        ws = wb.active
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Analytics_Log"
        ws.append(["Cycle", "Timestamp", "Analytics Module", "Metric A", "Metric B", "Variance"])

    row_idx = ws.max_row + 1
    metric_a = 1000 * cycle_num
    metric_b = 750 * cycle_num
    ws.append([
        cycle_num,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ANALYTICS_CATALOG.get(analytics_key, analytics_key),
        metric_a,
        metric_b,
        f"=D{row_idx}-E{row_idx}",
    ])
    wb.save(abs_path)
    return abs_path, f"Updated analytics workbook '{abs_path}' (cycle #{cycle_num})."

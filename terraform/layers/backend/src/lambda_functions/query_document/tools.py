from datetime import date


# ---------- Tool definitions (Bedrock Converse toolSpec format) ----------

TOOL_SPECS = [
    {
        "toolSpec": {
            "name": "get_current_date",
            "description": "Returns today's date. Use this whenever the question involves calculating durations, deadlines, days remaining, or any time-relative answer.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "get_my_entitlements",
            "description": "Returns the current user's leave and benefit entitlements: total vacation days, days used, days remaining, and training budget remaining.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
    {
        "toolSpec": {
            "name": "get_my_payroll_info",
            "description": "Returns the current user's payroll information: salary band, current salary, and next review date.",
            "inputSchema": {
                "json": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }
    },
]

TOOL_CONFIG = {
    "tools": TOOL_SPECS,
    "toolChoice": {"auto": {}},
}


# ---------- Mock implementations ----------

def get_current_date() -> dict:
    return {"today": date.today().isoformat()}


def get_my_entitlements() -> dict:
    return {
        "vacation_days_total": 25,
        "vacation_days_used": 11,
        "vacation_days_remaining": 14,
        "training_budget_remaining": 750,
    }


def get_my_payroll_info() -> dict:
    return {
        "salary_band": "L4",
        "current_salary": 72000,
        "next_review_date": "2026-09-01",
    }


# ---------- Dispatcher ----------

def execute_tool(name: str, tool_input: dict) -> dict:
    print(f"Executing tool: {name} with input: {tool_input}")
    if name == "get_current_date":
        return get_current_date()
    if name == "get_my_entitlements":
        return get_my_entitlements()
    if name == "get_my_payroll_info":
        return get_my_payroll_info()
    raise ValueError(f"Unknown tool: {name}")

# core/api/routes/dashboard.py
#
# Web dashboard sync endpoint.
# POST /dashboard/report  — receive a summary report from the plugin and
#                           persist it so the web dashboard can display it.

from datetime import datetime, timezone

from api.database import analysis_results
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class CodeValidatorPayload(BaseModel):
    files_scanned: int = 0
    total_issues: int = 0
    total_errors: int = 0
    total_warnings: int = 0


class AssetNamingPayload(BaseModel):
    total_scanned: int = 0
    invalid_assets: int = 0
    scan_time_s: float = 0.0


class DashboardReportRequest(BaseModel):
    project_name: str = "Unknown"
    engine: str = "unreal"
    report_type: str  # "code_validator" | "asset_naming"
    code_validator: CodeValidatorPayload | None = None
    asset_naming: AssetNamingPayload | None = None


@router.post("/dashboard/report")
async def post_dashboard_report(payload: DashboardReportRequest):
    """
    Receive a summary report from the UE5/Unity plugin and persist it to
    MongoDB so the web dashboard can display history, trends, and per-project
    analytics.
    """
    doc: dict = {
        "project_name": payload.project_name,
        "engine": payload.engine,
        "report_type": payload.report_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if payload.report_type == "code_validator" and payload.code_validator:
        doc["data"] = payload.code_validator.model_dump()
    elif payload.report_type == "asset_naming" and payload.asset_naming:
        doc["data"] = payload.asset_naming.model_dump()
    else:
        doc["data"] = {}

    try:
        result = await analysis_results.insert_one(doc)
        return {
            "status": "ok",
            "inserted_id": str(result.inserted_id),
            "timestamp": doc["timestamp"],
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
        }

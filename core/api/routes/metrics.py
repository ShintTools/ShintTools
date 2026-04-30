# core/api/routes/metrics.py
#
# Endpoints:
#   GET /metrics/score/latest   — latest Quality Score for a project
#   GET /metrics/score/history  — score history (time series)

from api.database import get_latest_score, get_score_history
from fastapi import APIRouter, Query

router = APIRouter()


@router.get("/metrics/score/latest")
async def score_latest(
    project_id: str = Query(..., description="Project identifier"),
):
    """Return the most recent Quality Score for a project.

    The score is computed automatically after each full scan
    (/validate/project or /validate/blueprints) and persisted
    in the project_scores collection.

    Returns 404 if no score exists yet for this project.
    """
    doc = await get_latest_score(project_id)

    if doc is None:
        return {
            "error": "No score found for this project",
            "project_id": project_id,
        }

    return doc


@router.get("/metrics/score/history")
async def score_history(
    project_id: str = Query(..., description="Project identifier"),
    limit: int = Query(
        default=30,
        ge=1,
        le=100,
        description="Max number of records to return",
    ),
):
    """Return the score history for a project, newest first.

    Use this to render trend charts in the plugin dashboard.
    Each entry contains the overall_score, category_scores,
    issue_counts, and timestamp.
    """
    docs = await get_score_history(project_id, limit=limit)

    return {
        "project_id": project_id,
        "count": len(docs),
        "scores": docs,
    }

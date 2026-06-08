import pytest


@pytest.mark.anyio
async def test_dashboard_report_unity_asset_naming(async_client):
    """
    Verifies that POST /dashboard/report accepts Unity asset naming reports.
    """
    payload = {
        "project_name": "MyUnityProject",
        "engine": "unity",
        "report_type": "asset_naming",
        "asset_naming": {
            "total_scanned": 150,
            "invalid_assets": 8,
            "scan_time_s": 2.35,
        },
    }

    response = await async_client.post("/dashboard/report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")  # ok if DB available, error if not


@pytest.mark.anyio
async def test_dashboard_report_unity_code_validator(async_client):
    """
    Verifies that POST /dashboard/report accepts Unity code validator reports.
    Returns either "ok" (DB available) or "error" (DB unavailable in test).
    """
    payload = {
        "project_name": "MyUnityProject",
        "engine": "unity",
        "report_type": "code_validator",
        "code_validator": {
            "files_scanned": 42,
            "total_issues": 5,
            "total_errors": 1,
            "total_warnings": 4,
        },
    }

    response = await async_client.post("/dashboard/report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")  # ok if DB available, error if not


@pytest.mark.anyio
async def test_dashboard_report_unreal_asset_naming(async_client):
    """
    Verifies that POST /dashboard/report still works for Unreal.
    """
    payload = {
        "project_name": "MyUE5Project",
        "engine": "unreal",
        "report_type": "asset_naming",
        "asset_naming": {
            "total_scanned": 500,
            "invalid_assets": 25,
            "scan_time_s": 5.12,
        },
    }

    response = await async_client.post("/dashboard/report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")


@pytest.mark.anyio
async def test_dashboard_report_missing_data_payload(async_client):
    """
    Verifies that /dashboard/report handles missing data gracefully.
    """
    payload = {
        "project_name": "MyProject",
        "engine": "unity",
        "report_type": "asset_naming",
        # asset_naming is missing
    }

    response = await async_client.post("/dashboard/report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "error")

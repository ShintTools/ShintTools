# core/api/routes/validate.py

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class ValidateAssetsRequest(BaseModel):
    paths: list[str] = Field(
        default_factory=list, description="Asset paths to validate"
    )


class ValidateCodeRequest(BaseModel):
    file_path: str = Field(..., description="Relative path of the source file")
    content: str = Field(default="", description="Full text content of the source file")
    engine: str = Field(
        default="unreal", description="Target engine: 'unreal' | 'unity'"
    )


@router.post("/validate/assets")
async def validate_assets(payload: ValidateAssetsRequest):
    """
    Validates asset naming conventions for a list of asset paths.
    Returns a mock response until Sprint 4 (Asset Naming Bot) is implemented.
    """
    # TODO Sprint 4: Replace mock with real Asset Naming Bot logic
    return {
        "summary": {
            "total": 0,
            "issues": 0,
            "errors": 0,
            "warnings": 0,
        },
        "issues": [],
        "message": "Mock response — Sprint 4 pending",
    }


@router.post("/validate/code")
async def validate_code(payload: ValidateCodeRequest):
    """
    Analyses a source file or Blueprint for code smells and bad patterns.
    Returns a mock response until Sprint 5 (Deep Code Validator) is implemented.
    """
    # TODO Sprint 5: Replace mock with real Deep Code Validator logic
    return {
        "summary": {
            "total": 0,
            "issues": 0,
            "errors": 0,
            "warnings": 0,
        },
        "issues": [],
        "message": "Mock response — Sprint 5 pending",
    }

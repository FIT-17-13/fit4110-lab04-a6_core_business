import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

SERVICE_NAME = os.getenv("SERVICE_NAME", "core-business")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")

app = FastAPI(
    title="FIT4110 Lab 04 - Core Business Service",
    version=SERVICE_VERSION,
    description="Policy Engine cho Smart Campus – kiểm tra quyền truy cập thẻ và quản lý chính sách.",
)

# Whitelist thẻ hợp lệ
VALID_CARDS = {
    "RFID-2026-001",
    "RFID-2026-002",
    "RFID-2026-003",
}

DECISIONS: List[Dict] = []

POLICIES: List[Dict] = [
    {"policyId": "POL-001", "policyType": "ACCESS_HOURS", "description": "Cho phep truy cap 06:00-22:00"},
    {"policyId": "POL-002", "policyType": "CARD_WHITELIST", "description": "Chi the dang ky moi duoc vao"},
]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class AccessCheckRequest(BaseModel):
    cardId: str = Field(..., min_length=1)
    gateId: str = Field(..., min_length=1)
    direction: str = Field(..., pattern="^(IN|OUT)$")
    idempotencyKey: Optional[str] = None


class AccessDecision(BaseModel):
    decisionId: str
    cardId: str
    gateId: str
    allow: bool
    reasonCode: str
    decidedAt: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_problem(*, status_code: int, title: str, detail: str, instance: Optional[str] = None) -> Dict:
    p = {"type": "about:blank", "title": title, "status": status_code, "detail": detail}
    if instance:
        p["instance"] = instance
    return p


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        problem = exc.detail
    else:
        problem = build_problem(
            status_code=exc.status_code,
            title=status.HTTP_STATUS_CODES.get(exc.status_code, "HTTP Error"),
            detail=str(exc.detail),
            instance=str(request.url.path),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=problem,
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    loc = ".".join(str(i) for i in first.get("loc", []))
    msg = first.get("msg", "Validation error")
    detail = f"{loc}: {msg}" if loc else msg
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation error",
            detail=detail,
            instance=str(request.url.path),
        ),
        media_type="application/problem+json",
    )


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Missing Authorization header",
                instance="/access/check",
            ),
        )
    if authorization != f"Bearer {AUTH_TOKEN}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=build_problem(
                status_code=status.HTTP_401_UNAUTHORIZED,
                title="Unauthorized",
                detail="Invalid bearer token",
                instance="/access/check",
            ),
        )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=SERVICE_NAME, version=SERVICE_VERSION)


@app.post("/access/check", response_model=AccessDecision, dependencies=[Depends(verify_bearer_token)])
def access_check(payload: AccessCheckRequest) -> AccessDecision:
    allow = payload.cardId in VALID_CARDS
    reason = "VALID_CARD" if allow else "UNKNOWN_CARD"
    decision = AccessDecision(
        decisionId=str(uuid.uuid4()),
        cardId=payload.cardId,
        gateId=payload.gateId,
        allow=allow,
        reasonCode=reason,
        decidedAt=now_iso(),
    )
    DECISIONS.append(decision.model_dump())
    return decision


@app.get("/policies/access", dependencies=[Depends(verify_bearer_token)])
def list_policies(limit: int = Query(default=10, ge=1, le=100)) -> Dict:
    return {"data": POLICIES[:limit], "total": len(POLICIES)}


@app.get("/decisions", dependencies=[Depends(verify_bearer_token)])
def list_decisions(limit: int = Query(default=20, ge=1, le=100)) -> Dict:
    return {"data": DECISIONS[-limit:], "total": len(DECISIONS)}

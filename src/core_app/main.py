import os
from datetime import datetime, timezone
from enum import Enum
from http import HTTPStatus
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field


SERVICE_NAME = os.getenv("SERVICE_NAME", "core-business")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "1.0.0")
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "local-dev-token")


app = FastAPI(
    title="FIT4110 Lab 04 - Core Business Service",
    version=SERVICE_VERSION,
    description="API trung tâm xử lý quy tắc nghiệp vụ an niên, chính sách ra/vào trường học.",
)


# ============================================================================
# ENUMS
# ============================================================================

class Direction(str, Enum):
    IN = "IN"
    OUT = "OUT"


class PolicyType(str, Enum):
    timeBased = "timeBased"
    roleBased = "roleBased"


class ReasonCode(str, Enum):
    VALID_CARD = "VALID_CARD"
    EXPIRED_CARD = "EXPIRED_CARD"
    UNKNOWN_CARD = "UNKNOWN_CARD"
    INVALID_REQUEST = "INVALID_REQUEST"
    POLICY_VIOLATION = "POLICY_VIOLATION"


class AlertSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# ============================================================================
# MODELS
# ============================================================================

class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class AccessRequest(BaseModel):
    cardId: str = Field(..., min_length=3, examples=["RFID-2026-001"])
    gateId: str = Field(..., min_length=3, examples=["gate-main-01"])
    direction: Direction = Field(..., examples=[Direction.IN])
    idempotencyKey: Optional[str] = Field(default=None, examples=["idem-8899-abc"])


class AccessDecision(BaseModel):
    decisionId: str
    allow: bool
    reasonCode: str
    policyId: Optional[str] = None
    expiresAt: Optional[str] = None
    operatorNote: Optional[str] = None


class PolicyBase(BaseModel):
    policyId: str
    policyType: PolicyType


class TimeBasedPolicy(PolicyBase):
    policyType: PolicyType = PolicyType.timeBased
    allowedHours: str = Field(..., examples=["07:00-18:00"])


class RoleBasedPolicy(PolicyBase):
    policyType: PolicyType = PolicyType.roleBased
    allowedRoles: List[str] = Field(..., examples=[["STUDENT", "STAFF"]])


# Union type để dùng trong response
Policy = TimeBasedPolicy | RoleBasedPolicy


class PoliciesResponse(BaseModel):
    data: List[Policy]
    nextCursor: Optional[str] = None


# ============================================================================
# IN-MEMORY DATA (Mock database)
# ============================================================================

# Mock thẻ hợp lệ
VALID_CARDS = {
    "RFID-2026-001": {
        "cardId": "RFID-2026-001",
        "name": "Nguyễn Văn A",
        "role": "STUDENT",
        "expiresAt": "2026-12-31T23:59:59Z",
        "status": "ACTIVE"
    },
    "RFID-2026-002": {
        "cardId": "RFID-2026-002",
        "name": "Trần Thị B",
        "role": "STAFF",
        "expiresAt": "2027-06-30T23:59:59Z",
        "status": "ACTIVE"
    }
}

# Mock chính sách
POLICIES: List[Dict] = [
    {
        "policyId": "POL-STUDENT-01",
        "policyType": "timeBased",
        "allowedHours": "07:00-18:00",
        "description": "Chính sách giờ ra/vào cho học sinh"
    },
    {
        "policyId": "POL-STAFF-01",
        "policyType": "roleBased",
        "allowedRoles": ["STAFF"],
        "description": "Chính sách truy cập cho nhân viên"
    }
]

# Mock quyết định
DECISIONS: List[Dict] = []


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def build_problem(
    *,
    status_code: int,
    title: str,
    detail: str,
    problem_type: str = "about:blank",
) -> Dict:
    return {
        "type": problem_type,
        "title": title,
        "status": status_code,
        "detail": detail,
    }


def verify_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            
        )

    expected = f"Bearer {AUTH_TOKEN}"
    if authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def next_decision_id() -> str:
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"DEC-{today}-{len(DECISIONS) + 1:04d}"


# ============================================================================
# EXCEPTION HANDLERS
# ============================================================================

def _http_title(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP Error"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=build_problem(
            status_code=exc.status_code,
            title=_http_title(exc.status_code),
            detail=str(exc.detail),
        ),
        media_type="application/problem+json",
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    location = ".".join(str(item) for item in first_error.get("loc", []))
    message = first_error.get("msg", "Request validation error")
    detail = f"{location}: {message}" if location else message

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=build_problem(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            title="Validation error",
            detail=detail,
            problem_type="https://smart-campus.local/problems/validation-error",
        ),
        media_type="application/problem+json",
    )


# ============================================================================
# ENDPOINTS
# ============================================================================

@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Kiểm tra trạng thái dịch vụ"""
    return HealthResponse(
        status="ok",
        service=SERVICE_NAME,
        version=SERVICE_VERSION,
    )


@app.post(
    "/access/check",
    response_model=AccessDecision,
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ProblemDetails},
        401: {"model": ProblemDetails},
        422: {"model": ProblemDetails},
    },
)
def check_access(
    request: AccessRequest,
    response: Response,
    authorization: Optional[str] = Header(default=None),
) -> AccessDecision:
    verify_bearer_token(authorization)
    decision_id = next_decision_id()
    
    # Kiểm tra thẻ
    card = VALID_CARDS.get(request.cardId)
    
    if not card:
        decision = AccessDecision(
            decisionId=decision_id,
            allow=False,
            reasonCode=ReasonCode.UNKNOWN_CARD,
            operatorNote="Thẻ không tồn tại trong hệ thống"
        )
        DECISIONS.append({
            "decisionId": decision_id,
            "cardId": request.cardId,
            "gateId": request.gateId,
            "direction": request.direction.value,
            "decision": decision.model_dump(),
            "createdAt": now_iso()
        })
        return decision
    
    # Kiểm tra hạn thẻ
    expires_at = card.get("expiresAt")
    if expires_at and expires_at < now_iso():
        decision = AccessDecision(
            decisionId=decision_id,
            allow=False,
            reasonCode=ReasonCode.EXPIRED_CARD,
            expiresAt=expires_at,
            operatorNote="Thẻ đã hết hạn"
        )
        DECISIONS.append({
            "decisionId": decision_id,
            "cardId": request.cardId,
            "gateId": request.gateId,
            "direction": request.direction.value,
            "decision": decision.model_dump(),
            "createdAt": now_iso()
        })
        return decision
    
    # Thẻ hợp lệ
    decision = AccessDecision(
        decisionId=decision_id,
        allow=True,
        reasonCode=ReasonCode.VALID_CARD,
        policyId="POL-STUDENT-01",
        expiresAt=expires_at,
        operatorNote=f"Quyền truy cập được phép - {card.get('name')}"
    )
    DECISIONS.append({
        "decisionId": decision_id,
        "cardId": request.cardId,
        "gateId": request.gateId,
        "direction": request.direction.value,
        "decision": decision.model_dump(),
        "createdAt": now_iso()
    })
    return decision


@app.get(
    "/policies/access",
    response_model=PoliciesResponse,
)
def list_policies(
    limit: int = Query(default=10, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
) -> PoliciesResponse:
    verify_bearer_token(authorization)
    # Simple cursor pagination mock
    start_idx = 0
    if cursor:
        try:
            start_idx = int(cursor)
        except ValueError:
            start_idx = 0
    
    end_idx = start_idx + limit
    policies_slice = POLICIES[start_idx:end_idx]
    
    # Convert to Policy objects
    policy_objects: List[Policy] = []
    for policy in policies_slice:
        if policy["policyType"] == "timeBased":
            policy_objects.append(TimeBasedPolicy(**policy))
        elif policy["policyType"] == "roleBased":
            policy_objects.append(RoleBasedPolicy(**policy))
    
    next_cursor = None
    if end_idx < len(POLICIES):
        next_cursor = str(end_idx)
    
    return PoliciesResponse(
        data=policy_objects,
        nextCursor=next_cursor
    )


@app.get(
    "/policies/access/{policyId}",
)
def get_access_policy(policyId: str, authorization: Optional[str] = Header(default=None)):
    verify_bearer_token(authorization)
    for policy in POLICIES:
        if policy["policyId"] == policyId:
            if policy["policyType"] == "timeBased":
                return TimeBasedPolicy(**policy)
            elif policy["policyType"] == "roleBased":
                return RoleBasedPolicy(**policy)
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Policy not found"
    )


@app.get(
    "/decisions",
)
def list_decisions(
    limit: int = Query(default=20, ge=1, le=100),
    cursor: Optional[str] = Query(default=None),
    authorization: Optional[str] = Header(default=None),
):
    verify_bearer_token(authorization)
    start_idx = 0
    if cursor:
        try:
            start_idx = int(cursor)
        except ValueError:
            start_idx = 0
    
    end_idx = start_idx + limit
    decisions_slice = DECISIONS[start_idx:end_idx]
    
    next_cursor = None
    if end_idx < len(DECISIONS):
        next_cursor = str(end_idx)
    
    return {
        "data": [d["decision"] for d in decisions_slice],
        "nextCursor": next_cursor
    }


@app.get(
    "/decisions/{decisionId}",
    response_model=AccessDecision,
)
def get_decision(decisionId: str, authorization: Optional[str] = Header(default=None)) -> AccessDecision:
    verify_bearer_token(authorization)
    for decision_record in DECISIONS:
        if decision_record["decisionId"] == decisionId:
            return AccessDecision(**decision_record["decision"])
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Decision {decisionId} not found"
    )
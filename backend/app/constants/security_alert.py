"""보안·감사 알림 심각도 규칙 (06 security_alerts 감지 유형 표)."""

# 높을수록 큰 값. 같은 알림에 다시 감지되면 이 순서로 올리기만 한다
SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# 유형마다 고정된 심각도. SENSITIVE_INPUT 은 가린 유형에 따라 다르다
FIXED_SEVERITY = {
    "BLOCKED_DOC_QUERY": "MEDIUM",
    "ACCOUNT_LOCKED": "MEDIUM",
    "LOGIN_BLOCKED": "LOW",
    "URGENT_CLOSED": "HIGH",
    "MASS_QUERY": "MEDIUM",
    # AI 보안 검토 기준. S01(사고 의심)만 HIGH, 나머지 우회·추출 요청은 MEDIUM. 더 올리는 일은 사람이 한다
    # AI 가 안전 판단으로 거절해 S01~S06 을 못 낸 문의. 위험 요청이면 거절될 가능성이 높아 따로 남긴다
    "AI_REFUSED": "MEDIUM",
    "S01": "HIGH",
    "S02": "MEDIUM",
    "S03": "MEDIUM",
    "S04": "MEDIUM",
    "S05": "MEDIUM",
    "S06": "MEDIUM",
}

# 이 유형만 가렸으면 MEDIUM, 그 밖의 유형이 하나라도 있으면 HIGH
MEDIUM_SENSITIVE_TYPES = frozenset({"OTP"})

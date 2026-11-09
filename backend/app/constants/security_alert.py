"""보안·감사 알림 심각도 규칙 (06 security_alerts 감지 유형 표)."""

from app.constants.security import SECURITY_RULES

# 높을수록 큰 값. 같은 알림에 다시 감지되면 이 순서로 올리기만 한다
SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# 유형마다 고정된 심각도. SENSITIVE_INPUT 은 가린 유형에 따라 다르다
FIXED_SEVERITY = {code: definition[1] for code, definition in SECURITY_RULES.items() if code != "SENSITIVE_INPUT"}

# 이 유형만 가렸으면 MEDIUM, 그 밖의 유형이 하나라도 있으면 HIGH
MEDIUM_SENSITIVE_TYPES = frozenset({"OTP"})

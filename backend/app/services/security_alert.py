"""보안·감사 알림 감지 (06 security_alerts, AUDIT-01·04).

원천 사건(audit_logs)을 남기는 곳에서 같은 트랜잭션으로 부른다. 커밋은 호출자가 한다.
"""
from app.constants.security_alert import FIXED_SEVERITY, MEDIUM_SENSITIVE_TYPES, SEVERITY_RANK
from app.models import SecurityAlert
from app.repositories.security_alert import SecurityAlertRepository
from app.utils import datetime_utils
from app.utils.dict_utils import add_counts


def severity_of(alert_type: str, detail: dict[str, int]) -> str:
    """감지 유형 표의 심각도. SENSITIVE_INPUT 은 OTP 만 가렸으면 MEDIUM, 그 밖은 HIGH."""
    if alert_type == "SENSITIVE_INPUT":
        return "MEDIUM" if set(detail) <= MEDIUM_SENSITIVE_TYPES else "HIGH"
    return FIXED_SEVERITY[alert_type]


def detect(
    alerts: SecurityAlertRepository,
    alert_type: str,
    subject_user_id: int,
    target_type: str,
    target_id: int,
    detail: dict[str, int] | None = None,
) -> SecurityAlert:
    """알림을 만들거나, 같은 대상의 종결 전 알림에 합친다.

    detail 은 유형별 개수만 받는다 (값·원문 금지). 합칠 때 개수를 더하고, 횟수·마지막 감지 시각을 올리고,
    심각도는 올리기만 한다. 종결된 알림에는 합치지 않으므로 다시 감지되면 새 알림이 생긴다.
    """
    detail = dict(detail or {})
    key = (alert_type, subject_user_id, target_type, target_id)
    now = datetime_utils.now()

    alert = alerts.open_for_update(*key)
    if alert is None:
        alert = SecurityAlert(
            alert_type=alert_type, severity=severity_of(alert_type, detail), status="NEW",
            subject_user_id=subject_user_id, target_type=target_type, target_id=target_id,
            detail=detail, occurrence_count=1, first_detected_at=now, last_detected_at=now,
        )
        if alerts.add_open(alert):
            return alert
        # 다른 요청이 같은 대상의 알림을 먼저 만들었다. 그 알림에 합친다
        alert = alerts.open_for_update(*key)

    alert.occurrence_count += 1
    alert.last_detected_at = now
    alert.detail = add_counts(alert.detail, detail)     # 새 dict 를 넣어야 JSONB 변경이 저장된다
    severity = severity_of(alert_type, alert.detail)
    if SEVERITY_RANK[severity] > SEVERITY_RANK[alert.severity]:
        alert.severity = severity
    return alert

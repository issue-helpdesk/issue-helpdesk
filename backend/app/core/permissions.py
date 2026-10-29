# 역할마다 볼 수 있는 view_scope (청크_메타데이터.md 4장). 문서·과거 사례·문의 출처에 똑같이 쓴다
VISIBLE_SCOPES = {
    "EMPLOYEE": ("ALL",),
    "AGENT": ("ALL", "AGENT"),
    "ADMIN": ("ALL", "AGENT", "ADMIN"),
}


def visible_scopes(service_role: str) -> tuple[str, ...]:
    return VISIBLE_SCOPES.get(service_role, ())

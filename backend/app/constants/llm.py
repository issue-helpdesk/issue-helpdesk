"""AI 사용 현황 비용 기준 (OP-03)."""

MODEL_PRICES_USD_PER_MTOK = {"claude-sonnet-5-5": (2.0, 10.0)}  # 모델 → (입력, 출력) 100만 토큰당 USD. 값은 공식 단가표로 채운다
MONTHLY_BUDGET_USD: float | None = 150                         # 월 예산. None 이면 예산을 보여 주지 않는다
BUDGET_MONTH_DAYS = 30                                          # 기간 예산 = 월 예산 × 기간 일수 / 이 값
FREE_ADAPTERS = {"Mock"}                                        # 비용이 들지 않는 호출

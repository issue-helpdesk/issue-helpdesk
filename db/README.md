# DB 스키마와 데이터 넣기

`dataset/data/`의 CSV·JSON을 PostgreSQL(Supabase)에 넣기 위한 파일입니다.

| 파일 | 내용 |
|---|---|
| `schema.sql` | 표 생성 SQL. 여러 번 실행해도 안전합니다. |
| `seed.py` | 표를 만들고 데이터를 넣는 스크립트 |

## 실행

1. 저장소 루트의 `.env.example`을 `.env`로 복사하고 `DATABASE_URL`을 채웁니다. `.env`는 저장소에 올리지 않습니다.
2. `pip install "psycopg[binary]"`
3. 아래 명령을 저장소 루트에서 실행합니다.

```bash
python db/seed.py --check        # DB 없이 파일만 검사
python db/seed.py                # 표를 만들고 데이터를 넣음
python db/seed.py --reset        # 표를 비우고 다시 넣음
python db/seed.py --with-eval    # 평가용 정답셋도 넣음
```

같은 명령을 다시 실행하면 같은 키의 행을 덮어씁니다. 중간에 실패하면 아무것도 반영되지 않습니다. 끝나면 표마다 파일 건수와 DB 건수를 나란히 보여 줍니다.

## 표

| 표 | 원본 | 건수 |
|---|---|---|
| `categories` | taxonomy.json `category_detail` | 7 |
| `urgency_levels` | taxonomy.json `urgency` | 4 |
| `teams` | taxonomy.json `team_detail` | 6 |
| `channels`, `handling_types` | taxonomy.json | 3, 2 |
| `user_roles`, `assignee_roles` | taxonomy.json | 3, 4 |
| `scenarios` | taxonomy.json `scenarios` | 50 |
| `major_incidents` | taxonomy.json `major_incidents` | 7 |
| `faqs` | faq.csv | 40 |
| `employees` | employees.csv | 400 |
| `assignees` | assignees.csv | 50 |
| `assignee_scenarios` | assignees.csv의 `scenario_ids`를 한 줄씩 풀어 넣음 | 116 |
| `inquiry_history` | history.csv | 400 |
| `eval.inquiries` | eval_inquiries.csv (`--with-eval`일 때만) | 50 |

## 원본과 다른 점

- `faqs.keywords`: 쉼표로 이어진 글자를 배열(`text[]`)로 넣습니다.
- `assignees.assignable`, `assignee_roles.assignable`: `Y`/`N`을 참/거짓으로 넣습니다.
- `assignee_scenarios`: `scenario_ids`가 `-`인 담당자(팀장·조직장)는 행이 없습니다.
- `inquiry_history.assignee_emp_id`: 원본에는 담당자 이름만 있어, 이름으로 `assignees`를 찾아 사번을 함께 넣습니다.
- 빈 칸(`resolved_at`, `prevention`, `related_faq`, 시나리오의 `faq`)은 NULL로 넣습니다.
- 시각은 한국 시간 그대로 `timestamp`(시간대 없음)로 넣습니다.

## 알아둘 점

- **PostgreSQL 17 기준입니다.** Supabase와 같은 PostgreSQL 17(pgvector 0.8)에서 실행을 확인했고, 16에서도 동작합니다.
- **평가용 정답셋은 따로 둡니다.** AI 검색 자료에 넣지 않는 데이터라 `public`이 아닌 `eval` 스키마에 두고, `--with-eval`을 줬을 때만 넣습니다.
- **모든 표에 행 수준 보안(RLS)을 켭니다.** Supabase가 자동으로 만드는 REST API(anon 키)로는 읽거나 쓸 수 없습니다. 백엔드는 DB에 직접 붙으므로 영향이 없습니다.
- **pgvector 확장을 켜 둡니다.** 임베딩을 담을 표는 아직 없습니다.
- **챗봇이 새로 만드는 문의·티켓·세션 표는 여기 없습니다.** 시스템 설계서대로 백엔드의 Alembic 마이그레이션에서 만듭니다. 이 SQL도 그때 첫 마이그레이션으로 옮기는 것을 권장합니다.

# 공통 파서 (M2-1-1)

가이드 문서(PPTX·PDF·DOCX·MD·TXT)를 읽어 **같은 모양의 결과**(`ParsedDocument`)로 돌려줍니다.
기준 문서는 `dataset/guides` (원천 JSON 하나에서 네 형식을 만든 정리본)입니다. 청크 나누기(M2-1-2)와 메타데이터(M2-1-3)는 이 결과를 입력으로 씁니다.

## 사용

```python
from app.rag.parser import parse, ParseError

try:
    doc = parse('dataset/guides/SW/guide/IT-SW-002_SW 라이선스 신청·인증 가이드.md')
except ParseError as e:
    e.reason, e.message   # 'encrypted', '암호가 걸린 문서입니다. …' (업로드 화면에 그대로 보여 줄 수 있음)

doc.meta        # {'doc_no': 'IT-SW-002', 'version': 'v2.0', 'access_level': '사내 일반', 'scenarios': ['SW-02'], ...}
doc.outline()   # [(0, 'SW 라이선스 신청·인증 가이드'), (1, '1. 개요'), (3, '목적'), ..., (2, '3.1 유료 프로그램 라이선스 신청'), ...]
doc.elements    # 읽는 순서대로 heading / paragraph / list_item / table / image
doc.quality     # {'mode': 'layout', 'coverage': 0.99, 'ok': True, ...} — 아래 '안전장치'
doc.warnings    # 쪽 해석 실패, 보수 모드 전환, 누락 의심
```

확인 명령 (저장소 루트):

```bash
cd backend && python -m app.rag.parser ../dataset/guides/SW --out ../참고/parsed   # 미리보기 md (--json 이면 json 도)
python tests/check_guides.py                                                                # 원천 JSON 대비 채점 (57종 × 4형식, 약 1분)
python tests/check_guides.py IT-SW-002 --format pdf --show                                  # 한 문서의 다른 곳 보기
pytest tests/test_parser.py tests/test_parser_robustness.py
```

## 파일 구성

| 파일 | 역할 |
|---|---|
| `__init__.py` | `parse(path)` 진입점: 파일 점검 → 형식별 파서 → 누락 감지(필요하면 보수 모드로 다시 읽기) → 로그 |
| `models.py` | 결과 모양 `ParsedDocument` · `Element`, 미리보기 `to_markdown()` |
| `md_parser.py` · `docx_parser.py` | 형식별 파서: 읽는 순서대로 요소를 만든다 |
| `pptx_parser.py` · `pdf_parser.py` | 형식별 파서: 쪽마다 글 상자·표·그림·배경 상자(`Item`)를 만든다 |
| `slides.py` | PPTX·PDF 공통 장표 해석 (쪽 종류·제목·소제목·읽는 순서) |
| `common.py` | 공통 도구와 후처리 `finalize()` (뺀 글자 정리·제목 정리·항목 머리·Q&A·메타데이터·제목 경로) |
| `quality.py` | 누락 감지 |
| `errors.py` | `ParseError` (원인 코드 + 사용자 안내 문구, 미지원 형식 변환 안내) |
| `__main__.py` | 결과 확인 명령 |

개발용 채점 도구는 `tests/check_guides.py`에 있습니다 (운영 코드 아님).

## 결과 모양

| 항목 | 내용 |
|---|---|
| `kind` | `heading` · `paragraph` · `list_item` · `table` · `image` |
| `level` | 제목 수준. 0 문서 제목 · 1 장(`1. 개요`, `부록 · 관련 문서 · 용어`, `개정 이력`) · 2 항목(`3.1 …`) · 3 소제목·카드 제목(`이런 경우`, `목적` …) |
| `section` | 속한 제목 경로. 예: `['3. 증상별 조치 방법', '3.1 …', '조치 방법']` |
| `page` | PDF 쪽 / PPTX 슬라이드 번호. DOCX·MD·TXT 는 `None` |
| `order` | 문서 안 순번 |
| `meta['props']` | 항목 제목(level 2)의 머리 정보 `[['문의 유형', 'SW-02'], ['처리 구분', '신청·승인 후 처리'], ['담당 부서', '서비스데스크']]` |
| `meta['card']` | 카드 제목(level 3)이면 `True` (카드 안의 목록이 이어짐) |
| `meta['code']` | 코드·명령어 문단이면 `True` (줄바꿈을 살림) |
| `doc.meta` | 문서 메타데이터. `.md` 머리말과 같은 키 (`doc_no`, `title`, `category`, `doc_type`, `version`, `effective_date`, `access_level`, `audience`, `owner`, `pair`, `scenarios`, `faqs`, `keywords` …). 다른 형식은 문서 정보 표에서 읽어 같은 키로 맞춤 |
| `doc.info` | 문서 정보 표의 원래 항목 이름 그대로 |
| `doc.properties['cover']` | 템플릿 문서의 표지 문구 (본문 아님) |
| `doc.dropped` | 본문에서 뺀 글자 `[이유, 글자, 쪽]` — 이유: `toc` · `skip_title` · `divider` · `page_no` · `repeat_title` · `band`(꼬리말·제목 띠) |

형식이 달라도 같게 맞춘 것: 장 제목 표기(`01  개요` → `1. 개요`), 번호 목록(`①` → `1.`), 질문·답변(`Q. …`/`A. …` 문단), 문서 정보·목차(본문에서 빼고 `doc.meta` 로), `(계속)` 쪽의 반복 제목.

## 형식별 처리

| 형식 | 구조를 읽는 방법 |
|---|---|
| MD·TXT | 머리말 → `doc.meta`, `#`~`####` 제목, 혼자 있는 굵은 줄 = 카드 제목, `**문의 유형** … · **처리 구분** …` = 항목 머리, `## 목차` 건너뜀. TXT는 줄마다 문단 |
| DOCX | 제목 스타일(Heading 1~3), 표지의 큰 글자 = 문서 제목, 2줄 카드 표 → 카드 제목 + 목록, 1칸 표(안내 상자) → 문단, 칸 안의 표도 읽음 |
| PPTX·PDF | 같은 장표 해석(`slides.py`): 표지·장 구분·쪽 제목, 굵고 색 있는 큰 글자 = 소제목, 상자 맨 위 굵은 글자 = 카드 제목. 행 → 칸 → 위아래 순서로 읽는다. PDF는 글자 → 줄 → 글 상자를 다시 만든 뒤 같은 해석을 쓴다 |

## 안전장치

| 상황 | 처리 |
|---|---|
| 파일 없음·빈 파일·미지원 형식·zip이 아닌 docx/pptx·암호(OLE)·%PDF 없음·암호 PDF | 읽기 전에 `ParseError` (`not_found` · `unsupported` · `empty` · `corrupt` · `encrypted`) |
| 라이브러리 내부 오류 | `ParseError('corrupt' 또는 'failed')`, 원인은 `detail`·로그에 |
| 글자를 하나도 얻지 못함 (스캔 PDF 등) | `ParseError('no_text')` |
| md·txt 인코딩 | utf-8(BOM) → cp949 순서로 시도, 둘 다 아니면 `ParseError('encoding')` |
| PDF 쪽·PPTX 슬라이드 하나가 깨짐 | 나머지는 정상 처리, 그 쪽은 글자만 추출 + 경고 |
| **내용 누락 의심** | 보수 모드로 다시 읽고 내용을 더 잘 지킨 쪽을 쓴다 (아래) |

**누락 감지** (`quality.py`) — 파서와 다른 길로 파일 글자를 전부 다시 읽어(docx 모든 문단·줄, pptx 모든 도형·표, PDF 모든 줄, md·txt 모든 줄) 결과와 비교한다.

| 검사 | 기준 | 잡는 것 |
|---|---|---|
| `coverage` | ≥ 0.98 | 원문 조각 글자 중 결과에 있는 비율. 조각은 결과 요소 하나(또는 이웃 6개 이내)에 들어 있어야 하고, 원문에 여러 번 나오면 그 횟수만큼 있어야 한다 |
| `long_missing` | 0개 | 40자 이상 문장이 하나라도 빠짐 (긴 문서에서 비율로는 가려지는 누락) |
| `missing_values` | 0개 | 숫자·코드(IT-SW-002, FAQ-023, AUTH-101, 443, 2026-10-16 …)가 결과에서 통째로 사라짐 |
| `dropped_ratio` | ≤ 0.15 | 정상 제외로 뺀 서로 다른 글자의 비율. 넘으면 배치 규칙이 본문을 뺀 것으로 의심 |

- 하나라도 어기면 `ok=False` → **보수 모드(safe)**로 다시 읽는다. 보수 모드는 제목 띠·꼬리말 띠의 글자도 본문으로 남긴다. 구조(제목 수준)는 덜 정확할 수 있지만 내용은 빠지지 않는다.
- 정당한 제외로 인정하는 것: 목차, 쪽 제목, 장 번호, 머리·바닥 띠의 쪽 번호, 반복 제목, 두 쪽 이상 반복되는 꼬리말, 템플릿 문서의 300자 이하 표지 문구.
- 표지 문구는 첫 장 앞에 문서 정보 표가 있는 템플릿 문서(정리본)일 때만 옮긴다 (md는 문서 제목 바로 뒤 인용 줄만). 그 밖의 문서에서 첫 장 앞 문단은 **서문으로 본문에 남는다**.
- 누락 감지 자체도 테스트한다: 결과에서 일부러 문단·반복 문장·코드를 지우면 잡히는지 (`tests/test_parser_robustness.py`).
- 로그 `app.rag.parser`: 성공은 INFO(형식·모드·포함률·요소 수·쪽 수·시간), 누락 의심·실패는 WARNING, 내부 오류는 스택과 함께 ERROR.

## 검증 결과 (2026-10-17)

| 묶음 | 파일 | 결과 |
|---|---|---|
| guides 원천 JSON 채점 | 57종 × 4형식 | 구조 일치 57/57, 내용 포함 1.000, 항목 머리·메타 일치 (네 형식 모두). 본문 순서(md 대비) docx 0.994 · pptx 0.993 · pdf 0.993 |
| guides 누락 감지 | 228 | 모두 배치 모드, 경고 0 |
| dataset/guides (정리 전, 배치가 다른 문서) | 114 | 오류 0, 16개는 보수 모드로 전환 후 경고 0 (예: HW-001 PDF 2,315자 → 9,422자) |
| 깨진·특수 파일 | 13종 | 모두 원인 있는 `ParseError` 또는 정상 처리 |
| 점검 보고서(2026-10-17) 재현 사례 | 5건 | 장 구분 쪽 본문, 그림 뒤 기울임 줄, 서문, 본문 숫자, YAML 목록 — 모두 보존 |

## 한계

- 그림 속 글자는 읽지 않습니다. 그림은 위치와 설명(`그림 3.1-1. …`)만 남깁니다. 스캔 PDF(OCR)도 범위 밖입니다.
- 보수 모드로 읽힌 문서는 제목 수준(특히 3.x 항목)이 덜 잡힐 수 있습니다. 청크를 제목 단위로 나눌 때 `doc.quality['mode']`를 보고 길이 기준으로 보완해야 합니다.
- 누락 감지는 글자가 결과에 "들어 있는지"를 봅니다. 읽는 순서가 섞인 것은 잡지 못합니다 (정리본은 채점 도구의 순서 지표로 확인).
- 누락 감지를 위해 파일을 한 번 더 읽습니다 (문서당 0.3~1.2초). 검사가 파서와 같은 코드를 쓰면 파서의 실수를 똑같이 놓치므로 일부러 따로 읽습니다.
- 선 없는 표는 PDF에서 문단으로 나옵니다. 같은 문서가 여러 형식이면 **`.md`를 등록**하는 것이 가장 정확합니다 (정리본 README 권장과 같음).
- PPTX·PDF 해석은 정리본 장표 배치를 기준으로 맞췄습니다. 다른 디자인의 장표는 보수 모드로 내용은 지키지만 구조는 덜 잡힐 수 있습니다.

"""근거 문장 고르기·검색어 만들기 (M3) 테스트. 본문은 IT-HW-001 3.6 청크 그대로."""
import pytest

from app.rag.search import ChunkHit, DocumentResult, build_query, pick_evidence

TEXT = """업무 PC 기본 장애 대응 가이드 > 3. 증상별 조치 방법 > 3.6 로그인 전에 '복구 키를 입력하세요' 화면이 뜸
문의 유형: HW-02 · 처리 구분: IT 담당자 처리 · 담당 부서: 엔드포인트지원팀

### 이런 경우
- 노트북을 켜면 로그인 화면 전에 '복구 키를 입력하세요'라는 화면이 뜬다.
화면 메시지: "복구 키를 입력하세요"
### 원인
- 노트북 펌웨어 업데이트 뒤 디스크 암호화가 복구 모드로 바뀜
### 조치 방법
1. 화면에 표시된 복구 키 ID를 적어 둡니다.
2. 아무 키나 여러 번 입력하지 않습니다.
3. IT 헬프데스크(내선 1000)에 전화합니다. 본인 확인 후 담당자가 복구 키를 알려 줍니다.
4. 안내받은 복구 키를 입력합니다.
[그림] 그림 3.6-1. 복구 키 입력 화면. 복구 키 ID가 표시되는 위치를 표시한다
### 해결 확인
- 복구 키를 입력한 뒤 로그인 화면이 나오면 해결된 것이다.
### 문의 시 알려 주실 정보
- 사번
- 화면의 복구 키 ID
- 노트북 모델명"""


def test_picks_lines_sharing_words():
    ev = pick_evidence('노트북 켜면 복구 키 입력하래요', TEXT)
    assert 1 <= len(ev) <= 3
    assert ev[0] == "노트북을 켜면 로그인 화면 전에 '복구 키를 입력하세요'라는 화면이 뜬다."
    assert all(s in TEXT for s in ev)                  # 본문에 그대로 있는 글만


def test_skips_heading_property_figure_and_short_lines():
    ev = pick_evidence('복구 키 ID 화면 로그인 HW-02 엔드포인트지원팀 사번', TEXT, limit=20)
    assert not any(' > ' in s or s.startswith(('#', '[그림]', '문의 유형')) for s in ev)
    assert '사번' not in ev


def test_no_evidence_when_unrelated():
    assert pick_evidence('프린터 토너가 떨어졌어요', TEXT) == ()
    assert pick_evidence('   ', TEXT) == ()


def test_evidence_passes_result_check():
    """고른 줄을 그대로 DocumentResult 에 넣어도 형식 검사(본문에 있는 문장만)를 통과한다."""
    ev = pick_evidence('복구 키를 입력하라는 화면이 떠요', TEXT)
    DocumentResult(unit_key='IT-HW-001@v2.0/item:3.6', chunk_type='ITEM', doc_code='IT-HW-001',
                   title='업무 PC 기본 장애 대응 가이드', version='v2.0', location='3.6', heading_path='',
                   text=TEXT, chunks=(ChunkHit(1, 1, 0.8),), unit_score=0.8, score_type='cosine:test',
                   view_scope='ALL', transfer_policy='ALLOWED', evidence=ev)


def test_build_query_joins_user_messages_in_order():
    assert build_query(['VPN이 안 돼요', ' 691번이요 ']) == 'VPN이 안 돼요\n691번이요'


def test_build_query_drops_oldest_when_long():
    q = build_query(['가' * 10, '나' * 10, '다' * 10], max_chars=21)
    assert q == '나' * 10 + '\n' + '다' * 10
    assert build_query(['라' * 30], max_chars=21) == '라' * 21      # 최근 글 하나가 길면 앞부분만


@pytest.mark.parametrize('msgs', [[], ['', '  ']])
def test_build_query_needs_user_text(msgs):
    with pytest.raises(ValueError):
        build_query(msgs)

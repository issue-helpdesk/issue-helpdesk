"""원천 JSON을 다시 만드는 순서. 원천을 손으로 고친 뒤에는 build.py만 실행하면 된다.

  1. author_sw.py, author_acs.py  직접 작성한 문서(SW·ACS·AI 정책)를 원천으로 쓴다
  2. normalize.py                 공통 기준(문구·버전·열람 등급·처리 구분·문의처·상태)을 모든 원천에 적용한다
  3. consolidate.py               분류 사이 중복·경계 정리와 참조 수정을 적용한다
  4. author_std.py                공통 기준 문서(문서 목록 포함)를 쓴다
  5. normalize.py                 다시 적용한다 (문서명·바로가기 동기화)

convert_accsec.py·convert_docx.py는 팀원 원본을 처음 옮길 때 한 번만 쓴 스크립트다.
다시 실행하면 consolidate 이후 손으로 고친 내용이 지워지므로 실행하지 않는다.
"""
import runpy

for step in ['author_sw', 'author_acs', 'normalize', 'consolidate', 'author_std', 'author_std', 'normalize']:
    print('==', step)
    runpy.run_module(step, run_name='__main__')

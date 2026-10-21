"""분류 사이 중복·경계 정리와 잘못된 참조 수정 (팀원 변환본 대상). normalize 뒤에 실행한다. 여러 번 실행해도 결과가 같다.

정리 기준과 결과는 IT-STD-002 3장 '중복 주제 정리'에 적었다.
"""
import glob
import json
import os

from model import *

# (문서 번호, 바꿀 글, 바꿀 값) — 문서 JSON 안의 글자를 그대로 바꾼다
TEXT_EDITS = [
    # 평가 정답셋(EV-043)과 같은 표현
    ('IT-SYS-003', '전 부서의 메일 송수신이 멈췄다.', '회사 전체에서 메일을 보내지도 받지도 못한다.'),
    # 잘못된 항목 참조
    ('IT-HW-001', 'IT-NET-002 3.5', 'IT-NET-002 3.7'),
    ('IT-SYS-002', 'IT-NET-002 3.5', 'IT-NET-002 3.7'),
    ('IT-SYS-005', 'IT-NET-002 3.5', 'IT-NET-002 3.7'),
    ('IT-SYS-008', 'IT-SW-003 3.5', 'IT-SW-003 3.6'),
    # 메일: 서비스(SYS-004)와 PC 메일 프로그램(SW-003 3.7) 경계
    ('IT-SYS-004', '메일 프로그램 실행 오류는 IT-SW-003,', 'PC에 설치한 메일 프로그램 오류는 IT-SW-003 3.7,'),
    ('IT-SYS-004', '메일 프로그램이 열리지 않거나 느리면 IT-SW-003을 본다.', 'PC에 설치한 메일 프로그램이 열리지 않거나 느리면 IT-SW-003 3.7을 본다.'),
    # 보안 프로그램 격리: 기준 문서는 IT-SEC-002
    ('IT-SEC-002', 'IT-SW-003 3장 4) 보안 프로그램의 파일 격리와 같은 기준입니다. 파일 이름·경로를 적어 챗봇으로 예외 검토를 요청합니다.',
     '이 문서 3.2를 따릅니다. 파일 이름·경로를 적어 챗봇으로 예외 검토를 요청합니다. 보안 프로그램을 끄고 실행하지 않습니다.'),
    # 생성형 AI: 미승인 도구 검토는 SW 설치 요청의 보안 검토 절차로
    ('IT-SEC-004', 'ITssue 챗봇으로 도구 검토를 요청합니다.', 'IT-SW-001 3.5에 따라 설치 요청을 내면 정보보안팀이 보안 검토를 합니다.'),
    # 공유 드라이브 액세스 거부: 팀 전체는 SYS-006, 개인 권한은 ACS
    ('IT-SYS-006', '혼자만 안 되면 권한 신청 대상일 수 있습니다. IT-ACS-001을 봅니다.',
     '혼자만 안 되면 개인 권한 문제입니다. IT-ACS-001 3.4를 보고, 부서를 옮긴 뒤라면 IT-ACS-003 3.2를 봅니다.'),
    ('IT-SYS-006', '혼자만 안 되면 권한 신청 대상일 수 있습니다(IT-ACS-001).', '혼자만 안 되면 개인 권한 문제입니다 (IT-ACS-001 3.4).'),
    # 개발 서버: 권한은 ACS-002, 서버 장애는 SYS-008
    ('IT-SYS-008', '나만 접속이 안 되면 계정·권한 문제일 수 있다. IT-ACS-002를 본다.', '나만 접속이 안 되면 계정·권한 문제일 수 있다. IT-ACS-002 3.4를 본다.'),
]

# (문서 번호, 항목 번호, 넣을 item, 넣을 위치: 'end' | 'before_cols')
INSERTS = [
    ('IT-HW-002', '3.7', note('info', '퇴사할 때 계정은 퇴사일 18시에 자동 비활성화되고(IT-ACS-003 3.3), 유료 SW 라이선스도 함께 회수됩니다(IT-SW-002 3.7). 반납 전에 업무 파일을 팀 공유 드라이브로 옮깁니다.'), 'end'),
    ('IT-SYS-008', '3.1', note('info', '혼자만 접속이 안 되고 다른 팀원은 되면 서버 장애가 아니라 권한 문제일 수 있습니다. IT-ACS-002 3.4를 봅니다.'), 'end'),
    ('IT-NET-001', '3.2', note('info', '사무실에서 VPN 없이도 화상회의가 끊기면 IT-NET-002 3.7, 회의 앱 자체 문제(소리·카메라·앱 종료)는 IT-SYS-005를 봅니다.'), 'end'),
]


# FAQ 원본이 없는 문서의 4장. 본문 내용을 문답으로 다시 쓴 것이다 (FAQ 데이터에는 없음).
FAQ_FILL = {
    'IT-SYS-002': [
        ['업무 시스템이 느린데 저만 그런지 어떻게 알 수 있나요?', '같은 팀 동료에게 같은 화면이 느린지 물어봅니다. 나만 느리면 3.1의 PC 기본 조치를, 여러 명이 느리면 느려진 시각과 화면 이름을 적어 ITssue 챗봇에 알립니다.'],
        ['오후만 되면 PMS가 느려요. 기다리면 되나요?', '사용자가 몰리는 시간대 문제일 수 있습니다. 느려지는 시각과 화면을 적어 알려 주시면 담당자가 처리 용량을 확인합니다 (3.2).'],
        ['팀 전체가 업무 시스템을 아예 쓸 수 없어요.', '느린 것이 아니라 장애입니다. IT-SYS-003을 따르고 IT 헬프데스크(내선 1000)에 알립니다.'],
    ],
    'IT-SYS-008': [
        ['개발 서버에 혼자만 접속이 안 돼요.', '다른 팀원은 접속된다면 서버 장애가 아니라 계정·권한 문제일 수 있습니다. IT-ACS-002 3.4를 봅니다.'],
        ['배포가 막혔는데 서버를 직접 다시 시작해도 되나요?', '아니요. 장애 중에 서버 설정을 바꾸거나 다시 시작하지 않습니다. 서버 이름과 시작 시각을 적어 신고하면 담당자가 복구합니다 (3.1).'],
        ['빌드에 제 개인 토큰을 넣으면 바로 될 것 같은데요?', '개인 토큰을 빌드 설정에 넣지 않습니다. 로그를 첨부해 신고하면 담당자가 연동 토큰을 다시 발급합니다 (3.2).'],
    ],
}


def path_of(no):
    return glob.glob(os.path.join(SOURCE, '*', no + '.json'))[0]


def main():
    n = 0
    for no, a, b in TEXT_EDITS:
        p_ = path_of(no)
        s = open(p_, encoding='utf-8').read()
        if b in s and a not in s.replace(b, ''):
            continue
        if a not in s:
            print('찾지 못함:', no, a[:40])
            continue
        s = s.replace(a, b) if a not in b else s.replace(b, '\0').replace(a, b).replace('\0', b)
        open(p_, 'w', encoding='utf-8').write(s)
        n += 1
    for no, sec, it, where in INSERTS:
        doc = load(path_of(no))
        for ch in doc['chapters']:
            for s in ch['sections']:
                if s['no'] == sec and it not in s['items']:
                    if where == 'end':
                        s['items'].append(it)
                    n += 1
        save(doc)
    for no, rows in FAQ_FILL.items():
        doc = load(path_of(no))
        for ch in doc['chapters']:
            if ch['title'] == '자주 묻는 질문' and any(it['t'] == 'p' and 'FAQ는 없음' in it['text'] for it in ch['items']):
                ch['items'] = [qa(rows)]
                n += 1
        save(doc)
    print(n, 'edits')


if __name__ == '__main__':
    main()

/**
 * 세부 유형 (inquiry_types) 시연 데이터와 키워드 판정.
 * 코드는 데이터셋 시나리오 ID(예: NET-02)와 같다. 실제 API 에서는 서버가 판단해 inquiryTypeCode 로 준다.
 * 위에서부터 차례로 맞는지 보고, 맞는 것이 없으면 null (화면은 "담당자가 확인해요"로 보여 준다).
 */
import type { CategoryCode } from '../chatTypes'

interface TypeRule {
  code: string
  name: string
  re: RegExp
}

const RULES: Record<CategoryCode, TypeRule[]> = {
  ACC: [
    { code: 'ACC-04', name: '통합 로그인(SSO) 장애', re: /SSO|통합 ?로그인|로그인.*(안|불가|오류)/i },
    { code: 'ACC-03', name: '2단계 인증(MFA)', re: /MFA|OTP|2단계|인증 ?앱/i },
    { code: 'ACC-02', name: '계정 잠금', re: /잠[겼금]/ },
    { code: 'ACC-01', name: '비밀번호 만료·초기화', re: /비밀번호|패스워드/ },
  ],
  ACS: [
    { code: 'ACS-02', name: '부서 이동·퇴사 권한 변경', re: /이동|퇴사|발령/ },
    { code: 'ACS-01', name: '시스템·폴더 접근권한 신청', re: /권한|접근/ },
  ],
  NET: [
    { code: 'NET-03', name: 'VPN 전사 장애', re: /(전사|전체|모두|다들).*(VPN|접속)|VPN.*(전사|전체)/i },
    { code: 'NET-02', name: 'VPN 접속 불가(개인)', re: /VPN/i },
    { code: 'NET-01', name: '사내 Wi-Fi', re: /와이파이|Wi-?Fi/i },
    { code: 'NET-05', name: '유선 LAN', re: /랜선|유선|LAN/i },
    { code: 'NET-04', name: '인터넷 속도 저하', re: /인터넷|느려|속도/ },
  ],
  SW: [
    { code: 'SW-06', name: '메일 프로그램 오류', re: /메일 ?프로그램|아웃룩|Outlook/i },
    { code: 'SW-05', name: '개발도구 인증서 오류', re: /인증서|개발 ?도구/ },
    { code: 'SW-03', name: '오피스 문서 오류', re: /Excel|엑셀|Word|워드|PowerPoint|오피스|문서/i },
    { code: 'SW-02', name: '라이선스', re: /라이선스/ },
    { code: 'SW-01', name: 'SW 설치 요청', re: /설치|프로그램/ },
  ],
  HW: [
    { code: 'HW-02', name: '부팅 불가·블루스크린', re: /부팅|블루스크린|켜지지/ },
    { code: 'HW-07', name: '인쇄 불가', re: /프린터|인쇄|복합기/ },
    { code: 'HW-03', name: '모니터·도킹', re: /모니터|도킹|화면/ },
    { code: 'HW-01', name: 'PC 속도 저하', re: /느려|속도|버벅/ },
    { code: 'HW-04', name: '장비 파손·수리', re: /파손|고장|수리|깨졌/ },
  ],
  SYS: [
    { code: 'SYS-09', name: '메일 서버 장애', re: /메일.*(전사|전체|서버)/ },
    { code: 'SYS-06', name: '메일 수신 불가', re: /메일/ },
    { code: 'SYS-02', name: 'ERP 오류', re: /ERP/i },
    { code: 'SYS-01', name: '전자결재', re: /결재/ },
    { code: 'SYS-04', name: '인사·근태', re: /인사|근태/ },
    { code: 'SYS-10', name: '메신저·화상회의', re: /메신저|화상|Teams|줌|Zoom/i },
    { code: 'SYS-13', name: '공유 드라이브 접속 장애', re: /공유 ?드라이브|파일 ?서버/ },
    { code: 'SYS-15', name: '개발 서버·DB', re: /개발 ?서버|DB/i },
  ],
  SEC: [
    { code: 'SEC-04', name: '피싱 대량 유입', re: /(대량|여러|다수).*(피싱|메일)/ },
    { code: 'SEC-01', name: '피싱 메일 신고', re: /피싱|스팸|수상한 ?메일/ },
    { code: 'SEC-06', name: '계정 도용 의심', re: /도용|탈취/ },
    { code: 'SEC-02', name: '악성코드·보안 알림', re: /악성|백신|바이러스|EDR/i },
    { code: 'SEC-05', name: '시스템 무단 접근·침해 의심', re: /무단|침해/ },
    { code: 'SEC-07', name: '웹사이트 차단 해제', re: /차단/ },
    { code: 'SEC-03', name: '매체·반출 예외', re: /USB|반출|매체/i },
  ],
}

/** 분류와 문장으로 세부 유형을 판단한다. 알 수 없으면 null */
export function detectInquiryType(category: CategoryCode | null, text: string): { code: string; name: string } | null {
  if (!category) return null
  const hit = RULES[category].find((r) => r.re.test(text))
  return hit ? { code: hit.code, name: hit.name } : null
}

/**
 * 서비스 권한(serviceRole)별 설정.
 * 라우터와 화면이 서로를 가져오다 순환 참조가 생기지 않도록 별도 파일로 분리했다.
 */
import type { ServiceRole } from '../api/types'

/** 역할별 로그인 직후 첫 화면 (프로토타입과 같음: 문의자=새 문의, 담당자=처리할 문의, 관리자=대시보드) */
export const HOME_BY_ROLE: Record<ServiceRole, string> = { EMPLOYEE: '/new', AGENT: '/my', ADMIN: '/dash' }

/** 화면에 보여 줄 역할 이름 */
export const ROLE_LABEL: Record<ServiceRole, string> = { EMPLOYEE: '문의자', AGENT: '담당자', ADMIN: '관리자' }

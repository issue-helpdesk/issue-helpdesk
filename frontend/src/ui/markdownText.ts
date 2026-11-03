/** 마크다운 본문 보정 (렌더러가 쓴다) */
/** 줄바꿈이 없는 본문에서 제목·목록 앞에 줄바꿈을 넣는다 */
export function restoreBreaks(text: string): string {
  if (/\n/.test(text)) return text
  return text
    .replace(/\s+(#{1,6})\s+/g, '\n$1 ')
    .replace(/([.!?다요음함임니까])\s+-\s+(?=\S)/g, '$1\n- ')
    .replace(/\s+-\s+(?=[가-힣A-Za-z0-9[(])/g, '\n- ')
    .replace(/\s+1\.\s+(?=[가-힣A-Za-z[(])/g, '\n1. ')
    .replace(/([.!?다요음함임니까])\s+(\d{1,2})\.\s+(?=\S)/g, '$1\n$2. ')
    .replace(/\s+(\[(?:그림|표)\])/g, '\n$1')
    .trim()
}


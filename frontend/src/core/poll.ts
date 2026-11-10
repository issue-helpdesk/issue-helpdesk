/**
 * 서버를 주기적으로 다시 읽을 때 쓰는 공통 도구.
 * 탭이 가려져 있으면(다른 탭을 보고 있거나 창이 최소화) 요청을 멈추고, 다시 보이면 곧바로 한 번 읽은 뒤 이어간다.
 * 돌려주는 함수를 부르면 멈춘다.
 */
export function visiblePoll(fn: () => void, ms: number, resume: () => void = fn): () => void {
  let timer: ReturnType<typeof setInterval> | undefined
  const start = () => {
    timer ??= setInterval(fn, ms)
  }
  const stop = () => {
    if (timer !== undefined) clearInterval(timer)
    timer = undefined
  }
  const onVisible = () => {
    if (document.visibilityState === 'hidden') return stop()
    resume()
    start()
  }
  if (document.visibilityState !== 'hidden') start()
  document.addEventListener('visibilitychange', onVisible)
  return () => {
    stop()
    document.removeEventListener('visibilitychange', onVisible)
  }
}

/**
 * 주기 조회를 하는 화면끼리 서로 알리는 표시.
 * - chatViews: 대화 화면이 열려 있는 수. 대화 화면이 자기 문의를 직접 읽고 있으면 사이드바의 목록 조회는 드물게 한다.
 * - listLoaders: 사이드바 문의 목록을 지금 바로 다시 읽는 함수. 대화 화면에서 상태가 바뀐 걸 알았을 때 한 번 불러 준다.
 */
export const pollHints = { chatViews: 0, listLoaders: new Set<() => void>() }

/** 문의 목록(사이드바)을 지금 한 번 다시 읽게 한다 */
export const refreshInquiryList = () => pollHints.listLoaders.forEach((f) => f())

/**
 * 서버를 주기적으로 다시 읽을 때 쓰는 공통 도구.
 * 탭이 가려져 있으면(다른 탭을 보고 있거나 창이 최소화) 요청을 멈추고, 다시 보이면 곧바로 한 번 읽은 뒤 이어간다.
 * 돌려주는 함수를 부르면 멈춘다.
 */
export function visiblePoll(fn: () => void, ms: number): () => void {
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
    fn()
    start()
  }
  if (document.visibilityState !== 'hidden') start()
  document.addEventListener('visibilitychange', onVisible)
  return () => {
    stop()
    document.removeEventListener('visibilitychange', onVisible)
  }
}

/**
 * 가이드 그림 한 장 (출처 미리보기의 `[그림] 설명` 줄). 서버(DC-11)에서 인증을 붙여 받아 blob 주소로 보여 준다.
 * 받는 동안과 못 받았을 때(404·권한·네트워크)는 지금까지처럼 설명 상자를 그대로 둔다. 창이 닫히면 blob 주소를 풀어 준다.
 */
import { useEffect, useState } from 'react'
import type { GuideImageRef } from '../api/chatTypes'
import { requestBlob } from '../core/apiClient'

/** 그림 키(`SW/sw001_portal_home.png`)를 주소로: 칸마다 인코딩하되 `/` 는 그대로 둔다 */
const pathOf = (key: string) => `/guide-images/${key.split('/').map(encodeURIComponent).join('/')}`

export function GuideFigure({ image, label }: { image: GuideImageRef; label: string }) {
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    let url: string | null = null
    requestBlob(pathOf(image.key)).then((b) => {
      if (!alive || !b) return
      url = URL.createObjectURL(b)
      setSrc(url)
    })
    return () => {
      alive = false
      if (url) URL.revokeObjectURL(url)
    }
  }, [image.key])

  if (!src)
    return (
      <div className="fig" role="img" aria-label={`${label}: ${image.caption || '설명 없음'}`}>
        <b>{label}</b>
        {image.caption}
      </div>
    )
  return (
    <figure className="figimg">
      <img src={src} alt={image.caption || '가이드 그림'} />
      {image.caption && <figcaption>{image.caption}</figcaption>}
    </figure>
  )
}

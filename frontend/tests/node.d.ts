/**
 * 테스트에서 저장소 안의 파일(서버 시드 CSV)을 읽는 데 쓰는 최소한의 Node 선언.
 * @types/node 를 새로 설치하지 않으려고 필요한 것만 적었다. (Vite 의 ?raw 가져오기는 프론트 폴더 밖 파일을 막는다)
 */
declare module 'node:fs' {
  export function readFileSync(path: string, encoding: 'utf-8'): string
}
declare module 'node:path' {
  export function resolve(...parts: string[]): string
}
declare const __dirname: string

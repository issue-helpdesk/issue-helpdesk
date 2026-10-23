# 임베딩 모델 (WBS M3-1-2)

KURE-v1과 BGE-M3를 **로컬에서** 실행합니다. 문서·질문을 외부 임베딩 서비스로 보내지 않습니다 (설계서 4장).

| 파일 | 내용 |
|---|---|
| [`models.py`](models.py) | 모델 목록(저장소·고정 리비전·받을 파일), 입력 처리 설정, 임베딩 이름 |
| [`embedder.py`](embedder.py) | `Embedder` — 검색·적재 코드는 이것만 쓴다 |
| [`__main__.py`](__main__.py) | 받기(`download`)·확인(`check`)·시험(`smoke`) 명령 |

## 설치

```bash
# Windows·macOS
pip install -r requirements-embedding.txt
# Linux 서버(EC2): CPU용 torch 를 먼저 설치한다. 그냥 설치하면 GPU용(수 GB)이 깔린다
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-embedding.txt
```

## 모델 받기·확인·시험 (backend 폴더에서)

```bash
python -m app.rag.embedding download      # 두 모델 약 4.6GB. 고정 리비전으로 받는다
python -m app.rag.embedding check         # 파일이 다 있는지만
python -m app.rag.embedding smoke         # 두 모델을 열어 샘플 임베딩·메모리·속도·FAQ 적중을 잰다
```

- 모델 폴더는 환경 변수 `EMBEDDING_MODEL_DIR`로 정합니다. 기본은 저장소 바로 옆 `models/`입니다 (예: `C:\workspace\models`).
- 모델 파일은 저장소에 넣지 않습니다.
- `smoke`의 FAQ 시험은 `faq.csv`를 씁니다. 평가셋(`eval_inquiries.csv`)은 쓰지 않습니다.

## 코드에서 쓰기

```python
from app.rag.embedding import Embedder

emb = Embedder('kure-v1')                 # 또는 'bge-m3'. 폴더에서만 읽고 인터넷에 접속하지 않는다
emb.model_id                              # 'kure-v1@8b418a5/v1' → document_chunk_embeddings.model
emb.embed_documents([c.text for c in chunks])   # 적재 (M2-2-1)
emb.embed_query('노트북이 안 켜져요')       # 검색 (M3-2-2)
```

- 질문과 문서에 같은 처리를 합니다. 두 모델 모두 질문 앞에 지시문을 붙이지 않습니다.
- 벡터는 길이 1로 맞춥니다. 그래서 내적이 곧 코사인 유사도입니다.
- 모델을 여는 데 10초 이상 걸립니다. 서버에서는 시작할 때 한 번만 열고 계속 씁니다.

## 입력 처리 설정과 임베딩 이름

| 설정 | 값 | 이유 |
|---|---|---|
| 최대 입력 길이 | 1024 토큰 | 가이드 청크 717개 중 가장 긴 것이 818토큰입니다 (KURE 토크나이저, 2026-10-22 `dataset/guides` 기준). 512로 두면 95개(13%)의 뒷부분이 잘립니다 |
| 정규화 | 켬 | 코사인 유사도 |
| 리비전 | KURE-v1 `8b418a5`, BGE-M3 `5617a9f` | 모두 같은 가중치를 쓰도록 고정 |

임베딩 이름(`model_id`)은 `이름@리비전/입력 처리` 형식입니다 (청크_메타데이터.md 5장). 위 설정을 바꾸면 `models.py`의 `PREPROCESS`를 올립니다. 그러면 이름이 바뀌어 예전 벡터와 섞이지 않고, 다시 임베딩해야 할 대상이 구분됩니다.

## 시험 결과 (2026-10-20, CPU 노트북 i5-1335U·32GB, 모델마다 별도 프로세스)

| 모델 | 여는 시간 | 질문 1개 | FAQ Top1 | FAQ Top3 | MRR | 메모리 최대 | 가이드 청크 전체 |
|---|---|---|---|---|---|---|---|
| KURE-v1 | 11.5초 | 107ms | 82% | 92% | 0.883 | 3.0GB | 717개 약 14.6분 |
| BGE-M3 | 10.0초 | 111ms | 72% | 95% | 0.836 | 2.1GB | 717개 약 14.2분 |

- FAQ 적중은 FAQ 질문 40개로 자기 답변을 찾게 한 값입니다. **모델 선택 근거가 아닙니다.** 선택은 M3-2-1에서 Golden Set으로 합니다.
- 가이드 청크 시간은 앞 64개로 잰 값을 전체 수로 늘린 추정입니다. 적재는 한 번만 하면 되므로 노트북에서 미리 만들어 DB에 넣습니다.

## 서버에 올릴 때 (EC2)

- **메모리가 4GB 이상 필요합니다.** 모델 하나를 열면 KURE-v1은 약 3GB, BGE-M3는 약 2GB를 씁니다. 메모리 1GB인 프리 티어 인스턴스(t2/t3.micro)에서는 뜨지 않습니다.
- **서버에는 선택한 모델 하나만 받습니다.** `python -m app.rag.embedding download --model kure-v1`. 디스크는 약 2.3GB를 씁니다.
- **서버는 질문 임베딩만 계산합니다.** 가이드 문서 임베딩은 미리 만들어 Supabase에 넣어 둡니다.
- **시연 예비**: 노트북에서 백엔드를 실행할 때는 이 노트북의 `models/` 폴더를 그대로 씁니다.

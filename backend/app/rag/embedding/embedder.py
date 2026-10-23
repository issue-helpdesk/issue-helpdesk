"""로컬 임베딩 모델 (KURE-v1 / BGE-M3). 검색·적재 코드는 이 클래스만 쓴다 — 모델 교체는 이름만 바꾼다."""
import os
from pathlib import Path

from app.rag.embedding.models import (DEFAULT_MODEL, MAX_SEQ_LENGTH, MODELS, NORMALIZE, check_files, model_dir,
                                      model_id)


class Embedder:
    """문장 → 1024차원 단위 벡터.

    질문과 문서에 같은 처리를 한다 (두 모델 모두 질문 앞에 지시문을 붙이지 않는다).
    인터넷에 접속하지 않고 로컬 폴더만 읽는다. 모델 파일은 python -m app.rag.embedding download 로 받는다.
    """

    def __init__(self, key: str = DEFAULT_MODEL, base: Path | None = None, device: str = 'cpu'):
        if key not in MODELS:
            raise ValueError(f'모르는 임베딩 모델: {key} (가능: {", ".join(MODELS)})')
        problems = check_files(key, base)
        if problems:
            raise FileNotFoundError(f'{key} 모델 파일이 없거나 덜 받아졌습니다:\n  ' + '\n  '.join(problems) +
                                    '\n→ 저장소 루트에서: cd backend && python -m app.rag.embedding download')
        os.environ.setdefault('HF_HUB_OFFLINE', '1')            # sentence_transformers 를 불러오기 전에
        from sentence_transformers import SentenceTransformer

        self.key = key
        self.model_id = model_id(key)                          # document_chunk_embeddings.model 값
        self.dim = MODELS[key]['dim']
        self._model = SentenceTransformer(str((base or model_dir()) / MODELS[key]['folder']), device=device)
        self._model.max_seq_length = MAX_SEQ_LENGTH

    def embed_documents(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        """청크 본문들 → 벡터들. 적재(M2-2-1)에서 쓴다. 입력 순서와 같은 순서로 돌려준다."""
        vecs = self._model.encode(texts, batch_size=batch_size, normalize_embeddings=NORMALIZE,
                                  convert_to_numpy=True, show_progress_bar=False)
        return vecs.tolist()

    def embed_query(self, text: str) -> list[float]:
        """질문 하나 → 벡터. 검색(M3-2-2)에서 쓴다."""
        return self.embed_documents([text], batch_size=1)[0]

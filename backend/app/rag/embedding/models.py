"""임베딩 모델 목록 (WBS M3-1-2). 두 모델 모두 공개 저장소·MIT 라이선스, 1024차원."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]                 # 저장소 루트

# 입력 처리 설정. 바꾸면 PREPROCESS 를 올린다 (임베딩 model 값이 바뀌어 예전 벡터와 섞이지 않는다)
MAX_SEQ_LENGTH = 1024    # 가이드 청크 717개 중 최장 818토큰 (KURE 토크나이저). 512면 95개(13%)가 잘린다
NORMALIZE = True         # 단위 벡터로 만들어 내적 = 코사인 유사도
PREPROCESS = 'v1'

# 받을 파일만 적는다 (bge-m3 저장소의 onnx/ 사본 2.27GB 는 받지 않는다). revision 을 고정해 모두 같은 가중치를 쓴다
MODELS = {
    'kure-v1': {
        'repo': 'nlpai-lab/KURE-v1',
        'revision': '8b418a58414668e75532ed045c22d9ca018ae2b2',
        'folder': 'KURE-v1',
        'dim': 1024,
        'files': ['model.safetensors', 'config.json', 'tokenizer.json', 'tokenizer_config.json',
                  'special_tokens_map.json', 'modules.json', 'sentence_bert_config.json',
                  'config_sentence_transformers.json', '1_Pooling/config.json'],
        'sizes': {'model.safetensors': 2_271_064_456, 'tokenizer.json': 17_083_053},
    },
    'bge-m3': {
        'repo': 'BAAI/bge-m3',
        'revision': '5617a9f61b028005a4858fdac845db406aefb181',
        'folder': 'bge-m3',
        'dim': 1024,
        'files': ['pytorch_model.bin', 'config.json', 'tokenizer.json', 'tokenizer_config.json',
                  'special_tokens_map.json', 'sentencepiece.bpe.model', 'modules.json', 'sentence_bert_config.json',
                  'config_sentence_transformers.json', '1_Pooling/config.json'],
        'sizes': {'pytorch_model.bin': 2_271_145_830, 'tokenizer.json': 17_098_108},
    },
}
DEFAULT_MODEL = 'kure-v1'


def model_dir() -> Path:
    """모델 폴더들이 있는 곳. 기본은 저장소 바로 옆 models/ (예: C:\\workspace\\models)."""
    return Path(os.environ.get('EMBEDDING_MODEL_DIR') or ROOT.parent / 'models').expanduser().resolve()


def model_id(key: str) -> str:
    """document_chunk_embeddings.model 에 넣는 값: 이름@리비전/입력 처리 (청크_메타데이터.md 5장)."""
    return f"{key}@{MODELS[key]['revision'][:7]}/{PREPROCESS}"


def check_files(key: str, base: Path | None = None) -> list[str]:
    """모델 폴더에 필요한 파일이 다 있고 큰 파일 크기가 맞는지. 문제를 문장 목록으로 돌려준다."""
    spec = MODELS[key]
    folder = (base or model_dir()) / spec['folder']
    problems = [f'없음: {folder / f}' for f in spec['files'] if not (folder / f).is_file()]
    for f, size in spec['sizes'].items():
        p = folder / f
        if p.is_file() and p.stat().st_size != size:
            problems.append(f'크기 다름 (받다가 끊김): {p} {p.stat().st_size:,}B, 기대 {size:,}B')
    return problems

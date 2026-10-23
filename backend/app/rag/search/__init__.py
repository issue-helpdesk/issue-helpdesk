"""검색 (WBS M3). 검색 요청·결과 형식(M3-1-1), 근거 문장 고르기·검색어 만들기. 설명은 README.md."""
from app.rag.search.evidence import build_query, pick_evidence
from app.rag.search.result import (DEFAULT_THRESHOLD, DEFAULT_TOP_K, MAX_EVIDENCE, ChunkHit, DocumentResult,
                                   LegacyResult, SearchRequest, SearchResponse, message_source_rows, visible_scopes)

__all__ = ['DEFAULT_THRESHOLD', 'DEFAULT_TOP_K', 'MAX_EVIDENCE', 'ChunkHit', 'DocumentResult', 'LegacyResult',
           'SearchRequest', 'SearchResponse', 'build_query', 'message_source_rows', 'pick_evidence', 'visible_scopes']

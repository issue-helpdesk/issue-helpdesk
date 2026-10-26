"""검색 (WBS M3). 지금은 검색 요청·결과 형식만 있다 (M3-1-1). 형식 설명은 README.md."""
from app.rag.search.result import (DEFAULT_THRESHOLD, DEFAULT_TOP_K, MAX_EVIDENCE, ChunkHit, DocumentResult,
                                   LegacyResult, SearchRequest, SearchResponse, message_source_rows, visible_scopes)

__all__ = ['DEFAULT_THRESHOLD', 'DEFAULT_TOP_K', 'MAX_EVIDENCE', 'ChunkHit', 'DocumentResult', 'LegacyResult',
           'SearchRequest', 'SearchResponse', 'message_source_rows', 'visible_scopes']

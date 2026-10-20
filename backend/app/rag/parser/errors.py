"""파서 오류. 업로드 API가 사용자에게 그대로 보여 줄 수 있는 메시지와 원인 코드를 함께 준다."""
from __future__ import annotations

# 원인 코드 → 사용자 안내
REASONS = {
    'not_found': '파일을 찾을 수 없습니다.',
    'unsupported': '지원하지 않는 파일 형식입니다.',
    'empty': '빈 파일입니다.',
    'corrupt': '파일이 손상되었거나 확장자와 실제 형식이 다릅니다.',
    'encrypted': '암호가 걸린 문서입니다. 암호를 풀고 다시 올려 주세요.',
    'encoding': '글자 인코딩을 알 수 없습니다. UTF-8로 저장해 다시 올려 주세요.',
    'no_text': '문서에서 글자를 찾지 못했습니다.',
    'failed': '문서를 읽는 중 오류가 났습니다.',
}

# 지원하지 않지만 자주 올라오는 형식 → 변환 안내
CONVERT_HINT = {
    '.hwp': '한글에서 [다른 이름으로 저장] → DOCX 또는 PDF로 저장해 올려 주세요.',
    '.hwpx': '한글에서 [다른 이름으로 저장] → DOCX 또는 PDF로 저장해 올려 주세요.',
    '.doc': 'Word에서 DOCX로 저장해 올려 주세요.',
    '.ppt': 'PowerPoint에서 PPTX로 저장해 올려 주세요.',
    '.xls': '표 문서는 가이드로 등록하지 않습니다. 내용을 DOCX로 옮겨 올려 주세요.',
    '.xlsx': '표 문서는 가이드로 등록하지 않습니다. 내용을 DOCX로 옮겨 올려 주세요.',
    '.rtf': 'Word에서 DOCX로 저장해 올려 주세요.',
    '.odt': 'DOCX로 저장해 올려 주세요.',
    '.png': '그림 파일은 글자를 읽을 수 없습니다. 원본 문서(DOCX·PDF)를 올려 주세요.',
    '.jpg': '그림 파일은 글자를 읽을 수 없습니다. 원본 문서(DOCX·PDF)를 올려 주세요.',
}


class ParseError(Exception):
    """reason: REASONS 의 키. detail: 내부 원인(로그용)."""

    def __init__(self, reason: str, path: str = '', detail: str = '', hint: str = ''):
        self.reason = reason if reason in REASONS else 'failed'
        self.path = path
        self.detail = detail
        self.hint = hint
        super().__init__(self.message)

    @property
    def message(self) -> str:
        msg = REASONS[self.reason]
        return f'{msg} {self.hint}'.strip()

    def __str__(self) -> str:
        base = f'[{self.reason}] {self.message}'
        return f'{base} ({self.detail})' if self.detail else base

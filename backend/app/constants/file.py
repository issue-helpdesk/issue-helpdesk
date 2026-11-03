"""문서 파일 업로드 기준 (DC-07)."""

MAX_DOCUMENT_FILE_MB = 20           # 파일 크기 제한. 서버 판단은 이 값 하나로 한다
FORM_MARGIN_BYTES = 1024 * 1024     # 요청에는 파일 말고 폼 값도 들어가므로 받는 양에 두는 여유
READ_SIZE_BYTES = 1024 * 1024       # 파일을 저장할 때 한 번에 읽는 양
FILE_FORMATS = {                    # 확장자 → file_format
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".pptx": "PPTX",
    ".md": "MD",
    ".txt": "TEXT"
}

"""문서 파일 업로드 기준 (DC-07)."""

MAX_DOCUMENT_FILE_MB = 20           # 파일 크기 제한. 서버 판단은 이 값 하나로 한다
FORM_MARGIN_BYTES = 1024 * 1024     # 요청에는 파일 말고 폼 값도 들어가므로 받는 양에 두는 여유
READ_SIZE_BYTES = 1024 * 1024       # 파일을 저장할 때 한 번에 읽는 양
TEMP_FILE_MAX_AGE_HOURS = 1         # 서버 시작 때 이보다 오래된 임시 파일을 지운다
FILE_FORMATS = {                    # 확장자 → file_format
    ".pdf": "PDF",
    ".docx": "DOCX",
    ".pptx": "PPTX",
    ".md": "MD",
    ".txt": "TEXT"
}
ZIP_REQUIRED_MEMBER = {             # 이 파일이 있어야 그 형식이다
    ".docx": "word/document.xml",
    ".pptx": "ppt/presentation.xml"
}   
TEXT_SUFFIXES = {".md", ".txt"}     # 글자 파일로 검사하는 확장자
TEMP_SUFFIX = ".part"               # 받는 중인 임시 파일

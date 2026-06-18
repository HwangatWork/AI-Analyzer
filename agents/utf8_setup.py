# -*- coding: utf-8 -*-
"""
Windows cp949 환경에서 한글 UnicodeEncodeError 방지 — agents/*.py 공통 임포트.

신규 Agent 작성 시 반드시 아래 한 줄을 최상단 임포트에 포함:
    import utf8_setup  # noqa: F401

이 파일의 임포트 사이드이펙트로 sys.stdout/stderr가 UTF-8로 강제 설정됨.
-X utf8 플래그 없이 직접 실행할 때도 한글 출력이 안전하게 동작.
"""
import io
import sys

if hasattr(sys.stdout, "buffer") and sys.stdout.encoding.lower().replace("-", "") not in ("utf8",):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

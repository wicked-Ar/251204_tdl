# Archived TDL Generation Files

이 폴더는 **master_pipeline.py 실행에 필요하지 않은** TDL_generation 파일들을 보관하는 곳입니다.

## 보관된 파일들

### Interactive Scripts (대화형 스크립트)
- `interactive_converter.py` - 대화형 NL2TDL 변환기
- `interactive_full_pipeline.py` - 대화형 전체 파이프라인
- `interactive_pipeline_with_vision.py` - 비전 통합 대화형 파이프라인

### Utility Scripts (유틸리티)
- `capture_scene.py` - 화면 캡처 유틸리티

### Documentation (문서)
- `VISION_GUIDE.md` - 비전 기능 가이드

## 왜 보관되었나?

이 파일들은 독립적으로 실행되는 **테스트/개발용 스크립트**입니다.
`master_pipeline.py`는 이 파일들을 import하지 않으므로 실제 프로그램 실행에는 영향이 없습니다.

## master_pipeline.py가 실제로 사용하는 파일

```
TDL_generation/
├── nl2tdl_converter.py          ← 핵심: NL → TDL 변환
├── tdl_knowledge_base.py         ← 핵심: TDL 문법 지식
├── state_to_text_generator.py    ← 핵심: Ground Truth TSD 생성
└── __init__.py                   ← 모듈 초기화
```

## 복구 방법

필요 시 archived 폴더에서 상위 폴더로 이동하면 됩니다:

```bash
cd C:\Users\Smart CPS\Desktop\AYN\TDL_generation
mv archived/interactive_converter.py .
```

---

**정리 일자**: 2025-12-02
**정리 이유**: TDL_generation 폴더 간소화 (master_pipeline.py 실행에 필요한 파일만 유지)

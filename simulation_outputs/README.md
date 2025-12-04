# Simulation Outputs

이 폴더는 시뮬레이션 실행 결과물들을 체계적으로 저장하는 공간입니다.

## 폴더 구조

```
simulation_outputs/
├── videos/          # 시뮬레이션 비디오 녹화 파일 (.mp4)
└── logs/            # 실행 로그 및 디버그 정보 (향후 추가)
```

## 📹 Videos

모든 시뮬레이션 비디오는 자동으로 `videos/` 폴더에 저장됩니다.

### 파일명 형식

- **자동 생성**: `simulation_YYYYMMDD_HHMMSS.mp4`
  - 예: `simulation_20251128_183045.mp4`

- **사용자 지정**: 사용자가 지정한 파일명
  - 예: `test_panda.mp4`, `pick_apple_demo.mp4`

### 비디오 설정

- **해상도**: 1024x768 (H.264 호환)
- **프레임레이트**: 30 FPS
- **인코딩**: OpenCV VideoWriter (H.264 codec)

## 사용법

### 1. 자동 비디오 저장 (기본)

```python
from master_pipeline import MasterPipeline

pipeline = MasterPipeline()
result = pipeline.execute_full_pipeline(
    user_nl="Pick the apple",
    # output_video 지정 안 하면 자동 생성
)

# 비디오는 simulation_outputs/videos/simulation_YYYYMMDD_HHMMSS.mp4에 저장됨
print(result['simulation']['video_path'])
```

### 2. 사용자 지정 파일명

```python
result = pipeline.execute_full_pipeline(
    user_nl="Pick the apple",
    output_video="my_test.mp4"  # 파일명만 지정
)

# 비디오는 simulation_outputs/videos/my_test.mp4에 저장됨
```

### 3. PyBulletExecutor 직접 사용

```python
from pybullet_adapter import PyBulletExecutor

executor = PyBulletExecutor(render=True)

# 자동 생성
executor.execute_plan("panda pick apple", record_video=True)

# 사용자 지정
executor.execute_plan("panda pick apple", record_video=True, video_path="demo.mp4")

# 둘 다 simulation_outputs/videos/에 자동 저장됨
```

## 📝 Logs (향후 추가 예정)

향후 다음과 같은 로그 파일들이 저장될 예정입니다:

- `execution_log_YYYYMMDD_HHMMSS.txt`: 실행 상세 로그
- `robot_state_YYYYMMDD_HHMMSS.json`: 로봇 상태 스냅샷
- `error_log_YYYYMMDD_HHMMSS.txt`: 에러 및 경고 메시지

## 관리

### 오래된 파일 정리

비디오 파일은 용량이 크므로 주기적으로 정리하는 것을 권장합니다:

```bash
# 7일 이상 된 파일 삭제 (Linux/Mac)
find simulation_outputs/videos/ -name "*.mp4" -mtime +7 -delete

# Windows PowerShell
Get-ChildItem simulation_outputs\videos\*.mp4 | Where-Object {$_.LastWriteTime -lt (Get-Date).AddDays(-7)} | Remove-Item
```

### 중요한 파일 백업

중요한 데모 비디오는 별도로 백업하세요:

```bash
# 특정 파일 복사
cp simulation_outputs/videos/important_demo.mp4 ~/backup/

# 전체 폴더 백업
cp -r simulation_outputs/videos/ ~/backup/simulation_videos_$(date +%Y%m%d)/
```

## Git 관리

이 폴더는 `.gitignore`에 포함되어 있어 **Git에 커밋되지 않습니다**.

이유:
- 비디오 파일은 용량이 큼 (보통 400KB~1MB 이상)
- 자동 생성되는 임시 파일
- Git 저장소 크기를 불필요하게 증가시킴

중요한 데모 비디오는 별도의 스토리지에 보관하세요.

## 문제 해결

### 비디오가 저장되지 않음

1. OpenCV 설치 확인:
   ```bash
   pip install opencv-python
   ```

2. 폴더 권한 확인:
   - `simulation_outputs/videos/` 폴더에 쓰기 권한이 있는지 확인

3. 디스크 공간 확인:
   - 충분한 여유 공간이 있는지 확인 (최소 100MB 권장)

### 비디오 품질이 낮음

현재 설정은 30 FPS, 1024x768 해상도입니다. 더 높은 품질이 필요하면 `pybullet_adapter.py`의 비디오 설정을 수정하세요.

---

**마지막 업데이트**: 2025-11-28

# 신들의 사생활 빌더

정지 이미지 + 대본 → 나레이션 애니메이션 mp4 자동 조립기.

## 준비 (처음 한 번만)

```bash
sudo apt-get install -y ffmpeg fonts-noto-cjk        # mac: brew install ffmpeg
pip3 install fastapi uvicorn edge-tts pydub mutagen jinja2 python-multipart
```

## 목소리 고르기 (처음 한 번만)

```bash
python3 build.py --voice-sample
```

`output/voice_samples/` 에 남성·여성 음성이 하나씩 생깁니다.
마음에 드는 쪽 파일 이름에 적힌 목소리를 `config.json` 의 `tts_voice` 에 넣으세요.

- 남성 `ko-KR-InJoonNeural`
- 여성 `ko-KR-SunHiNeural`

## 매 편 작업

1. `input/images/` 에 `cut01.png` ~ `cut28.png` 를 넣습니다.
2. `input/script.json` 의 대본을 갈아 끼웁니다.
3. 실행:

```bash
python3 build.py --check     # 이미지와 대본이 맞는지 먼저 확인
python3 build.py             # 조립
```

`output/final.mp4` 가 완성본입니다.

## 결과물

| 위치 | 내용 |
|---|---|
| `output/final.mp4` | 완성본 |
| `output/clips/cut01.mp4` … | 컷별 개별 클립 — 캡컷으로 가져가 손으로 이어 붙일 수 있습니다 |
| `output/audio/cut01.mp3` … | 컷별 나레이션 음성 |

조립이 중간에 멈춰도 여기까지 만들어진 파일은 그대로 남습니다.
다시 실행하면 이미 만든 음성은 건너뛰고 이어서 진행합니다.
음성을 처음부터 다시 만들려면 `--fresh` 를 붙이세요.

## 컷 길이

고정값이 아닙니다. 나레이션 음성의 **실제 길이를 재서** 거기에
`config.json` 의 `cut_padding_sec`(기본 0.4초)를 더한 값이 컷 길이가 됩니다.
말이 끝나면 화면이 넘어갑니다.

## 대본 형식

```json
{
  "title": "1화 아버지를 삼킨 아들, 아들을 삼킨 아버지",
  "accent_color": "#4DD9C6",
  "cuts": [
    {
      "n": 1,
      "narration": "아무것도 없었습니다. 진짜로, 아무것도요.",
      "subtitle": "아무것도 없었습니다",
      "motion": "zoom_in"
    }
  ],
  "ending_card": "다음 편, 신들의 전쟁."
}
```

`motion` — `zoom_in` `zoom_out` `pan_left` `pan_right` `pan_up` `pan_down`

## 설정 (`config.json`)

코드는 건드릴 일이 없습니다. 연출 수치는 전부 여기에 있습니다.

| 항목 | 설명 |
|---|---|
| `tts_voice` / `tts_rate` | 목소리와 말 속도 |
| `cut_padding_sec` | 말이 끝난 뒤 여백 |
| `motion_strength` | 카메라 움직임 크기. 1.08 = 8% 확대. **1.15 초과 금지** (흔들려 보입니다) |
| `motion_quality` | `max`(가장 부드러움·느림) / `smooth` / `fast`(빠름·미세하게 튐) |
| `workers` | 동시에 만들 클립 수. `0` 이면 CPU 코어 수 |
| `subtitle` | 자막 폰트·크기·위치 |
| `bgm_volume` | 배경음악 볼륨 |

## 이미지 규칙

- 파일명은 `cut01.png` 처럼 번호순. **번호가 하나라도 빠지면 에러로 멈춥니다** (조용히 건너뛰지 않습니다)
- 이미지를 자르거나 늘리지 않습니다. 16:9 가 아니면 검은 여백이 들어갑니다

## 검증용 더미 이미지

실제 컷 이미지가 아직 없을 때 파이프라인만 확인하려면:

```bash
python3 tools/make_sample_images.py 6 input/images
```

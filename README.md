# 신들의 사생활 빌더

정지 이미지 + 대본 → 나레이션 애니메이션 mp4 자동 조립기.

컷 길이는 고정값이 아닙니다. 나레이션 음성의 **실제 길이를 재서** 거기에 여백
0.4초를 더한 값이 그 컷의 길이가 됩니다. 말이 끝나면 화면이 넘어갑니다.

---

## 아이패드·아이폰에서 쓰는 법

기기에는 아무것도 설치하지 않습니다. 조립은 GitHub 서버가 하고,
아이패드는 올리고 받기만 합니다. **아이패드를 꺼도 계속 만들어집니다.**

### 1. 이미지 올리기 — 약 2분

사파리에서 저장소를 열고 `input/images` 폴더로 들어갑니다.

```
Add file  →  Upload files  →  사진 28장 선택  →  Commit changes
```

### 2. 대본 넣기 — 약 1분

`input/script.json` 을 열고 연필 아이콘을 누른 뒤 내용을 갈아 끼웁니다.
→ `Commit changes`

### 3. 만들기 — 버튼 한 번

```
Actions 탭  →  왼쪽에서 '영상 만들기'  →  Run workflow  →  초록 버튼
```

먼저 **점검만 하고 끝내기**를 켜고 한 번 돌리면, 40초 만에 이미지와 대본이
맞는지 알려 줍니다. 이상 없으면 끄고 다시 돌리세요.

### 4. 받기 — 약 1분

실행이 끝나면 그 화면 아래 **Artifacts** 에 두 개가 놓입니다.

| 이름 | 내용 |
|---|---|
| `완성본` | 유튜브에 올릴 mp4 한 개 |
| `컷별-클립과-음성` | 컷별 개별 클립과 음성. 손으로 다시 편집할 때 |

받으면 zip 입니다. 파일 앱에서 한 번 누르면 풀립니다.

> Actions 탭이 안 보이면 사파리 주소창 왼쪽 `ᴀA` → **데스크탑용 웹사이트 요청**.

---

## 이미지 이름 규칙

기본은 `cut01.png` ~ `cut28.png` 입니다. 번호가 곧 등장 순서이고,
**번호가 하나라도 빠지면 에러로 멈춥니다.** 조용히 건너뛰지 않습니다.

사진앱에서 `IMG_4821.png` 같은 이름 그대로 올리고 싶으면,
`config.json` 의 `image_naming` 을 `"ordered"` 로 바꾸세요.
파일명을 숫자까지 고려해 정렬한 순서대로 1번 컷부터 배정합니다
(`IMG_2` 가 `IMG_10` 보다 앞에 옵니다).

이 경우 **이미지 개수와 대본 컷 수가 정확히 같아야** 하고, 어떤 그림이 몇 번
컷이 되었는지 점검 단계에서 표로 보여 줍니다. 반드시 한 번 훑어보세요.

> 아이폰 사진은 기본이 **HEIC** 라 열리지 않습니다. `설정 > 카메라 > 포맷 >
> 높은 호환성` 으로 바꾸거나, 올리기 전에 PNG·JPG 로 저장하세요.
> HEIC 가 섞여 있으면 조립을 시작하지 않고 파일 이름을 알려 줍니다.

이미지를 자르거나 늘리지 않습니다. 16:9 가 아니면 검은 여백이 들어갑니다.

---

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

`narration` 은 실제로 읽는 문장, `subtitle` 은 화면에 뜨는 글자입니다.
`subtitle` 을 빼면 나레이션을 그대로 씁니다.

---

## 설정 (`config.json`)

코드는 건드릴 일이 없습니다. 2화부터는 이미지와 대본만 갈아 끼우면 됩니다.

| 항목 | 설명 |
|---|---|
| `tts_voice` | 목소리. 남성 `ko-KR-InJoonNeural` · 여성 `ko-KR-SunHiNeural` |
| `tts_rate` | 말 속도. `-5%` 는 기본보다 조금 느리게 |
| `cut_padding_sec` | 말이 끝난 뒤 여백 (기본 0.4초) |
| `motion_strength` | 카메라 움직임 크기. 1.08 = 8% 확대. **1.15 초과 금지** — 넘기면 실행을 거부합니다 |
| `motion_quality` | `max` 가장 부드럽고 느림 · `smooth` 중간 · `fast` 빠르지만 미세하게 튐 |
| `image_naming` | `strict` cut01 규칙 · `ordered` 파일명 순서대로 |
| `workers` | 동시에 만들 클립 수. `0` 이면 코어 수만큼 |
| `subtitle` | 자막 폰트·크기·위치 |
| `bgm_volume` | 배경음악 볼륨 |

---

## 컴퓨터에서 쓰는 법

윈도우·맥·리눅스에서 직접 돌릴 수도 있습니다. 결과물은 완전히 같습니다.

```bash
sudo apt-get install -y ffmpeg fonts-noto-cjk   # mac: brew install ffmpeg
pip3 install -r requirements.txt

python3 build.py --check    # 이미지와 대본 점검
python3 build.py            # 조립
```

| 위치 | 내용 |
|---|---|
| `output/final.mp4` | 완성본 |
| `output/clips/cut01.mp4` … | 컷별 개별 클립 |
| `output/audio/cut01.mp3` … | 컷별 나레이션 음성 |

중간에 멈춰도 여기까지 만들어진 파일은 남습니다. 다시 실행하면 이미 만든
음성은 건너뛰고 이어서 진행합니다. 음성부터 새로 만들려면 `--fresh` 를 붙이세요.

### 목소리 고르기

```bash
python3 build.py --voice-sample
```

`output/voice_samples/` 에 남성·여성 음성이 하나씩 생깁니다.
(아이패드만 쓰신다면 Actions 로 만든 결과물에서 골라도 됩니다.)

### 도구만 점검하기

실제 이미지 없이 파이프라인만 확인하려면 `samples/` 폴더를 씁니다.

```bash
python3 build.py --images samples/images --script samples/script.json
```

인터넷이 막힌 환경에서는 `--tts espeak` 를 붙이면 기계음으로 길이만 맞춰
영상 부분을 점검할 수 있습니다.

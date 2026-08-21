"""config.json 로딩. 모든 연출 수치는 코드가 아니라 이 파일에서 온다."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "resolution": [1920, 1080],
    "fps": 30,
    "tts_voice": "ko-KR-InJoonNeural",
    "tts_rate": "-5%",
    "cut_padding_sec": 0.4,
    "transition": "dissolve",
    "transition_sec": 0.5,
    "motion_strength": 1.08,
    "subtitle": {
        "font": "Noto Sans KR",
        "size": 48,
        "color": "#FFFFFF",
        "outline_color": "#000000",
        "outline_width": 3,
        "bottom_margin_pct": 12,
        "max_width_pct": 80,
        "max_chars_per_line": 20,
    },
    "bgm_volume": 0.15,
    "fade_in_sec": 1.0,
    "fade_out_sec": 2.0,
    "motion_quality": "max",
    "workers": 0,
    "image_naming": "strict",
    "bgm_duck": "medium",
    "sfx_volume": 0.6,
}

# 정지 이미지가 흔들려 보이기 시작하는 한계선.
MOTION_STRENGTH_CAP = 1.15
# zoompan 프레임 떨림 방지용 업샘플 배수. 크게 그려서 줄이면 이동이 소수점 단위가 된다.
# 낮출수록 빨라지지만 카메라가 픽셀 단위로 튄다(측정값: max 0.19 / smooth 0.53 / fast 0.93).
SUPERSAMPLE_BY_QUALITY = {"fast": 2, "smooth": 3, "max": 4}


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, data: dict):
        self._d = data
        self.width, self.height = data["resolution"]
        self.fps = int(data["fps"])
        self.tts_voice = data["tts_voice"]
        self.tts_rate = data["tts_rate"]
        self.cut_padding_sec = float(data["cut_padding_sec"])
        self.motion_strength = float(data["motion_strength"])
        self.subtitle = data["subtitle"]
        self.bgm_volume = float(data["bgm_volume"])
        self.bgm_duck = data["bgm_duck"]
        self.sfx_volume = float(data["sfx_volume"])
        self.fade_in_sec = float(data["fade_in_sec"])
        self.fade_out_sec = float(data["fade_out_sec"])
        self.transition = data["transition"]
        self.transition_sec = float(data["transition_sec"])
        self.image_naming = data["image_naming"]
        self.ending_card_sec = float(data["ending_card_sec"])
        self.shorts = data["shorts"]
        self.supersample = SUPERSAMPLE_BY_QUALITY[data["motion_quality"]]
        self.workers = int(data["workers"]) or (os.cpu_count() or 2)

    def __getitem__(self, key):
        return self._d[key]

    def variant(self, **overrides) -> "Config":
        """일부 값만 바꾼 설정. 쇼츠처럼 해상도가 다른 판을 만들 때 쓴다."""
        return Config(_merge(self._d, overrides))

    @property
    def size(self) -> str:
        return f"{self.width}x{self.height}"


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | Path = "config.json") -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"설정 파일이 없습니다: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"config.json 형식 오류 ({path}): {e}") from e

    data = _merge(DEFAULTS, raw)

    if data["motion_strength"] > MOTION_STRENGTH_CAP:
        raise ConfigError(
            f"motion_strength {data['motion_strength']} 는 너무 큽니다. "
            f"{MOTION_STRENGTH_CAP} 이하로 낮추세요. 정지 이미지가 흔들려 보입니다."
        )
    if data["motion_strength"] < 1.0:
        raise ConfigError("motion_strength 는 1.0 이상이어야 합니다.")
    if data["motion_quality"] not in SUPERSAMPLE_BY_QUALITY:
        raise ConfigError(
            f"motion_quality '{data['motion_quality']}' 는 알 수 없는 값입니다. "
            f"가능한 값: {', '.join(SUPERSAMPLE_BY_QUALITY)}"
        )
    # 예전 설정 파일 호환
    if data["bgm_duck"] is True:
        data["bgm_duck"] = "medium"
    elif data["bgm_duck"] is False:
        data["bgm_duck"] = "off"
    if data["bgm_duck"] not in ("off", "light", "medium", "strong"):
        raise ConfigError(
            f"bgm_duck '{data['bgm_duck']}' 는 알 수 없는 값입니다. "
            "가능한 값: off, light, medium, strong"
        )
    sh = data["shorts"]
    if sh["background"] not in ("blur", "pad", "crop"):
        raise ConfigError(
            f"shorts.background '{sh['background']}' 는 알 수 없는 값입니다. "
            "가능한 값: blur(흐린 배경), pad(검은 여백), crop(가운데를 잘라 채움)"
        )
    if float(sh["max_seconds"]) <= 0:
        raise ConfigError("shorts.max_seconds 는 0보다 커야 합니다.")
    if data["image_naming"] not in ("strict", "ordered"):
        raise ConfigError(
            f"image_naming '{data['image_naming']}' 는 알 수 없는 값입니다. "
            "가능한 값: strict, ordered"
        )
    if int(data["fps"]) <= 0:
        raise ConfigError("fps 는 1 이상이어야 합니다.")
    w, h = data["resolution"]
    if w % 2 or h % 2:
        raise ConfigError("resolution 의 가로·세로는 짝수여야 합니다 (H.264 제약).")

    return Config(data)

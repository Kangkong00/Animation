"""자막 ASS 파일 생성.

줄바꿈은 어절 단위로만 한다. 단어 중간을 자르면 읽는 흐름이 끊긴다.
두 줄을 넘어가는 긴 문장은 자막을 두 번에 나눠 띄운다. 이미지는 건드리지 않는다.
"""
from __future__ import annotations

import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

MAX_LINES = 2

# ASS 의 Fontsize 는 픽셀이 아니라 폰트 내부 단위라, 같은 48 이라도 폰트마다
# 화면에 그려지는 크기가 다르다. Noto Sans CJK KR 은 48 로 두면 28px 로 나온다.
# 설정의 size 를 '실제 글자 높이(px)' 로 쓰려고, 한 번 그려 보고 배율을 잰다.
_CAL_SIZE = 100
_CAL_TEXT = "한글"
_CAL_CANVAS = (600, 400)

_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{color},{color},{outline_color},{outline_color},0,0,0,0,100,100,0,0,1,{outline},0,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_color(hex_color: str) -> str:
    """#RRGGBB → ASS 의 &HAABBGGRR. 색 순서가 뒤집혀 있어서 그냥 넣으면 파랑이 빨강이 된다."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"색 형식이 잘못되었습니다: {hex_color}")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def wrap_lines(text: str, max_chars: int) -> list[str]:
    """어절 단위 줄바꿈. 한 어절이 기준보다 길어도 자르지 않는다."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if len(candidate) <= max_chars or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def split_events(text: str, max_chars: int) -> list[list[str]]:
    """자막 한 덩어리를 화면에 띄울 단위로 나눈다. 한 번에 최대 두 줄."""
    lines = wrap_lines(text, max_chars)
    return [lines[i:i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)] or [[]]


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build(text: str, duration: float, cfg, font: str, out: Path) -> Path | None:
    """컷 하나짜리 자막 파일. 시간은 컷이 시작하는 순간부터 0초로 센다."""
    text = (text or "").strip()
    if not text:
        return None

    sub = cfg.subtitle
    events = split_events(text, int(sub["max_chars_per_line"]))

    # 글자 수에 비례해 시간을 나눈다. 긴 자막이 더 오래 떠 있어야 읽힌다.
    weights = [max(1, sum(len(l) for l in ev)) for ev in events]
    total_weight = sum(weights)

    body, start = [], 0.0
    for i, (ev, w) in enumerate(zip(events, weights)):
        end = duration if i == len(events) - 1 else start + duration * w / total_weight
        body.append(
            f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,"
            + r"\N".join(ev)
        )
        start = end

    size, _ = ass_fontsize(font, float(sub["size"]))
    header = _HEADER.format(
        width=cfg.width, height=cfg.height,
        font=font, size=size,
        color=ass_color(sub["color"]),
        outline_color=ass_color(sub["outline_color"]),
        outline=int(sub["outline_width"]),
        margin_lr=round(cfg.width * (100 - float(sub["max_width_pct"])) / 200),
        margin_v=round(cfg.height * float(sub["bottom_margin_pct"]) / 100),
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(body) + "\n", encoding="utf-8")
    return out


def filter_arg(path: Path) -> str:
    """ffmpeg 필터 문자열 안에 파일 경로를 넣을 때의 이스케이프."""
    p = str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{p}'"


# ------------------------------------------------------- 글자 크기 보정

_CAL_ASS = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,&H00FFFFFF,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,{text}
"""


def _ink_height(font: str) -> int | None:
    """글자를 한 번 그려서 잉크가 차지한 세로 픽셀 수를 잰다."""
    w, h = _CAL_CANVAS
    with tempfile.TemporaryDirectory() as td:
        ass = Path(td) / "cal.ass"
        ass.write_text(
            _CAL_ASS.format(w=w, h=h, font=font, size=_CAL_SIZE, text=_CAL_TEXT),
            encoding="utf-8",
        )
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi",
             "-i", f"color=c=black:s={w}x{h}", "-frames:v", "1",
             "-vf", filter_arg(ass), "-pix_fmt", "gray", "-f", "rawvideo", "-"],
            capture_output=True,
        )
    if proc.returncode != 0 or len(proc.stdout) < w * h:
        return None

    raw = proc.stdout
    rows = [y for y in range(h) if max(raw[y * w:(y + 1) * w]) > 40]
    return (rows[-1] - rows[0] + 1) if rows else None


@lru_cache(maxsize=8)
def px_per_unit(font: str) -> float | None:
    """ASS Fontsize 1 이 화면에서 몇 픽셀인지. 못 재면 None."""
    ink = _ink_height(font)
    return ink / _CAL_SIZE if ink else None


def ass_fontsize(font: str, wanted_px: float) -> tuple[int, str | None]:
    """원하는 글자 높이(px)를 ASS Fontsize 로 바꾼다."""
    ratio = px_per_unit(font)
    if not ratio:
        return int(round(wanted_px)), (
            "글자 크기를 실측하지 못해 설정값을 그대로 씁니다. "
            "자막이 예상보다 작게 나올 수 있습니다."
        )
    return max(1, int(round(wanted_px / ratio))), None

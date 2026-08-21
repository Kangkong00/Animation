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
# 자막 하나가 화면에 떠 있어야 하는 최소 시간
MIN_EVENT_SEC = 0.6

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
Style: Default,{font},{size},{color},{color},{outline_color},{outline_color},0,0,0,0,100,100,0,0,1,{outline},0,{align},{margin_lr},{margin_lr},{margin_v},1

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


_last_reason: list[str] = []


def why_estimated() -> str:
    return _last_reason[0] if _last_reason else ""


def _letters(text: str) -> str:
    """비교용으로 공백과 문장부호를 걷어낸 글자만 남긴다."""
    return "".join(ch for ch in text if ch.isalnum())


def times_from_words(events: list[list[str]], words: list[dict],
                     duration: float) -> list[tuple[float, float]] | None:
    """말한 시각으로 자막 시간을 잡는다.

    받아 오는 시각이 낱말 단위면 그대로 정확하다. 문장 단위밖에 못 받는 판에서는
    문장이 시작하는 시각은 맞추고 그 안에서만 글자 수로 나눈다. 시각 한 개에
    자막 여러 개가 걸려도 앞 자막이 순식간에 지나가지 않는다.

    자막을 나레이션과 다르게 줄여 쓴 경우에는 어느 대목인지 알 수 없어 None.
    """
    if not words:
        _last_reason.clear()
        _last_reason.append("낱말 시각이 없음 (words.json 비어 있음)")
        return None

    # 글자마다 (몇 번째 시각 덩어리인지, 그 안에서 몇 번째인지, 덩어리 글자수)
    spoken: list[tuple[str, int, int, int]] = []
    for i, w in enumerate(words):
        letters = _letters(w.get("text", ""))
        for j, ch in enumerate(letters):
            spoken.append((ch, i, j, len(letters)))

    written = _letters("".join("".join(ev) for ev in events))
    if not spoken or "".join(c[0] for c in spoken) != written:
        _last_reason.clear()
        _last_reason.append(
            f"글자가 어긋남 · 시각 덩어리 {len(words)}개\n"
            f"        음성쪽: {''.join(c[0] for c in spoken)[:60]}\n"
            f"        자막쪽: {written[:60]}")
        return None

    def time_at(pos: int) -> float:
        if pos >= len(spoken):
            return duration
        _, i, j, n = spoken[pos]
        a, b = float(words[i]["start"]), float(words[i]["end"])
        if b <= a or n <= 1:
            return a
        return a + (b - a) * (j / n)

    starts, pos = [], 0
    for ev in events:
        starts.append(time_at(pos))
        pos += len(_letters("".join(ev)))

    starts[0] = 0.0
    # 뒤로 가지 않게, 그리고 자막 하나가 최소 0.6초는 떠 있게 다듬는다
    for i in range(1, len(starts)):
        starts[i] = min(max(starts[i], starts[i - 1] + MIN_EVENT_SEC),
                        duration - MIN_EVENT_SEC * (len(starts) - i))
    return [(starts[i], starts[i + 1] if i + 1 < len(starts) else duration)
            for i in range(len(starts))]


def boundary_kind(narration: str, words: list[dict]) -> str:
    """받아 온 시각이 낱말 단위인지 문장 단위인지."""
    if not words:
        return "없음"
    return "낱말 단위" if len(words) >= max(2, len(narration.split()) * 0.6) \
        else "문장 단위"


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _header(cfg, font: str, align: int, size: float | None = None,
            margin_v: int | None = None) -> str:
    sub = cfg.subtitle
    px, _ = ass_fontsize(font, float(size if size is not None else sub["size"]))
    return _HEADER.format(
        width=cfg.width, height=cfg.height,
        font=font, size=px, align=align,
        color=ass_color(sub["color"]),
        outline_color=ass_color(sub["outline_color"]),
        outline=int(sub["outline_width"]),
        margin_lr=round(cfg.width * (100 - float(sub["max_width_pct"])) / 200),
        margin_v=(margin_v if margin_v is not None
                  else round(cfg.height * float(sub["bottom_margin_pct"]) / 100)),
    )


def build_card(text: str, duration: float, cfg, font: str, out: Path) -> Path | None:
    """엔딩 카드 글자. 화면 한가운데에 놓는다."""
    text = (text or "").strip()
    if not text:
        return None
    lines = wrap_lines(text, int(cfg.subtitle["max_chars_per_line"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        _header(cfg, font, align=5, margin_v=0)
        + f"Dialogue: 0,{_timestamp(0)},{_timestamp(duration)},Default,,0,0,0,,"
        + r"\N".join(lines) + "\n",
        encoding="utf-8")
    return out


def _estimated_times(events, duration):
    """낱말 시각을 못 쓸 때. 글자 수에 비례해 나눈다 — 어디까지나 어림이다."""
    weights = [max(1, sum(len(l) for l in ev)) for ev in events]
    total = sum(weights)
    times, start = [], 0.0
    for i, w in enumerate(weights):
        end = duration if i == len(weights) - 1 else start + duration * w / total
        times.append((start, end))
        start = end
    return times


def build(text: str, duration: float, cfg, font: str, out: Path,
          words: list[dict] | None = None) -> tuple[Path, bool] | None:
    """컷 하나짜리 자막 파일. 시간은 컷이 시작하는 순간부터 0초로 센다.

    돌려주는 두 번째 값은 시각이 실측인지(True) 어림인지(False)."""
    text = (text or "").strip()
    if not text:
        return None

    sub = cfg.subtitle
    events = split_events(text, int(sub["max_chars_per_line"]))

    _last_reason.clear()
    times = times_from_words(events, words or [], duration)
    exact = times is not None
    if times is None:
        times = _estimated_times(events, duration)

    body = []
    for ev, (start, end) in zip(events, times):
        body.append(
            f"Dialogue: 0,{_timestamp(start)},{_timestamp(end)},Default,,0,0,0,,"
            + r"\N".join(ev)
        )

    header = _header(cfg, font, align=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + "\n".join(body) + "\n", encoding="utf-8")
    return out, exact


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

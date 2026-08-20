"""대본 JSON 로딩과 이미지 폴더 대조. 번호가 하나라도 어긋나면 여기서 멈춘다."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
_IMAGE_RE = re.compile(r"^cut0*(\d+)$", re.IGNORECASE)


class ScriptError(Exception):
    pass


@dataclass
class Cut:
    n: int
    narration: str
    subtitle: str
    motion: str
    sfx: str | None = None
    image: Path | None = None
    # 파이프라인이 채워 넣는 값
    audio: Path | None = None
    audio_sec: float = 0.0
    duration_sec: float = 0.0
    frames: int = 0
    clip: Path | None = None
    start_sec: float = 0.0

    @property
    def stem(self) -> str:
        """중간 파일 이름은 전부 영문·숫자로. 한글 파일명은 최종 출력에서만."""
        return f"cut{self.n:02d}"


@dataclass
class Script:
    title: str
    accent_color: str
    cuts: list[Cut]
    ending_card: str | None = None
    bgm: str | None = None
    meta: dict = field(default_factory=dict)

    @property
    def total_narration_chars(self) -> int:
        return sum(len(c.narration) for c in self.cuts)


def load(path: str | Path) -> Script:
    path = Path(path)
    if not path.exists():
        raise ScriptError(f"대본 파일이 없습니다: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ScriptError(f"대본 JSON 형식 오류 ({path}): {e}") from e

    if not isinstance(raw, dict) or "cuts" not in raw:
        raise ScriptError("대본에 cuts 배열이 없습니다.")
    if not raw["cuts"]:
        raise ScriptError("대본의 cuts 가 비어 있습니다.")

    cuts: list[Cut] = []
    for i, item in enumerate(raw["cuts"], start=1):
        n = int(item.get("n", i))
        if n != i:
            raise ScriptError(
                f"대본 컷 번호가 어긋납니다. {i}번째 항목의 n 이 {n} 입니다. "
                "cuts 는 1부터 1씩 증가해야 합니다."
            )
        narration = (item.get("narration") or "").strip()
        if not narration:
            raise ScriptError(f"컷 {n}: narration 이 비어 있습니다.")
        motion = item.get("motion") or "zoom_in"
        if motion not in MOTIONS:
            raise ScriptError(
                f"컷 {n}: motion '{motion}' 은 알 수 없는 값입니다. "
                f"가능한 값: {', '.join(MOTIONS)}"
            )
        subtitle = (item.get("subtitle") or narration).strip()
        cuts.append(Cut(n=n, narration=narration, subtitle=subtitle,
                        motion=motion, sfx=item.get("sfx")))

    return Script(
        title=(raw.get("title") or "untitled").strip(),
        accent_color=raw.get("accent_color") or "#4DD9C6",
        cuts=cuts,
        ending_card=(raw.get("ending_card") or "").strip() or None,
        bgm=raw.get("bgm"),
        meta={k: v for k, v in raw.items()
              if k not in ("title", "accent_color", "cuts", "ending_card", "bgm")},
    )


def scan_images(folder: str | Path) -> dict[int, Path]:
    """cut01.png 형태의 파일을 번호로 수집한다."""
    folder = Path(folder)
    if not folder.is_dir():
        raise ScriptError(f"이미지 폴더가 없습니다: {folder}")

    found: dict[int, Path] = {}
    for p in sorted(folder.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        m = _IMAGE_RE.match(p.stem)
        if not m:
            raise ScriptError(
                f"이미지 파일명 규칙에 맞지 않습니다: {p.name}\n"
                "  cut01.png ... cut28.png 형식이어야 합니다."
            )
        n = int(m.group(1))
        if n in found:
            raise ScriptError(f"컷 {n} 이미지가 중복입니다: {found[n].name} / {p.name}")
        found[n] = p

    if not found:
        raise ScriptError(f"{folder} 안에 이미지가 없습니다.")
    return found


def attach_images(script: Script, folder: str | Path) -> None:
    """대본 컷과 이미지를 1:1로 묶는다. 빠진 번호는 조용히 넘기지 않고 중단한다."""
    found = scan_images(folder)
    want = {c.n for c in script.cuts}
    have = set(found)

    missing = sorted(want - have)
    extra = sorted(have - want)
    problems = []
    if missing:
        problems.append("이미지가 없는 컷: " + ", ".join(f"cut{n:02d}" for n in missing))
    if extra:
        problems.append("대본에 없는 이미지: " + ", ".join(found[n].name for n in extra))
    if problems:
        raise ScriptError(
            "이미지와 대본이 맞지 않습니다.\n  " + "\n  ".join(problems)
            + f"\n  (대본 {len(want)}컷 / 이미지 {len(have)}장)"
        )

    for c in script.cuts:
        c.image = found[c.n]

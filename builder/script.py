"""대본 JSON 로딩과 이미지 폴더 대조. 번호가 하나라도 어긋나면 여기서 멈춘다."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

MOTIONS = ("zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down")
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")
# ffmpeg 이 열지 못하는데 아이폰·아이패드에서 흔히 나오는 형식
UNSUPPORTED_EXTS = {".heic": "HEIC", ".heif": "HEIF", ".avif": "AVIF"}
_IMAGE_RE = re.compile(r"^cut0*(\d+)$", re.IGNORECASE)
_NUM_RE = re.compile(r"(\d+)")


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
    words: list = field(default_factory=list)
    subtitle_exact: bool = False
    timing_note: str = ""

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
    empty: list[int] = []
    for i, item in enumerate(raw["cuts"], start=1):
        n = int(item.get("n", i))
        if n != i:
            raise ScriptError(
                f"대본 컷 번호가 어긋납니다. {i}번째 항목의 n 이 {n} 입니다. "
                "cuts 는 1부터 1씩 증가해야 합니다."
            )
        narration = (item.get("narration") or "").strip()
        if not narration:
            empty.append(n)
        motion = item.get("motion") or "zoom_in"
        if motion not in MOTIONS:
            raise ScriptError(
                f"컷 {n}: motion '{motion}' 은 알 수 없는 값입니다. "
                f"가능한 값: {', '.join(MOTIONS)}"
            )
        # subtitle 키가 없으면 나레이션을 그대로 쓰고, "" 로 두면 자막을 넣지 않는다
        raw_sub = item.get("subtitle")
        subtitle = narration if raw_sub is None else raw_sub.strip()
        cuts.append(Cut(n=n, narration=narration, subtitle=subtitle,
                        motion=motion, sfx=item.get("sfx")))

    if empty:
        nums = ", ".join(str(n) for n in empty)
        raise ScriptError(
            f"나레이션이 비어 있는 컷: {nums}\n"
            f"  ({len(empty)}개) 대본에서 이 컷들의 narration 을 채워 주세요."
        )

    return Script(
        title=(raw.get("title") or "untitled").strip(),
        accent_color=raw.get("accent_color") or "#4DD9C6",
        cuts=cuts,
        ending_card=(raw.get("ending_card") or "").strip() or None,
        bgm=raw.get("bgm"),
        meta={k: v for k, v in raw.items()
              if k not in ("title", "accent_color", "cuts", "ending_card", "bgm")},
    )


def natural_key(p: Path):
    """IMG_2 가 IMG_10 보다 앞에 오도록. 단순 알파벳순이면 순서가 뒤집힌다.

    아이폰·아이패드에서 올린 한글 파일명은 자모가 분해된 채로 저장된다.
    그대로 비교하면 정렬이 뒤틀리므로 먼저 합쳐 놓는다.
    """
    stem = unicodedata.normalize("NFC", p.stem)
    return [int(t) if t.isdigit() else t.lower() for t in _NUM_RE.split(stem)]


def _image_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        raise ScriptError(f"이미지 폴더가 없습니다: {folder}")

    files, blocked = [], []
    for p in folder.iterdir():
        if not p.is_file() or p.name.startswith("."):
            continue
        ext = p.suffix.lower()
        if ext in UNSUPPORTED_EXTS:
            blocked.append((p.name, UNSUPPORTED_EXTS[ext]))
        elif ext in IMAGE_EXTS:
            files.append(p)

    if blocked:
        names = ", ".join(n for n, _ in blocked[:5])
        more = f" 외 {len(blocked) - 5}장" if len(blocked) > 5 else ""
        raise ScriptError(
            f"{blocked[0][1]} 형식은 열 수 없습니다: {names}{more}\n"
            "  아이폰·아이패드 사진은 기본이 HEIC 입니다.\n"
            "  설정 > 카메라 > 포맷 > '높은 호환성' 으로 바꾸거나,\n"
            "  사진을 올리기 전에 PNG 또는 JPG 로 저장하세요."
        )
    if not files:
        raise ScriptError(f"{folder} 안에 이미지가 없습니다.")
    return files


def scan_images(folder: str | Path, naming: str = "strict",
                expected: int | None = None) -> dict[int, Path]:
    """이미지를 컷 번호에 배정한다.

    strict  — cut01.png 규칙. 번호가 곧 순서다.
    ordered — 파일명을 숫자까지 고려해 정렬한 순서대로 1번부터 배정한다.
              사진앱에서 그대로 올린 IMG_4821.png 같은 이름을 위한 것.
    """
    folder = Path(folder)
    files = _image_files(folder)

    if naming == "ordered":
        if expected is not None and len(files) != expected:
            raise ScriptError(
                f"이미지가 {len(files)}장인데 대본은 {expected}컷입니다.\n"
                "  순서대로 배정하는 방식(ordered)에서는 개수가 정확히 같아야 합니다.\n"
                "  빠진 그림이 없는지 확인하세요."
            )
        return {i: p for i, p in enumerate(sorted(files, key=natural_key), start=1)}

    found: dict[int, Path] = {}
    for p in sorted(files, key=natural_key):
        m = _IMAGE_RE.match(p.stem)
        if not m:
            raise ScriptError(
                f"이미지 파일명 규칙에 맞지 않습니다: {p.name}\n"
                "  cut01.png ... cut28.png 형식이어야 합니다.\n"
                "  이름을 바꾸기 어려우면 config.json 의 image_naming 을\n"
                "  \"ordered\" 로 두세요. 파일명 순서대로 컷을 배정합니다."
            )
        n = int(m.group(1))
        if n in found:
            raise ScriptError(f"컷 {n} 이미지가 중복입니다: {found[n].name} / {p.name}")
        found[n] = p

    return found


def attach_images(script: Script, folder: str | Path,
                  naming: str = "strict") -> None:
    """대본 컷과 이미지를 1:1로 묶는다. 빠진 번호는 조용히 넘기지 않고 중단한다."""
    found = scan_images(folder, naming, expected=len(script.cuts))
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

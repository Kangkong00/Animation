"""ffmpeg / ffprobe 호출 래퍼."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class MediaError(Exception):
    pass


def require_tools() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            raise MediaError(
                f"{tool} 를 찾을 수 없습니다.\n"
                "  설치: sudo apt-get install -y ffmpeg   (mac: brew install ffmpeg)"
            )


def run(cmd: list[str], what: str) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-12:])
        raise MediaError(f"{what} 실패\n{tail}")


def probe_duration(path: str | Path) -> float:
    """실제 재생 길이(초). mp3 헤더값을 믿지 않고 ffprobe 로 다시 잰다."""
    path = Path(path)
    cmd = ["ffprobe", "-v", "error", "-show_entries",
           "format=duration:stream=duration", "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"길이 측정 실패: {path.name}\n{proc.stderr.strip()[-400:]}")

    data = json.loads(proc.stdout or "{}")
    candidates = []
    fmt = (data.get("format") or {}).get("duration")
    if fmt not in (None, "N/A"):
        candidates.append(float(fmt))
    for st in data.get("streams") or []:
        d = st.get("duration")
        if d not in (None, "N/A"):
            candidates.append(float(d))

    candidates = [c for c in candidates if c > 0]
    if not candidates:
        raise MediaError(f"길이를 읽을 수 없습니다 (빈 파일?): {path.name}")
    # 헤더값과 스트림값이 다르면 긴 쪽을 택한다. 짧게 잡으면 말이 잘린다.
    return max(candidates)


def probe_size(path: str | Path) -> tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "json", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"이미지 크기 측정 실패: {Path(path).name}")
    st = (json.loads(proc.stdout or "{}").get("streams") or [{}])[0]
    return int(st.get("width", 0)), int(st.get("height", 0))


def count_frames(path: str | Path) -> int:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
           "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(path)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"프레임 수 측정 실패: {Path(path).name}")
    return int((proc.stdout or "0").strip() or 0)

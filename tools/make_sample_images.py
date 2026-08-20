#!/usr/bin/env python3
"""검증용 더미 이미지 생성기. 실제 컷 이미지가 준비되면 필요 없다.

컷 번호와 상하좌우 표시가 크게 들어가 있어, 완성된 mp4 만 보고도
(a) 순서가 맞는지 (b) 카메라가 어느 방향으로 움직이는지 알 수 있다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BG = ["0x14212e", "0x2a1f2e", "0x16281f", "0x2e2418", "0x1c1c2e", "0x2e1a1a",
      "0x102a2a", "0x2a2210", "0x201030", "0x102030"]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def make(n: int, out: Path, w: int = 1920, h: int = 1080) -> None:
    def txt(text, size, x, y, color="white"):
        return (f"drawtext=fontfile={FONT}:text='{text}':fontsize={size}"
                f":fontcolor={color}:x={x}:y={y}")

    vf = ",".join([
        "drawgrid=w=160:h=160:t=3:c=white@0.18",
        txt(f"CUT {n:02d}", 260, "(w-tw)/2", "(h-th)/2"),
        txt("LEFT", 90, "60", "(h-th)/2", "0x4DD9C6"),
        txt("RIGHT", 90, "w-tw-60", "(h-th)/2", "0x4DD9C6"),
        txt("TOP", 90, "(w-tw)/2", "50", "0x4DD9C6"),
        txt("BOTTOM", 90, "(w-tw)/2", "h-th-50", "0x4DD9C6"),
    ])
    subprocess.run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={BG[(n - 1) % len(BG)]}:s={w}x{h}",
        "-vf", vf, "-frames:v", "1", str(out),
    ], check=True)


if __name__ == "__main__":
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    dest = Path(sys.argv[2] if len(sys.argv) > 2 else "input/images")
    dest.mkdir(parents=True, exist_ok=True)
    for i in range(1, count + 1):
        make(i, dest / f"cut{i:02d}.png")
        print(f"  {dest}/cut{i:02d}.png")

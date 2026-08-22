"""그림에 박힌 워터마크 지우기.

생성 도구가 오른쪽 아래에 남기는 표식을 주변 색으로 메운다. 메운 자리에
경계가 보이지 않도록 그 부분만 아주 살짝 흐리게 문지른다.

자리는 비율로 적는다. 그래야 그림 크기가 달라져도 같은 곳을 가리킨다.
"""
from __future__ import annotations

from pathlib import Path

from .media import probe_size, run


def box_for(cfg, width: int, height: int) -> tuple[int, int, int, int]:
    wm = cfg.watermark
    x = int(width * float(wm["x_pct"]) / 100)
    y = int(height * float(wm["y_pct"]) / 100)
    w = int(width * float(wm["w_pct"]) / 100)
    h = int(height * float(wm["h_pct"]) / 100)
    # delogo 는 상자가 화면 안쪽에 완전히 들어와야 한다
    x = max(1, min(x, width - 3))
    y = max(1, min(y, height - 3))
    w = max(1, min(w, width - x - 1))
    h = max(1, min(h, height - y - 1))
    return x, y, w, h


def clean(src: Path, dst: Path, cfg) -> Path:
    """워터마크를 지운 그림을 만들어 돌려준다."""
    width, height = probe_size(src)
    x, y, w, h = box_for(cfg, width, height)
    soften = float(cfg.watermark["soften"])

    graph = f"[0:v]delogo=x={x}:y={y}:w={w}:h={h}"
    if soften > 0:
        # 메운 자리보다 조금 넓게 잡아 경계를 문지른다
        m = max(4, int(min(w, h) * 0.2))
        bx, by = max(0, x - m), max(0, y - m)
        bw, bh = min(width - bx, w + m * 2), min(height - by, h + m * 2)
        graph += (f",split[base][r];[r]crop={bw}:{bh}:{bx}:{by},"
                  f"gblur=sigma={soften}[b];[base][b]overlay={bx}:{by}[v]")
    else:
        graph += "[v]"

    dst.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-filter_complex", graph, "-map", "[v]", "-frames:v", "1", str(dst)],
        f"{src.name} 워터마크 지우기")
    return dst

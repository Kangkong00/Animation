"""배경음악과 효과음 섞기.

배경음악은 나레이션이 나오는 동안 스스로 작아진다(더킹). 볼륨만 낮춰 놓으면
말과 음악이 같은 음역에서 겹쳐 웅얼거리는데, 더킹을 걸면 말이 또렷해진다.
페이드는 배경음악에만 건다. 나레이션을 페이드하면 첫 마디가 작아진다.
"""
from __future__ import annotations

from pathlib import Path

from .media import MediaError, run

# 나레이션 음색.
#
# 잔향은 넣지 않는다. 공간감을 준다고 넣었더니 말이 뭉개지고 인공적으로 들렸다.
#
# 소리 높이를 내릴 때는 음정만 따로 변조하지 않는다. 그 방식은 파형을 다시
# 짜맞추기 때문에 기계음이 생긴다. 대신 테이프를 늦게 돌리듯 통째로 늦춰
# 자연히 낮아지게 한 다음, 속도만 되돌린다.
_TTS_RATE = 24000          # edge-tts 가 내려주는 표본율

# 치찰음과 금속성 대역만 눌러 주는 가벼운 정리. 압축도 약하게 건다.
_CLEANUP = (
    "deesser=i=0.35,"
    "equalizer=f=3200:t=q:w=1.8:g=-3,"      # 금속성
    "equalizer=f=115:t=q:w=1.0:g=2,"        # 저음 살짝
    "acompressor=threshold=-18dB:ratio=2:attack=15:release=250:makeup=1.5,"
    "alimiter=limit=0.95"
)


def _drop(ratio: float) -> str:
    """소리 높이를 ratio 배로 낮춘다. 길이는 그대로."""
    return (f"aresample={_TTS_RATE},"
            f"asetrate={int(_TTS_RATE * ratio)},"
            f"aresample=48000,"
            f"atempo={1 / ratio:.10f},"
            f"highpass=f=60,{_CLEANUP}")


NARRATION_TONE = {
    "off":   "",
    "clean": f"highpass=f=60,{_CLEANUP}",   # 높이는 그대로, 정리만
    "low":   _drop(0.87),                   # 132Hz → 115Hz
    "lower": _drop(0.795),                  # 132Hz → 105Hz
}

AUDIO_RATE = 48000
AUDIO_CH = 2
BGM_EXTS = (".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac")

# 더킹 세기. 괄호 안은 이 대본으로 실측한, 말할 때 배경음악이 눌리는 양이다.
# 배경음악은 이미 15% 로 깔리므로 너무 세게 누르면 아예 안 들린다.
DUCK_LEVELS = {
    "light":  "threshold=0.05:ratio=3:attack=20:release=250:makeup=1",   # 약 4dB
    "medium": "threshold=0.03:ratio=4:attack=20:release=300:makeup=1",   # 약 8dB
    "strong": "threshold=0.02:ratio=6:attack=20:release=400:makeup=1",   # 약 12dB
}


def find_bgm(assets_dir: Path, named: str | None = None) -> Path | None:
    """대본에 지정한 파일, 없으면 input 폴더의 bgm.* 를 쓴다."""


def find_bgm(assets_dir: Path, named: str | None = None) -> Path | None:
    """대본에 지정한 파일, 없으면 input 폴더의 bgm.* 를 쓴다."""
    if named:
        p = Path(named)
        if not p.is_absolute():
            p = assets_dir / named
        if not p.exists():
            raise MediaError(
                f"배경음악 파일을 찾을 수 없습니다: {named}\n"
                f"  찾아본 곳: {p}"
            )
        return p

    for ext in BGM_EXTS:
        p = assets_dir / f"bgm{ext}"
        if p.exists():
            return p
    return None


def find_sfx(assets_dir: Path, named: str, cut_n: int) -> Path:
    p = Path(named)
    if not p.is_absolute():
        for base in (assets_dir / "sfx", assets_dir):
            if (base / named).exists():
                return base / named
        p = assets_dir / "sfx" / named
    if not p.exists():
        raise MediaError(
            f"컷 {cut_n}: 효과음 파일을 찾을 수 없습니다: {named}\n"
            f"  {assets_dir / 'sfx'} 안에 넣어 주세요."
        )
    return p


def _norm(label: str, out: str, extra: str = "") -> str:
    chain = f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo"
    if extra:
        chain += "," + extra
    return f"[{label}]{chain}[{out}]"


def mix(narration: Path, out: Path, cfg, total_sec: float,
        bgm: Path | None = None,
        sfx: list[tuple[Path, float]] | None = None) -> Path:
    """나레이션 + 배경음악 + 효과음 → 최종 소리 한 트랙."""
    sfx = sfx or []
    if bgm is None and not sfx:
        return narration

    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(narration)]
    graph: list[str] = []
    mix_labels: list[str] = []
    idx = 1

    if bgm is not None:
        # 나레이션을 둘로 나눈다. 하나는 그대로 쓰고, 하나는 더킹의 기준 신호로 쓴다.
        graph.append("[0:a]asplit=2[nar][duckkey]")
        mix_labels.append("[nar]")

        fade_out_start = max(0.0, total_sec - cfg.fade_out_sec)
        bgm_chain = (
            f"atrim=0:{total_sec:.3f},asetpts=N/SR/TB,"
            f"volume={cfg.bgm_volume},"
            f"afade=t=in:st=0:d={cfg.fade_in_sec},"
            f"afade=t=out:st={fade_out_start:.3f}:d={cfg.fade_out_sec}"
        )
        graph.append(_norm(f"{idx}:a", "bgmraw", bgm_chain))
        if cfg.bgm_duck == "off":
            graph.append("[bgmraw]anull[bgm]")
            graph.append("[duckkey]anullsink")
        else:
            graph.append(
                f"[bgmraw][duckkey]sidechaincompress={DUCK_LEVELS[cfg.bgm_duck]}[bgm]"
            )
        mix_labels.append("[bgm]")
        # 배경음악이 영상보다 짧으면 반복해서 채운다
        cmd += ["-stream_loop", "-1", "-i", str(bgm)]
        idx += 1
    else:
        mix_labels.append("[0:a]")

    for n, (path, at) in enumerate(sfx):
        delay_ms = int(round(at * 1000))
        graph.append(_norm(
            f"{idx}:a", f"sfx{n}",
            f"volume={cfg.sfx_volume},adelay={delay_ms}:all=1",
        ))
        mix_labels.append(f"[sfx{n}]")
        cmd += ["-i", str(path)]
        idx += 1

    graph.append(
        "".join(mix_labels)
        + f"amix=inputs={len(mix_labels)}:duration=first:normalize=0,"
        # 여러 소리가 겹쳐 최대치를 넘으면 찢어진다. 마지막에 눌러 준다.
        "alimiter=limit=0.95[out]"
    )

    cmd += [
        "-filter_complex", ";".join(graph),
        "-map", "[out]", "-t", f"{total_sec:.6f}",
        "-c:a", "pcm_s16le", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH),
        str(out),
    ]
    run(cmd, "배경음악·효과음 섞기")
    return out

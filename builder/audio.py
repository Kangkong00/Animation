"""배경음악과 효과음 섞기.

배경음악은 나레이션이 나오는 동안 스스로 작아진다(더킹). 볼륨만 낮춰 놓으면
말과 음악이 같은 음역에서 겹쳐 웅얼거리는데, 더킹을 걸면 말이 또렷해진다.
페이드는 배경음악에만 건다. 나레이션을 페이드하면 첫 마디가 작아진다.
"""
from __future__ import annotations

from pathlib import Path

from .media import MediaError, run

# 나레이션 음색. 합성 음성 특유의 얇고 쇳소리 나는 느낌을 눌러 주고,
# 가슴 울림과 아주 옅은 공간감을 더해 '녹음한 목소리'에 가깝게 만든다.
NARRATION_TONE = {
    "off": "",
    "warm": (
        "highpass=f=65,"
        "equalizer=f=130:t=q:w=1.0:g=2.5,"      # 가슴 울림
        "equalizer=f=4200:t=q:w=2.0:g=-2.5,"    # 쇳소리 억제
        "acompressor=threshold=-20dB:ratio=2.5:attack=12:release=220:makeup=2"
    ),
    "deep": (
        # 소리 높이를 내리되 성대 울림까지 함께 내린다.
        # 목소리만 낮추면 어색하지만, 함께 내리면 체구가 큰 사람이 말하는 소리가 된다.
        "rubberband=pitch=0.93,"
        "highpass=f=50,"
        "equalizer=f=100:t=q:w=0.9:g=4.5,"
        "equalizer=f=320:t=q:w=1.2:g=-2.5,"
        "equalizer=f=4500:t=q:w=2.0:g=-4.5,"
        "acompressor=threshold=-22dB:ratio=3.5:attack=8:release=180:makeup=3.5,"
        "aecho=0.9:0.85:55:0.14,"
        "alimiter=limit=0.95"
    ),
    "myth": (
        # 가장 깊게. 배음을 더해 합성 음성의 얇음을 메우고 넓은 공간에 놓는다.
        "rubberband=pitch=0.89,"
        "highpass=f=45,"
        "equalizer=f=90:t=q:w=0.8:g=5.5,"
        "equalizer=f=300:t=q:w=1.2:g=-3,"
        "equalizer=f=4800:t=q:w=2.0:g=-5,"
        "aexciter=amount=1.5:blend=2,"
        "acompressor=threshold=-24dB:ratio=4:attack=6:release=160:makeup=4,"
        "aecho=0.88:0.8:70|130:0.16|0.09,"
        "alimiter=limit=0.95"
    ),
    "epic": (
        "highpass=f=55,"
        "equalizer=f=110:t=q:w=0.9:g=4,"        # 더 깊은 저음
        "equalizer=f=330:t=q:w=1.2:g=-2,"       # 웅웅거림 제거
        "equalizer=f=4500:t=q:w=2.0:g=-4,"      # 쇳소리 강하게 억제
        "acompressor=threshold=-22dB:ratio=3.5:attack=8:release=180:makeup=3.5,"
        "aecho=0.9:0.85:48:0.12,"               # 옅은 공간감
        "alimiter=limit=0.95"
    ),
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

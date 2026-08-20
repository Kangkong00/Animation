"""컷별 클립 생성과 최종 합치기.

떨림 방지: 원본을 크게 키운 뒤(SUPERSAMPLE) 잘라내고 줄인다. 그래야 카메라가
프레임당 1픽셀 미만으로도 움직일 수 있다.
싱크 밀림 방지: 모든 클립을 같은 해상도·fps·샘플레이트·코덱으로 만들고,
컷 길이를 프레임 단위로 딱 떨어지게 맞춘다.
"""
from __future__ import annotations

import math
from pathlib import Path

from .config import Config
from .media import MediaError, run

AUDIO_RATE = 48000
AUDIO_CH = 2


def frames_for(seconds: float, fps: int) -> int:
    """길이를 프레임 수로. 올림해서 음성이 잘리지 않게 한다."""
    return max(1, int(math.ceil(seconds * fps - 1e-6)))


def _motion_filter(motion: str, strength: float, frames: int) -> str:
    """zoompan 표현식. p 는 0 → 1 로 가는 진행도."""
    z = strength
    p = "0" if frames <= 1 else f"(on/{frames - 1})"
    cx = "iw/2-(iw/zoom/2)"
    cy = "ih/2-(ih/zoom/2)"

    if motion == "zoom_in":
        zoom, x, y = f"1+({z}-1)*{p}", cx, cy
    elif motion == "zoom_out":
        zoom, x, y = f"{z}-({z}-1)*{p}", cx, cy
    elif motion == "pan_left":
        zoom, x, y = f"{z}", f"(iw-iw/zoom)*(1-{p})", cy
    elif motion == "pan_right":
        zoom, x, y = f"{z}", f"(iw-iw/zoom)*{p}", cy
    elif motion == "pan_up":
        zoom, x, y = f"{z}", cx, f"(ih-ih/zoom)*(1-{p})"
    elif motion == "pan_down":
        zoom, x, y = f"{z}", cx, f"(ih-ih/zoom)*{p}"
    else:
        raise MediaError(f"알 수 없는 모션: {motion}")

    return f"zoompan=z='{zoom}':x='{x}':y='{y}'"


def image_chain(motion: str, cfg: Config, frames: int) -> str:
    """정지 이미지 → 움직이는 영상. 이미지를 자르거나 늘리지 않고 비율을 지킨다."""
    sw, sh = cfg.width * cfg.supersample, cfg.height * cfg.supersample
    return (
        f"scale={sw}:{sh}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={sw}:{sh}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,"
        + _motion_filter(motion, cfg.motion_strength, frames)
        + f":d={frames}:s={cfg.size}:fps={cfg.fps},"
        f"format=yuv420p"
    )


def pad_audio(src: Path, dst: Path, seconds: float) -> Path:
    """나레이션 뒤에 여백을 붙여 컷 길이에 정확히 맞춘 wav. 무손실이라 이어붙여도 안 밀린다."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-af", f"aresample={AUDIO_RATE}:first_pts=0,apad",
        "-ac", str(AUDIO_CH), "-t", f"{seconds:.6f}",
        "-c:a", "pcm_s16le", str(dst),
    ], f"{src.stem} 음성 길이 맞추기")
    return dst


def silent_audio(dst: Path, seconds: float) -> Path:
    """나레이션 없는 구간(엔딩 카드 등)용 무음."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    run([
        "ffmpeg", "-y", "-v", "error",
        "-f", "lavfi", "-i",
        f"anullsrc=channel_layout=stereo:sample_rate={AUDIO_RATE}",
        "-t", f"{seconds:.6f}", "-c:a", "pcm_s16le", str(dst),
    ], "무음 생성")
    return dst


def fade_filter(duration: float, cfg: Config,
                first: bool, last: bool) -> str:
    """첫 컷은 어둠에서 밝아지고, 마지막 컷은 어둠으로 잠긴다."""
    parts = []
    if first and cfg.fade_in_sec > 0:
        d = min(cfg.fade_in_sec, duration)
        parts.append(f"fade=t=in:st=0:d={d:.3f}")
    if last and cfg.fade_out_sec > 0:
        d = min(cfg.fade_out_sec, duration)
        parts.append(f"fade=t=out:st={duration - d:.3f}:d={d:.3f}")
    return ",".join(parts)


def build_clip(image: Path, audio_wav: Path, out: Path, cfg: Config,
               motion: str, frames: int, extra_video: str = "") -> Path:
    """컷 하나를 mp4 로. 이 파일만 따로 떼어 캡컷으로 가져가도 쓸 수 있다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    chain = image_chain(motion, cfg, frames)
    if extra_video:
        chain += "," + extra_video
    run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(image), "-i", str(audio_wav),
        "-filter_complex", f"[0:v]{chain}[v]",
        "-map", "[v]", "-map", "1:a",
        "-frames:v", str(frames),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-r", str(cfg.fps), "-fps_mode", "cfr",
        "-c:a", "aac", "-b:a", "192k", "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH),
        "-movflags", "+faststart", str(out),
    ], f"{out.stem} 클립 생성")
    return out


def _concat_list(paths: list[Path], listfile: Path) -> Path:
    listfile.parent.mkdir(parents=True, exist_ok=True)
    lines = ["file '" + str(p.resolve()).replace("'", "'\\''") + "'" for p in paths]
    listfile.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listfile


def join_audio(audio_wavs: list[Path], out: Path, workdir: Path) -> Path:
    """컷별 나레이션을 하나의 연속 트랙으로. 무손실이라 이어 붙여도 안 밀린다."""
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(_concat_list(audio_wavs, workdir / "audio.txt")),
        "-c:a", "copy", str(out),
    ], "음성 이어붙이기")
    return out


def concat(clips: list[Path], full_audio: Path, out: Path, workdir: Path) -> Path:
    """영상은 무손실로 복사해 붙이고, 다 만들어 둔 소리를 얹는다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    video_only = workdir / "video_only.mp4"
    run([
        "ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
        "-i", str(_concat_list(clips, workdir / "clips.txt")),
        "-map", "0:v:0", "-c:v", "copy", "-an", str(video_only),
    ], "영상 이어붙이기")

    run([
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video_only), "-i", str(full_audio),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-ar", str(AUDIO_RATE), "-ac", str(AUDIO_CH),
        "-movflags", "+faststart", str(out),
    ], "최종 합치기")
    return out

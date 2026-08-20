"""나레이션 음성 생성.

기본 엔진은 edge-tts(무료, 한국어 품질 양호). 네트워크가 막힌 환경에서
영상 파이프라인만 점검할 때를 위해 오프라인 엔진(espeak)을 함께 둔다.
오프라인 엔진은 목소리 품질이 아니라 '길이가 있는 음성'을 만드는 용도다.
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path

RETRIES = 3
RETRY_WAIT_SEC = 2.0

VOICES = {
    "male": "ko-KR-InJoonNeural",
    "female": "ko-KR-SunHiNeural",
}


class TTSError(Exception):
    pass


# ----------------------------------------------------------------- edge-tts

async def _edge_save(text: str, out: Path, voice: str, rate: str) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(str(out))


def _edge(text: str, out: Path, voice: str, rate: str, cut_label: str) -> None:
    try:
        import edge_tts  # noqa: F401
    except ImportError as e:
        raise TTSError(
            "edge-tts 가 설치되어 있지 않습니다.\n  설치: pip3 install edge-tts"
        ) from e

    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            asyncio.run(_edge_save(text, out, voice, rate))
            if out.exists() and out.stat().st_size > 0:
                return
            last = "빈 파일이 생성되었습니다"
        except Exception as e:  # 네트워크 의존이라 예외 종류가 다양하다
            last = f"{type(e).__name__}: {e}"
        if attempt < RETRIES:
            import time
            time.sleep(RETRY_WAIT_SEC * attempt)

    raise TTSError(
        f"{cut_label} 음성 생성이 {RETRIES}회 모두 실패했습니다.\n"
        f"  마지막 오류: {last}\n"
        "  인터넷 연결과 방화벽을 확인한 뒤 다시 실행하세요. "
        "이미 만들어진 음성은 output/audio/ 에 남아 있어 그대로 재사용됩니다."
    )


# ------------------------------------------------------------ 오프라인 대역

# 한국어 나레이션 체감 속도(초당 글자수)에 맞춘 espeak 속도.
_ESPEAK_WPM = 145


def _espeak(text: str, out: Path, voice: str, rate: str, cut_label: str) -> None:
    if not shutil.which("espeak-ng"):
        raise TTSError(
            "espeak-ng 가 없습니다 (오프라인 엔진).\n"
            "  설치: sudo apt-get install -y espeak-ng"
        )
    with tempfile.TemporaryDirectory() as td:
        wav = Path(td) / "raw.wav"
        proc = subprocess.run(
            ["espeak-ng", "-v", "ko", "-s", str(_ESPEAK_WPM), "-w", str(wav), text],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or not wav.exists():
            raise TTSError(f"{cut_label} 오프라인 음성 생성 실패: {proc.stderr.strip()[-200:]}")
        conv = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(wav),
             "-c:a", "libmp3lame", "-b:a", "192k", "-ar", "48000", "-ac", "1", str(out)],
            capture_output=True, text=True,
        )
        if conv.returncode != 0:
            raise TTSError(f"{cut_label} mp3 변환 실패: {conv.stderr.strip()[-200:]}")


ENGINES = {"edge": _edge, "espeak": _espeak}


def synth(text: str, out: Path, voice: str, rate: str,
          engine: str = "edge", cut_label: str = "") -> Path:
    """음성 파일을 만든다. 이미 있으면 다시 만들지 않는다."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if engine not in ENGINES:
        raise TTSError(f"알 수 없는 TTS 엔진: {engine} (가능: {', '.join(ENGINES)})")
    ENGINES[engine](text, out, voice, rate, cut_label or out.stem)
    return out


def make_voice_samples(outdir: Path, text: str, rate: str = "-5%") -> list[Path]:
    """남성·여성 목소리로 같은 문장을 뽑아 비교용 파일을 만든다."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    made = []
    for label, voice in VOICES.items():
        p = outdir / f"voice_{label}_{voice}.mp3"
        synth(text, p, voice, rate, engine="edge", cut_label=f"목소리 샘플({label})")
        made.append(p)
    return made

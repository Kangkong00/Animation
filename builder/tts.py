"""나레이션 음성 생성.

기본 엔진은 edge-tts(무료, 한국어 품질 양호). 네트워크가 막힌 환경에서
영상 파이프라인만 점검할 때를 위해 오프라인 엔진(espeak)을 함께 둔다.
오프라인 엔진은 목소리 품질이 아니라 '길이가 있는 음성'을 만드는 용도다.
"""
from __future__ import annotations

import asyncio
import json
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

async def _edge_save(text: str, out: Path, voice: str, rate: str) -> list[dict]:
    """음성을 받으면서 낱말이 언제 발음되는지도 함께 받아 둔다.

    이 시각이 있어야 자막이 말과 정확히 맞는다. 없으면 글자 수로 어림잡는
    수밖에 없고, 그러면 자막이 말보다 먼저 넘어가거나 늦게 남는다.
    """
    import edge_tts

    # 낱말 단위를 반드시 요청한다. 판 7.x 의 기본값은 문장 단위라, 그대로 두면
    # 긴 문장 하나에 시각이 한 개만 와서 자막을 맞출 수가 없다.
    try:
        comm = edge_tts.Communicate(text, voice, rate=rate,
                                    boundary="WordBoundary")
    except TypeError:
        comm = edge_tts.Communicate(text, voice, rate=rate)

    words: list[dict] = []
    seen: set[str] = set()
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            kind = chunk.get("type", "?")
            seen.add(kind)
            if kind == "audio":
                f.write(chunk["data"])
            elif "offset" in chunk and chunk.get("text"):
                # 낱말 경계의 이름이 판마다 다를 수 있어 종류를 따지지 않고
                # 시각과 글자가 함께 오는 것은 모두 받는다.
                # 단위는 100나노초. 초로 바꿔 둔다.
                words.append({
                    "text": chunk["text"],
                    "start": chunk["offset"] / 1e7,
                    "end": (chunk["offset"] + chunk.get("duration", 0)) / 1e7,
                })
    return {"words": words, "types": sorted(seen)}


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
            got = asyncio.run(_edge_save(text, out, voice, rate))
            if out.exists() and out.stat().st_size > 0:
                save_words(out, got)
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


def words_path(audio: Path) -> Path:
    return Path(audio).with_suffix(".words.json")


def save_words(audio: Path, data: dict) -> None:
    words_path(audio).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _read(audio: Path):
    p = words_path(audio)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def load_words(audio: Path) -> list[dict]:
    """낱말 시각표. 없으면 빈 목록 — 자막은 어림 계산으로 넘어간다."""
    data = _read(audio)
    if isinstance(data, dict):
        return data.get("words") or []
    return data or []


def stream_kinds(audio: Path) -> list[str]:
    """음성을 받을 때 어떤 종류의 응답이 왔는지. 낱말 시각이 비었을 때 원인 확인용."""
    data = _read(audio)
    return data.get("types", []) if isinstance(data, dict) else []


def synth(text: str, out: Path, voice: str, rate: str,
          engine: str = "edge", cut_label: str = "") -> Path:
    """음성 파일을 만든다. 이미 있으면 다시 만들지 않는다."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if engine not in ENGINES:
        raise TTSError(f"알 수 없는 TTS 엔진: {engine} (가능: {', '.join(ENGINES)})")
    ENGINES[engine](text, out, voice, rate, cut_label or out.stem)
    return out


async def _list_korean() -> list[dict]:
    import edge_tts

    voices = await edge_tts.list_voices()
    ko = [v for v in voices if str(v.get("Locale", "")).startswith("ko-")]
    # 남성 먼저, 그 안에서는 이름순
    return sorted(ko, key=lambda v: (v.get("Gender", ""), v.get("ShortName", "")))


def korean_voices() -> list[dict]:
    """마이크로소프트가 지금 제공하는 한국어 목소리를 그대로 받아 온다.

    목록을 코드에 박아 두지 않는다. 목소리는 늘고 줄기 때문에, 물어봐서 쓴다.
    """
    try:
        import edge_tts  # noqa: F401
    except ImportError as e:
        raise TTSError(
            "edge-tts 가 설치되어 있지 않습니다.\n  설치: pip3 install edge-tts"
        ) from e
    try:
        return asyncio.run(_list_korean())
    except Exception as e:
        raise TTSError(
            f"목소리 목록을 받아오지 못했습니다: {type(e).__name__}: {e}\n"
            "  인터넷 연결을 확인하세요."
        ) from e


def make_voice_samples(outdir: Path, text: str, rate: str = "-5%") -> list[dict]:
    """한국어 목소리를 전부 같은 문장으로 뽑아 비교할 수 있게 한다.

    파일 이름 앞에 번호를 붙여, 파일 앱에서 위에서부터 차례로 들으면 된다.
    """
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    made = []
    for i, v in enumerate(korean_voices(), start=1):
        short = v["ShortName"]                      # ko-KR-InJoonNeural
        name = short.split("-")[-1].replace("Neural", "")
        sex = "남성" if v.get("Gender") == "Male" else "여성"
        out = outdir / f"{i:02d}_{sex}_{name}.mp3"
        synth(text, out, short, rate, engine="edge", cut_label=f"목소리 샘플({name})")
        made.append({"번호": i, "성별": sex, "이름": name,
                     "설정값": short, "파일": out})
    return made

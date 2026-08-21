"""전체 조립 흐름. 음성 → 길이 측정 → 클립 → 합치기."""
from __future__ import annotations

import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from . import audio as audio_mod
from . import config as config_mod
from . import script as script_mod
from . import fonts, tts, video
from . import subtitle as subs
from .media import probe_duration, probe_size, require_tools


@dataclass
class Paths:
    root: Path
    images: Path
    script: Path
    config: Path
    out: Path

    @property
    def audio(self) -> Path:
        return self.out / "audio"

    @property
    def clips(self) -> Path:
        return self.out / "clips"

    @property
    def assets(self) -> Path:
        """배경음악·효과음이 놓이는 곳. 이미지 폴더의 부모."""
        return self.images.parent

    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def final(self) -> Path:
        return self.out / "final.mp4"


@dataclass
class Result:
    final: Path
    clips: list[Path] = field(default_factory=list)
    audio: list[Path] = field(default_factory=list)
    total_sec: float = 0.0
    elapsed_sec: float = 0.0
    cuts: list[script_mod.Cut] = field(default_factory=list)
    title: str = ""
    bgm: Path | None = None
    sfx_count: int = 0


def _noop(**kwargs):
    pass


def build(paths: Paths, engine: str = "edge", on_event=_noop,
          reuse_audio: bool = True) -> Result:
    started = time.time()
    require_tools()

    cfg = config_mod.load(paths.config)
    scr = script_mod.load(paths.script)
    script_mod.attach_images(scr, paths.images, cfg.image_naming)
    total = len(scr.cuts)

    font, font_note = fonts.resolve(cfg.subtitle["font"])
    on_event(stage="start", total=total, title=scr.title, font=font)
    if font_note:
        on_event(stage="warn", message=font_note)

    paths.audio.mkdir(parents=True, exist_ok=True)
    paths.clips.mkdir(parents=True, exist_ok=True)
    pad_dir = paths.work / "audio_pad"
    subs_dir = paths.work / "subs"
    for d in (pad_dir, subs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # 1) 음성 생성 + 실제 길이 측정 → 컷 길이 결정
    for i, cut in enumerate(scr.cuts, start=1):
        mp3 = paths.audio / f"{cut.stem}.mp3"
        if not (reuse_audio and mp3.exists() and mp3.stat().st_size > 0):
            tts.synth(cut.narration, mp3, cfg.tts_voice, cfg.tts_rate,
                      engine=engine, cut_label=f"컷 {cut.n}")
        cut.audio = mp3
        cut.words = tts.load_words(mp3)
        cut.audio_sec = probe_duration(mp3)
        cut.frames = video.frames_for(cut.audio_sec + cfg.cut_padding_sec, cfg.fps)
        cut.duration_sec = cut.frames / cfg.fps
        on_event(stage="tts", i=i, total=total, label=cut.stem,
                 seconds=round(cut.duration_sec, 2))

    # 컷 시작 시각 — 자막·효과음이 이 값을 쓴다
    t = 0.0
    for cut in scr.cuts:
        cut.start_sec = t
        t += cut.duration_sec
    total_sec = t

    # 2) 컷별 클립 — 컷끼리 서로 의존하지 않으므로 코어 수만큼 동시에 만든다
    pad_wavs = [video.pad_audio(c.audio, pad_dir / f"{c.stem}.wav", c.duration_sec)
                for c in scr.cuts]

    def make_clip(idx: int):
        cut = scr.cuts[idx]
        # 자막은 카메라가 움직인 뒤에 얹는다. 그래야 글자가 같이 흔들리지 않는다.
        made = subs.build(cut.subtitle, cut.duration_sec, cfg, font,
                          subs_dir / f"{cut.stem}.ass", words=cut.words)
        filters = []
        if made:
            ass, cut.subtitle_exact = made
            filters.append(subs.filter_arg(ass))
        # 페이드는 자막 위에 건다. 화면 전체가 같이 어두워져야 한다.
        fade = video.fade_filter(cut.duration_sec, cfg,
                                 first=idx == 0, last=idx == total - 1)
        if fade:
            filters.append(fade)
        cut.clip = video.build_clip(
            cut.image, pad_wavs[idx], paths.clips / f"{cut.stem}.mp4",
            cfg, cut.motion, cut.frames,
            extra_video=",".join(filters),
        )
        return cut

    done = 0
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        futures = [pool.submit(make_clip, i) for i in range(total)]
        for fut in as_completed(futures):
            cut = fut.result()
            done += 1
            on_event(stage="clip", i=done, total=total, label=cut.stem,
                     seconds=round(cut.duration_sec, 2))

    # 3) 배경음악·효과음
    narration = video.join_audio(pad_wavs, paths.work / "narration.wav", paths.work)
    bgm = audio_mod.find_bgm(paths.assets, scr.bgm)
    sfx = [(audio_mod.find_sfx(paths.assets, c.sfx, c.n), c.start_sec)
           for c in scr.cuts if c.sfx]
    if bgm or sfx:
        on_event(stage="audio", total=total,
                 bgm=bgm.name if bgm else None, sfx=len(sfx))
        full_audio = audio_mod.mix(narration, paths.work / "full_audio.wav",
                                   cfg, total_sec, bgm=bgm, sfx=sfx)
    else:
        full_audio = narration

    # 4) 합치기
    on_event(stage="concat", i=0, total=total)
    video.concat([c.clip for c in scr.cuts], full_audio, paths.final, paths.work)
    on_event(stage="done", total=total, seconds=round(total_sec, 2))

    return Result(
        final=paths.final,
        clips=[c.clip for c in scr.cuts],
        audio=[c.audio for c in scr.cuts],
        total_sec=total_sec,
        elapsed_sec=time.time() - started,
        cuts=scr.cuts,
        title=scr.title,
        bgm=bgm,
        sfx_count=len(sfx),
    )


def inspect(paths: Paths) -> dict:
    """조립 전에 입력이 맞는지 본다. 어떤 그림이 몇 번 컷이 되는지도 함께 돌려준다."""
    cfg = config_mod.load(paths.config)
    scr = script_mod.load(paths.script)
    script_mod.attach_images(scr, paths.images, cfg.image_naming)

    warns = []
    for cut in scr.cuts:
        w, h = probe_size(cut.image)
        if w and h and abs(w / h - 16 / 9) > 0.01:
            warns.append(f"컷 {cut.n} ({w}x{h}) 는 16:9 가 아닙니다 → 검은 여백이 들어갑니다")

    reworded = [c.n for c in scr.cuts if c.subtitle.strip() != c.narration.strip()]
    if reworded:
        nums = ", ".join(str(n) for n in reworded[:8])
        more = f" 외 {len(reworded) - 8}개" if len(reworded) > 8 else ""
        warns.append(
            f"컷 {nums}{more} 은 자막을 나레이션과 다르게 썼습니다.\n"
            "        읽는 말과 화면 글자가 달라 보이고, 자막이 뜨는 시각도 어림잡게 됩니다.\n"
            "        그대로 쓰려면 대본에서 subtitle 을 빼세요."
        )

    return {"script": scr, "warnings": warns, "naming": cfg.image_naming}


def clean(paths: Paths) -> None:
    shutil.rmtree(paths.work, ignore_errors=True)

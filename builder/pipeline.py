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
from . import watermark as wm
from .media import probe_duration, probe_size, require_tools
from .script import ScriptError as ScriptErrorLike


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

    @property
    def shorts(self) -> Path:
        return self.out / "shorts.mp4"


@dataclass
class Result:
    final: Path
    clips: list[Path] = field(default_factory=list)
    audio: list[Path] = field(default_factory=list)
    total_sec: float = 0.0
    elapsed_sec: float = 0.0
    cuts: list[script_mod.Cut] = field(default_factory=list)
    title: str = ""
    font: str = ""
    bgm: Path | None = None
    sfx_count: int = 0



def _strip_watermarks(cuts, cfg, workdir: Path, on_event, total: int) -> None:
    """워터마크를 지운 그림으로 바꿔 둔다. 원본 파일은 건드리지 않는다."""
    if not cfg.watermark.get("remove"):
        return
    clean_dir = workdir / "clean"
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        jobs = {pool.submit(wm.clean, c.image, clean_dir / f"{c.stem}.png", cfg): c
                for c in cuts}
        for job in as_completed(jobs):
            jobs[job].image = job.result()
    on_event(stage="watermark", total=total)

def _noop(**kwargs):
    pass


def decide_fit(cfg, width: int, height: int) -> tuple[str, str]:
    """이 그림을 화면에 어떻게 앉힐지. 돌려주는 둘째 값은 사람이 읽을 설명."""
    if not width or not height:
        return "pad", ""
    want = cfg.width / cfg.height
    got = width / height
    off = abs(got - want) / want * 100
    if off < 0.05:
        return "cover", ""
    if cfg.image_fit == "pad":
        return "pad", f"({width}x{height}) 는 비율이 {off:.1f}% 달라 검은 여백이 들어갑니다"
    if cfg.image_fit == "cover":
        return "cover", f"({width}x{height}) 는 비율이 {off:.1f}% 달라 가장자리를 잘라 채웁니다"
    # auto — 조금 어긋난 정도면 잘라서 채우고, 많이 다르면 그림을 지킨다
    if off <= cfg.crop_tolerance_pct:
        return "cover", f"({width}x{height}) 는 비율이 {off:.1f}% 달라 가장자리를 아주 조금 잘라 채웁니다"
    return "pad", f"({width}x{height}) 는 비율이 {off:.1f}% 달라 검은 여백이 들어갑니다"


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
        fresh_needed = not (reuse_audio and mp3.exists()
                            and mp3.stat().st_size > 0
                            and (engine != "edge" or tts.matches_settings(
                                mp3, cfg.tts_voice, cfg.tts_rate, cfg.tts_pitch)))
        if fresh_needed:
            tts.synth(cut.narration, mp3, cfg.tts_voice, cfg.tts_rate,
                      cfg.tts_pitch, engine=engine, cut_label=f"컷 {cut.n}")
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

    # 엔딩 카드는 마지막에 3초 붙는다. 배경음악이 여기까지 덮어야 한다.
    card_text = scr.ending_card if cfg.ending_card_sec > 0 else None
    card_frames = video.frames_for(cfg.ending_card_sec, cfg.fps) if card_text else 0
    card_sec = card_frames / cfg.fps if card_text else 0.0
    total_sec = t + card_sec

    # 2) 컷별 클립 — 컷끼리 서로 의존하지 않으므로 코어 수만큼 동시에 만든다
    tone = audio_mod.NARRATION_TONE[cfg.narration_tone]
    pad_wavs = [video.pad_audio(c.audio, pad_dir / f"{c.stem}.wav",
                                c.duration_sec, tone)
                for c in scr.cuts]

    _strip_watermarks(scr.cuts, cfg, paths.work, on_event, total)

    fit_of = {c.n: decide_fit(cfg, *probe_size(c.image))[0] for c in scr.cuts}

    def make_clip(idx: int):
        cut = scr.cuts[idx]
        # 자막은 카메라가 움직인 뒤에 얹는다. 그래야 글자가 같이 흔들리지 않는다.
        made = subs.build(cut.subtitle, cut.duration_sec, cfg, font,
                          subs_dir / f"{cut.stem}.ass", words=cut.words)
        filters = []
        if made:
            ass, cut.subtitle_exact = made
            if not cut.subtitle_exact:
                cut.timing_note = subs.why_estimated()
                if not cut.words:
                    kinds = tts.stream_kinds(cut.audio)
                    cut.timing_note += f" · 받은 응답 종류: {kinds or '기록 없음'}"
            filters.append(subs.filter_arg(ass))
        # 페이드는 자막 위에 건다. 화면 전체가 같이 어두워져야 한다.
        fade = video.fade_filter(
            cut.duration_sec, cfg, first=idx == 0,
            # 엔딩 카드가 있으면 어둠으로 잠기는 건 카드 쪽이다
            last=idx == total - 1 and not card_text)
        if fade:
            filters.append(fade)
        cut.clip = video.build_clip(
            cut.image, pad_wavs[idx], paths.clips / f"{cut.stem}.mp4",
            cfg, cut.motion, cut.frames,
            extra_video=",".join(filters), fit=fit_of[cut.n],
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

    # 2-b) 엔딩 카드
    clips = [c.clip for c in scr.cuts]
    if card_text:
        on_event(stage="ending", total=total, seconds=round(card_sec, 2))
        card_ass = subs.build_card(card_text, card_sec, cfg, font,
                                   subs_dir / "ending.ass")
        card_filters = [subs.filter_arg(card_ass)] if card_ass else []
        card_fade = video.fade_filter(card_sec, cfg, first=False, last=True)
        if card_fade:
            card_filters.append(card_fade)
        card_wav = video.silent_audio(pad_dir / "ending.wav", card_sec)
        pad_wavs.append(card_wav)
        clips.append(video.build_clip(
            video.black_frame(cfg, paths.work / "ending_bg.png"),
            card_wav, paths.clips / "ending.mp4", cfg, "zoom_in", card_frames,
            extra_video=",".join(card_filters),
        ))

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
    video.concat(clips, full_audio, paths.final, paths.work)
    on_event(stage="done", total=total, seconds=round(total_sec, 2))

    return Result(
        final=paths.final,
        clips=clips,
        audio=[c.audio for c in scr.cuts],
        total_sec=total_sec,
        elapsed_sec=time.time() - started,
        cuts=scr.cuts,
        title=scr.title,
        font=font,
        bgm=bgm,
        sfx_count=len(sfx),
    )


def parse_cuts(spec: str, total: int) -> list[int]:
    """'3-8' 이나 '3,4,7' 을 컷 번호로 푼다."""
    nums: list[int] = []
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part[1:]:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise ScriptErrorLike(f"컷 범위를 알아볼 수 없습니다: {part}")
            if lo > hi:
                lo, hi = hi, lo
            nums.extend(range(lo, hi + 1))
        else:
            try:
                nums.append(int(part))
            except ValueError:
                raise ScriptErrorLike(f"컷 번호를 알아볼 수 없습니다: {part}")

    seen, out = set(), []
    for n in nums:
        if not 1 <= n <= total:
            raise ScriptErrorLike(f"컷 {n} 은 없습니다. 대본은 1~{total} 컷입니다.")
        if n not in seen:
            seen.add(n)
            out.append(n)
    if not out:
        raise ScriptErrorLike("쇼츠로 뽑을 컷을 지정하세요. 예: 3-8")
    return out


def build_shorts(paths: Paths, spec: str, engine: str = "edge",
                 on_event=_noop, reuse_audio: bool = True) -> Result:
    """고른 컷만 9:16 세로로 다시 만들어 쇼츠 한 편으로 잇는다.

    롱폼에서 잘라내는 게 아니라 세로 화면에 맞춰 새로 그린다. 그래야 자막이
    세로 화면에서도 읽을 만한 크기로 들어간다.
    """
    started = time.time()
    require_tools()

    cfg = config_mod.load(paths.config)
    scr = script_mod.load(paths.script)
    script_mod.attach_images(scr, paths.images, cfg.image_naming)
    font, font_note = fonts.resolve(cfg.subtitle["font"])
    if font_note:
        on_event(stage="notice", message=font_note)

    sh = cfg.shorts
    vcfg = cfg.variant(
        resolution=sh["resolution"],
        subtitle={**cfg.subtitle,
                  "size": sh["subtitle_size"],
                  "max_chars_per_line": sh["max_chars_per_line"],
                  "max_width_pct": sh["max_width_pct"]},
    )

    wanted = parse_cuts(spec, len(scr.cuts))
    cap = float(sh["max_seconds"])

    work = paths.work / "shorts"
    pad_dir, subs_dir = work / "audio_pad", work / "subs"
    for d in (paths.audio, work, pad_dir, subs_dir):
        d.mkdir(parents=True, exist_ok=True)

    picked, dropped, used = [], [], 0.0
    for n in wanted:
        cut = scr.cuts[n - 1]
        mp3 = paths.audio / f"{cut.stem}.mp3"
        fresh_needed = not (reuse_audio and mp3.exists()
                            and mp3.stat().st_size > 0
                            and (engine != "edge" or tts.matches_settings(
                                mp3, cfg.tts_voice, cfg.tts_rate, cfg.tts_pitch)))
        if fresh_needed:
            tts.synth(cut.narration, mp3, cfg.tts_voice, cfg.tts_rate,
                      cfg.tts_pitch, engine=engine, cut_label=f"컷 {cut.n}")
        cut.audio = mp3
        cut.words = tts.load_words(mp3)
        cut.audio_sec = probe_duration(mp3)
        cut.frames = video.frames_for(cut.audio_sec + cfg.cut_padding_sec, cfg.fps)
        cut.duration_sec = cut.frames / cfg.fps

        if picked and used + cut.duration_sec > cap:
            dropped.append(cut.n)
            continue
        picked.append(cut)
        used += cut.duration_sec

    if dropped:
        on_event(stage="notice", message=(
            f"{cap:.0f}초를 넘어 컷 {', '.join(str(n) for n in dropped)} 은 뺐습니다. "
            f"넣은 컷: {', '.join(str(c.n) for c in picked)}"))

    total = len(picked)
    on_event(stage="start", total=total, title=f"{scr.title} · 쇼츠", font=font)

    tone = audio_mod.NARRATION_TONE[cfg.narration_tone]
    pad_wavs = [video.pad_audio(c.audio, pad_dir / f"{c.stem}.wav",
                                c.duration_sec, tone)
                for c in picked]

    _strip_watermarks(picked, cfg, work, on_event, total)

    def make(idx: int):
        cut = picked[idx]
        made = subs.build(cut.subtitle, cut.duration_sec, vcfg, font,
                          subs_dir / f"{cut.stem}.ass", words=cut.words)
        filters = []
        if made:
            ass, cut.subtitle_exact = made
            filters.append(subs.filter_arg(ass))
        fade = video.fade_filter(cut.duration_sec, vcfg,
                                 first=idx == 0, last=idx == total - 1)
        if fade:
            filters.append(fade)
        fit = decide_fit(cfg, *probe_size(cut.image))[0]
        clip = video.build_clip(
            cut.image, pad_wavs[idx], work / f"{cut.stem}.mp4",
            vcfg, cut.motion, cut.frames, extra_video=",".join(filters),
            graph=video.vertical_graph(cut.motion, vcfg, cut.frames, fit),
        )
        return idx, clip

    clips: list[Path | None] = [None] * total
    done = 0
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        for fut in as_completed([pool.submit(make, i) for i in range(total)]):
            idx, clip = fut.result()
            clips[idx] = clip
            done += 1
            on_event(stage="clip", i=done, total=total, label=picked[idx].stem,
                     seconds=round(picked[idx].duration_sec, 2))

    narration = video.join_audio(pad_wavs, work / "narration.wav", work)
    bgm = audio_mod.find_bgm(paths.assets, scr.bgm)
    sfx = [(audio_mod.find_sfx(paths.assets, c.sfx, c.n), c.start_sec)
           for c in picked if c.sfx]
    if bgm:
        full_audio = audio_mod.mix(narration, work / "full_audio.wav",
                                   cfg, used, bgm=bgm, sfx=[])
    else:
        full_audio = narration

    on_event(stage="concat", i=0, total=total)
    video.concat(clips, full_audio, paths.shorts, work)
    on_event(stage="done", total=total, seconds=round(used, 2))

    return Result(
        final=paths.shorts,
        clips=clips,
        audio=[c.audio for c in picked],
        total_sec=used,
        elapsed_sec=time.time() - started,
        cuts=picked,
        title=f"{scr.title} · 쇼츠",
        font=font,
        bgm=bgm,
        sfx_count=0,
    )


def inspect(paths: Paths) -> dict:
    """조립 전에 입력이 맞는지 본다. 어떤 그림이 몇 번 컷이 되는지도 함께 돌려준다."""
    cfg = config_mod.load(paths.config)
    scr = script_mod.load(paths.script)
    script_mod.attach_images(scr, paths.images, cfg.image_naming)

    warns, fits = [], {}
    for cut in scr.cuts:
        fit, note = decide_fit(cfg, *probe_size(cut.image))
        fits.setdefault((fit, note), []).append(cut.n)
    for (fit, note), nums in fits.items():
        if note:
            warns.append(f"컷 {nums[0]}~{nums[-1]} ({len(nums)}장) {note}"
                         if len(nums) > 2 else
                         f"컷 {', '.join(map(str, nums))} {note}")

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

#!/usr/bin/env python3
"""신들의 사생활 빌더 — CLI.

  python3 build.py                     기본 경로로 조립
  python3 build.py --check             입력만 점검하고 끝
  python3 build.py --voice-sample      남성·여성 목소리 비교 파일 생성
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from builder import pipeline, tts
from builder.config import ConfigError
from builder.media import MediaError
from builder.script import ScriptError

ROOT = Path(__file__).resolve().parent
SAMPLE_LINE = "아무것도 없었습니다. 진짜로, 아무것도요. 하늘도, 땅도, 시간마저도."

STAGE_NAMES = {"tts": "음성 생성", "clip": "클립 생성", "concat": "합치기"}


def fmt_time(sec: float) -> str:
    m, s = divmod(int(round(sec)), 60)
    return f"{m}분 {s:02d}초"


def make_reporter():
    def report(**e):
        stage = e.get("stage")
        if stage == "start":
            print(f"  대본: {e['title']}  ({e['total']}컷)\n")
        elif stage in STAGE_NAMES and stage != "concat":
            print(f"  {STAGE_NAMES[stage]}  {e['i']:>2}/{e['total']}  "
                  f"{e['label']}  {e['seconds']:.2f}초", flush=True)
        elif stage == "concat":
            print("\n  합치는 중...", flush=True)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="신들의 사생활 빌더")
    ap.add_argument("--script", default="input/script.json", help="대본 JSON 경로")
    ap.add_argument("--images", default="input/images", help="이미지 폴더 경로")
    ap.add_argument("--config", default="config.json", help="설정 파일 경로")
    ap.add_argument("--out", default="output", help="출력 폴더")
    ap.add_argument("--tts", default="edge", choices=["edge", "espeak"],
                    help="음성 엔진 (기본 edge-tts)")
    ap.add_argument("--fresh", action="store_true", help="이미 만든 음성도 다시 생성")
    ap.add_argument("--check", action="store_true", help="입력 점검만 하고 종료")
    ap.add_argument("--voice-sample", action="store_true",
                    help="남성·여성 목소리 샘플만 생성")
    args = ap.parse_args()

    paths = pipeline.Paths(
        root=ROOT,
        images=Path(args.images) if Path(args.images).is_absolute() else ROOT / args.images,
        script=Path(args.script) if Path(args.script).is_absolute() else ROOT / args.script,
        config=Path(args.config) if Path(args.config).is_absolute() else ROOT / args.config,
        out=Path(args.out) if Path(args.out).is_absolute() else ROOT / args.out,
    )

    try:
        if args.voice_sample:
            print("\n목소리 샘플을 만듭니다...\n")
            made = tts.make_voice_samples(paths.out / "voice_samples", SAMPLE_LINE)
            for p in made:
                print(f"  {p}")
            print("\n두 파일을 들어 보고 마음에 드는 쪽 목소리 이름을")
            print("config.json 의 tts_voice 에 넣으세요.\n")
            return 0

        print("\n입력 점검...")
        info = pipeline.inspect(paths)
        scr = info["script"]
        for w in info["warnings"]:
            print(f"  알림  {w}")

        if info["naming"] == "ordered":
            print("\n  파일명 순서대로 컷을 배정했습니다. 맞는지 확인하세요.")
            for cut in scr.cuts:
                print(f"    컷 {cut.n:>2}  ←  {cut.image.name}")

        print(f"  이상 없음 — {len(scr.cuts)}컷, "
              f"나레이션 {scr.total_narration_chars}자\n")
        if args.check:
            return 0
        res = pipeline.build(paths, engine=args.tts, on_event=make_reporter(),
                             reuse_audio=not args.fresh)

        print("\n" + "-" * 52)
        print(f"  완성      {res.final}")
        print(f"  총 컷     {len(res.cuts)}개")
        print(f"  총 길이   {fmt_time(res.total_sec)}")
        print(f"  처리 시간 {fmt_time(res.elapsed_sec)}")
        print(f"  컷별 클립 {paths.clips}")
        print(f"  컷별 음성 {paths.audio}")
        print("-" * 52 + "\n")
        return 0

    except (ScriptError, ConfigError, MediaError, tts.TTSError) as e:
        print(f"\n[중단] {e}\n", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

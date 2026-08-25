#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
캡컷 드래프트 생성기 — 「신들의 사생활」

대본(script.json)과 이미지 폴더를 넣으면, 캡컷을 열었을 때 이미 다 배치되어 있는
프로젝트(드래프트)를 만들어 준다.

    python make_capcut_draft.py --script script.json --images ./images --name "신들의사생활_1화"

이 프로그램이 하는 일 / 하지 않는 일
------------------------------------
하는 일   : 이미지 순서대로 배치, 컷 길이 계산, 자막 텍스트 입력, 줌·패닝 키프레임
하지 않음 : 음성 합성(캡컷의 '텍스트 읽기'가 더 낫다), 자막 스타일, BGM, 영상 렌더링

* 음성 라이브러리(edge-tts, gTTS 등)를 절대 쓰지 않는다. 목소리는 캡컷 안에서
  사람이 바꿀 수 있어야 하기 때문이다.
* 영상 렌더링도 하지 않는다. 프로젝트 파일만 쓴다.

필요한 것: pip install pycapcut
"""

import argparse
import json
import os
import re
import shutil
import sys
import unicodedata

# ─────────────────────────────────────────────────────────────────────────────
# 기본 설정값 — config 파일로 덮어쓸 수 있다
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    # 초당 낭독 글자 수. 1화에서 실측한 값.
    # 캡컷이 만든 음성이 자막보다 '길면' 이 값을 낮추고, '짧으면' 높인 뒤 다시 돌린다.
    "chars_per_second": 5.5,
    # 말이 끝난 뒤 여백(초). 이미지가 음성보다 이만큼 길어야 컷 전환이 급해 보이지 않는다.
    "tail_padding": 0.5,
    # 줌·패닝에 쓰는 확대 배율. 1.15를 넘기지 않는다(정지 이미지라 화질이 무너진다).
    "zoom_scale": 1.08,
    # 28번 이미지를 몇 초 더 끌고 갈지. 이 위에 엔딩카드가 올라간다.
    "ending_card_seconds": 5.0,
    # 패닝 총 이동량(화면 폭/높이의 %). 크게 움직이면 정지 이미지 티가 난다.
    "pan_percent": 4.0,
    # 엔딩카드 텍스트가 화면에 떠 있는 시간(초). 이미지보다 조금 짧게 끝낸다.
    "ending_card_text_seconds": 4.7,
    # 자막 세로 위치 — 화면 아래에서 몇 % 지점에 둘지 (12~15 권장)
    "subtitle_bottom_percent": 13.0,
    # 드래프트 해상도 / 프레임레이트
    "width": 1920,
    "height": 1080,
    "fps": 30,
}

# 확대 배율 상한 — 이 값을 넘으면 정지 이미지의 화질이 무너진다
MAX_ZOOM_SCALE = 1.15

# 대본에서 허용하는 모션 값 6종
VALID_MOTIONS = ("zoom_in", "zoom_out", "pan_up", "pan_down", "pan_left", "pan_right")

# 트랙 이름 — 캡컷 화면에 이 이름으로 보인다
TRACK_IMAGE = "이미지"
TRACK_SUBTITLE = "자막A"      # 텍스트 읽기를 돌릴 트랙
TRACK_ENDING = "엔딩카드B"    # 텍스트 읽기에 휩쓸리면 안 되는 트랙
TRACK_NARRATION = "나레이션"  # 비워 둔다 (텍스트 읽기 결과가 여기 들어온다)
TRACK_BGM = "BGM"             # 비워 둔다

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


# ─────────────────────────────────────────────────────────────────────────────
# 작은 도우미들
# ─────────────────────────────────────────────────────────────────────────────
def die(message):
    """치명적 오류 — 어디서 왜 멈췄는지 반드시 남기고 끝낸다."""
    print("\n[중단] " + message, file=sys.stderr)
    sys.exit(1)


def fmt_clock(seconds):
    """324.41 → '5:24.4' 형태로."""
    m = int(seconds // 60)
    s = seconds - m * 60
    # 반올림하면 338.55초가 '5:38.6'으로 보인다. 검산표와 맞추려고 버림한다.
    s = int(s * 10 + 1e-9) / 10.0
    return "%d:%04.1f" % (m, s)


def fmt_srt_time(seconds):
    """SRT용 '00:05:24,410' 형태로."""
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def first_int(name):
    """파일 이름에서 처음 나오는 정수를 뽑는다.

    '01.png' → 1,  '컷_10_·_어머니의_눈_202608220622.jpeg' → 10
    두 자리 0채움('01.png')이든 한글 제목이든 둘 다 이걸로 정렬된다.
    숫자가 없으면 None.
    """
    m = re.search(r"\d+", name)
    return int(m.group()) if m else None


# ─────────────────────────────────────────────────────────────────────────────
# 1단계 — 설정 읽기
# ─────────────────────────────────────────────────────────────────────────────
def load_config(path):
    """설정 파일을 읽어 기본값 위에 덮어쓴다. 파일이 없으면 기본값으로 하나 만들어 둔다.

    모르는 키는 조용히 무시한다 — 다른 용도의 config 파일을 가리켜도 망가지지 않게.
    """
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                user = json.load(f)
        except Exception as e:
            die("설정 파일을 읽지 못했습니다: %s\n       %s" % (path, e))
        if not isinstance(user, dict):
            die("설정 파일의 최상위가 객체(JSON object)가 아닙니다: %s" % path)
        used = []
        for k, v in user.items():
            if k in cfg:
                cfg[k] = v
                used.append(k)
        print("설정 파일 : %s  (적용된 항목 %d개: %s)"
              % (path, len(used), ", ".join(used) if used else "없음"))
    else:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
                f.write("\n")
            print("설정 파일 : %s  (없어서 기본값으로 새로 만들었습니다)" % path)
        except Exception as e:
            print("설정 파일 : 기본값 사용 (파일을 만들지 못했습니다: %s)" % e)

    # 값 검사 — 여기서 막지 않으면 나중에 이유를 알 수 없는 결과가 나온다
    if not (cfg["chars_per_second"] > 0):
        die("chars_per_second 는 0보다 커야 합니다 (현재 %r)" % cfg["chars_per_second"])
    if cfg["zoom_scale"] > MAX_ZOOM_SCALE:
        die("zoom_scale 이 %.2f 를 넘습니다 (현재 %r). 정지 이미지라 확대하면 화질이 무너집니다."
            % (MAX_ZOOM_SCALE, cfg["zoom_scale"]))
    if cfg["zoom_scale"] < 1.0:
        die("zoom_scale 은 1.0 이상이어야 합니다 (현재 %r)" % cfg["zoom_scale"])
    return cfg


# ─────────────────────────────────────────────────────────────────────────────
# 2단계 — 대본 읽기
# ─────────────────────────────────────────────────────────────────────────────
def load_script(path):
    """script.json 을 읽고 구조를 검사한다.

    subtitle 은 28컷 전부 narration 과 문자열이 같으므로 narration 만 쓴다.
    accent_color 는 이미지 생성용이라 여기서는 쓰지 않는다.
    """
    if not os.path.exists(path):
        die("대본 파일이 없습니다: %s" % path)
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as e:
        die("대본 파일을 읽지 못했습니다: %s\n       %s" % (path, e))

    cuts = data.get("cuts")
    if not isinstance(cuts, list) or not cuts:
        die("대본에 cuts 배열이 없습니다: %s" % path)

    for i, c in enumerate(cuts):
        where = "cuts[%d]" % i
        if not isinstance(c, dict):
            die("%s 가 객체가 아닙니다." % where)
        n = c.get("n", i + 1)
        narration = c.get("narration")
        if not isinstance(narration, str) or not narration.strip():
            die("컷 %s (%s) 의 narration 이 비어 있습니다." % (n, where))
        motion = c.get("motion")
        if motion not in VALID_MOTIONS:
            die("컷 %s (%s) 의 motion 값이 이상합니다: %r\n       쓸 수 있는 값: %s"
                % (n, where, motion, ", ".join(VALID_MOTIONS)))
        # subtitle 이 narration 과 다르면 알려만 주고 narration 을 쓴다
        sub = c.get("subtitle")
        if isinstance(sub, str) and sub.strip() and sub != narration:
            print("  [알림] 컷 %s: subtitle 이 narration 과 다릅니다. narration 을 씁니다." % n)

    ending = data.get("ending_card")
    if not isinstance(ending, str) or not ending.strip():
        print("  [알림] ending_card 가 없습니다. 엔딩카드 트랙을 만들지 않습니다.")
        ending = None

    return {
        "title": data.get("title", ""),
        "cuts": cuts,
        "ending_card": ending,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3단계 — 이미지 정렬 (여기서 어긋나면 그 뒤가 전부 무너진다)
# ─────────────────────────────────────────────────────────────────────────────
def collect_images(images_dir, expected_count):
    """이미지 폴더를 훑어 컷 순서대로 정렬한다.

    파일 이름 안의 '첫 번째 숫자'를 컷 번호로 본다.
      '01.png'                              → 1
      '컷_10_·_어머니의_눈_2026....jpeg'      → 10
    숫자가 없는 파일이 섞여 있으면 이름순으로 뒤에 붙이고 경고한다.
    """
    if not os.path.isdir(images_dir):
        die("이미지 폴더가 없습니다: %s" % images_dir)

    # 주의: 맥에서 만든 한글 파일명은 자소 분리(NFD)로 저장돼 있을 수 있다.
    #       os.listdir 이 준 문자열을 그대로 써야 파일을 찾을 수 있으므로
    #       정규화한 이름은 '보여주기'에만 쓴다.
    names = [f for f in os.listdir(images_dir)
             if not f.startswith(".") and os.path.splitext(f)[1].lower() in IMAGE_EXTS]
    if not names:
        die("이미지 폴더에 이미지가 하나도 없습니다: %s\n       지원 확장자: %s"
            % (images_dir, ", ".join(IMAGE_EXTS)))

    numbered, unnumbered = [], []
    for f in names:
        k = first_int(f)
        (numbered if k is not None else unnumbered).append((k, f))

    numbered.sort(key=lambda t: (t[0], t[1]))
    unnumbered.sort(key=lambda t: t[1])
    if unnumbered:
        print("  [경고] 이름에 숫자가 없는 이미지 %d개는 이름순으로 맨 뒤에 붙입니다."
              % len(unnumbered))

    ordered = [f for _, f in numbered] + [f for _, f in unnumbered]

    # 같은 번호가 두 번 나오면 순서를 믿을 수 없다
    seen = {}
    for k, f in numbered:
        seen.setdefault(k, []).append(f)
    dups = {k: v for k, v in seen.items() if len(v) > 1}
    if dups:
        print("  [경고] 같은 번호를 가진 이미지가 있습니다. 순서를 꼭 확인하세요:")
        for k in sorted(dups):
            for f in dups[k]:
                print("         %s → %s" % (k, unicodedata.normalize("NFC", f)))

    if len(ordered) != expected_count:
        die("이미지 개수가 컷 개수와 다릅니다. 이미지 %d장 / 컷 %d개\n"
            "       폴더: %s" % (len(ordered), expected_count, images_dir))

    return [os.path.join(images_dir, f) for f in ordered]


def confirm_order(cuts, image_paths, auto_yes):
    """정렬 결과를 화면에 뿌리고 사람의 확인을 받는다.

    순서가 어긋나면 그 뒤가 전부 무너지는데, 드래프트가 만들어진 뒤에는
    알아채기 어렵다. 그래서 이 확인만은 생략하지 않는다.
    """
    print("")
    print("─" * 78)
    print("이미지 ↔ 컷 짝짓기 결과 — 순서가 맞는지 확인해 주세요")
    print("─" * 78)
    print("%-4s %-46s %s" % ("컷", "이미지 파일", "나레이션 앞부분"))
    print("─" * 78)
    for c, p in zip(cuts, image_paths):
        fname = unicodedata.normalize("NFC", os.path.basename(p))
        if len(fname) > 44:
            fname = fname[:41] + "..."
        head = c["narration"][:20].replace("\n", " ")
        print("%-4s %-46s %s…" % (c.get("n"), fname, head))
    print("─" * 78)

    if auto_yes:
        print("--yes 가 켜져 있어 확인 없이 진행합니다.")
        return
    if not sys.stdin.isatty():
        die("이미지 순서 확인이 필요한데 입력을 받을 수 없습니다.\n"
            "       위 표를 눈으로 확인한 뒤 --yes 를 붙여 다시 실행하세요.")
    try:
        answer = input("\n이 순서가 맞습니까? 진행하려면 y 를 누르세요 [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        die("확인이 취소되었습니다.")
    if answer not in ("y", "yes"):
        die("사용자가 순서를 승인하지 않아 중단합니다. 이미지 파일 이름을 고친 뒤 다시 실행하세요.")


# ─────────────────────────────────────────────────────────────────────────────
# 4단계 — 컷 길이 계산
# ─────────────────────────────────────────────────────────────────────────────
def build_timeline(cuts, cfg):
    """컷 길이 = (나레이션 글자 수 ÷ chars_per_second) + tail_padding

    캡컷이 음성을 만들기 전이라 실제 길이를 알 수 없으므로 글자 수로 추정한다.
    소수 둘째 자리에서 반올림한 값을 그대로 누적한다(검산표와 맞추기 위해).
    """
    cps = float(cfg["chars_per_second"])
    pad = float(cfg["tail_padding"])

    rows, cursor = [], 0.0
    for c in cuts:
        chars = len(c["narration"])
        dur = round(chars / cps + pad, 2)
        rows.append({
            "n": c.get("n"),
            "chars": chars,
            "duration": dur,
            "start": round(cursor, 2),
            "end": round(cursor + dur, 2),
            "motion": c["motion"],
            "narration": c["narration"],
        })
        cursor = round(cursor + dur, 2)

    body_total = round(cursor, 2)

    # 마지막 이미지는 엔딩카드가 올라갈 만큼 더 끌고 간다
    tail = float(cfg["ending_card_seconds"])
    for r in rows:
        r["image_end"] = r["end"]
    if rows and tail > 0:
        rows[-1]["image_end"] = round(rows[-1]["end"] + tail, 2)

    return rows, body_total, round(body_total + tail, 2)


def print_timeline_check(rows, body_total, grand_total):
    """검산값 출력 — 계산식이 맞게 짜였는지 사람이 바로 대조할 수 있게."""
    shortest = min(rows, key=lambda r: r["duration"])
    longest = max(rows, key=lambda r: r["duration"])
    last = rows[-1]
    print("")
    print("컷 길이 검산")
    print("  컷 1 길이        : %.2f초" % rows[0]["duration"])
    print("  최단 컷          : 컷 %s / %.2f초" % (shortest["n"], shortest["duration"]))
    print("  최장 컷          : 컷 %s / %.2f초" % (longest["n"], longest["duration"]))
    print("  마지막 컷 시작   : %s (%.2f초)" % (fmt_clock(last["start"]), last["start"]))
    print("  본편 총 길이     : %.2f초 (%s)" % (body_total, fmt_clock(body_total)))
    print("  엔딩카드 포함    : %.2f초 (%s)" % (grand_total, fmt_clock(grand_total)))


# ─────────────────────────────────────────────────────────────────────────────
# 5단계 — 캡컷 드래프트 폴더 찾기
# ─────────────────────────────────────────────────────────────────────────────
def find_draft_folder():
    """이 컴퓨터에 설치된 캡컷의 드래프트 폴더를 찾는다. 못 찾으면 None."""
    home = os.path.expanduser("~")
    candidates = []
    if sys.platform.startswith("win"):
        local = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        candidates += [
            os.path.join(local, "CapCut", "User Data", "Projects", "com.lveditor.draft"),
            os.path.join(local, "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        ]
    elif sys.platform == "darwin":
        candidates += [
            os.path.join(home, "Movies", "CapCut", "User Data", "Projects", "com.lveditor.draft"),
            os.path.join(home, "Movies", "JianyingPro", "User Data", "Projects", "com.lveditor.draft"),
        ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 6단계 — 드래프트 조립
# ─────────────────────────────────────────────────────────────────────────────
def apply_motion(seg, motion, duration_us, cfg):
    """컷의 motion 값에 따라 줌·패닝 키프레임을 건다.

    캡컷 좌표계 주의:
      - 위치 단위는 '화면의 절반'. 즉 값 1.0 = 화면 폭의 50%.
        그래서 화면 폭의 4%를 움직이려면 총 이동값이 0.08 이어야 한다(가운데 기준 ±0.04).
      - position_y 는 위로 갈수록 양수.
    """
    from pycapcut import KeyframeProperty

    scale = float(cfg["zoom_scale"])
    # 총 이동량(화면 폭/높이의 %) → 캡컷 값. 단위가 '화면의 절반'이라 %값에 2를 곱하고,
    # 그걸 가운데 기준 좌우(위아래)로 절반씩 나눠 쓰므로 결국 %값 그대로가 한쪽 몫이 된다.
    half = float(cfg["pan_percent"]) / 100.0
    t0, t1 = 0, int(duration_us)

    if motion == "zoom_in":
        seg.add_keyframe(KeyframeProperty.uniform_scale, t0, 1.0)
        seg.add_keyframe(KeyframeProperty.uniform_scale, t1, scale)
    elif motion == "zoom_out":
        seg.add_keyframe(KeyframeProperty.uniform_scale, t0, scale)
        seg.add_keyframe(KeyframeProperty.uniform_scale, t1, 1.0)
    elif motion in ("pan_up", "pan_down", "pan_left", "pan_right"):
        # 패닝은 확대 배율을 고정해 둔 채(=clip_settings 에서 이미 지정) 위치만 움직인다.
        # 확대해 둔 만큼 화면 밖으로 나간 여백 안에서만 움직이므로 검은 테두리가 생기지 않는다.
        if motion == "pan_up":       # 아래 → 위
            prop, a, b = KeyframeProperty.position_y, -half, +half
        elif motion == "pan_down":   # 위 → 아래
            prop, a, b = KeyframeProperty.position_y, +half, -half
        elif motion == "pan_left":   # 오른쪽 → 왼쪽
            prop, a, b = KeyframeProperty.position_x, +half, -half
        else:                        # pan_right: 왼쪽 → 오른쪽
            prop, a, b = KeyframeProperty.position_x, -half, +half
        seg.add_keyframe(prop, t0, a)
        seg.add_keyframe(prop, t1, b)
    else:
        raise ValueError("모르는 motion 값: %r" % motion)


def build_draft(script, rows, image_paths, cfg, draft_root, draft_name, allow_replace):
    """드래프트를 만들고 저장한다. 저장된 폴더 경로를 돌려준다."""
    from pycapcut import (ClipSettings, DraftFolder, TextSegment, TextStyle,
                          TrackType, VideoSegment, trange)

    if not os.path.isdir(draft_root):
        os.makedirs(draft_root, exist_ok=True)

    folder = DraftFolder(draft_root)
    if folder.has_draft(draft_name) and not allow_replace:
        die("같은 이름의 프로젝트가 이미 있습니다: %s\n"
            "       덮어쓰려면 --replace 를 붙이거나 --name 을 바꾸세요."
            % os.path.join(draft_root, draft_name))

    # 최신 캡컷은 기존 draft_content.json 이 암호화되어 있어 템플릿으로 읽어올 수 없다.
    # 그래서 항상 '새 드래프트 생성'만 쓴다. 기존 프로젝트는 건드리지 않는다.
    script_file = folder.create_draft(
        draft_name, int(cfg["width"]), int(cfg["height"]), int(cfg["fps"]),
        allow_replace=True,
    )

    # 트랙 순서: 아래에서 위로 이미지 → 자막A → 엔딩카드B.
    # 오디오 두 줄은 비워 둔다 — 캡컷의 '텍스트 읽기'가 만든 음성과 BGM 자리.
    script_file.add_track(TrackType.video, TRACK_IMAGE)
    script_file.add_track(TrackType.audio, TRACK_NARRATION)
    script_file.add_track(TrackType.audio, TRACK_BGM)
    script_file.add_track(TrackType.text, TRACK_SUBTITLE)
    if script["ending_card"]:
        script_file.add_track(TrackType.text, TRACK_ENDING)

    scale = float(cfg["zoom_scale"])
    # 자막 세로 위치: 화면 아래에서 N% 지점. 단위가 '화면 높이의 절반'이라 이렇게 환산한다.
    sub_y = -(0.5 - float(cfg["subtitle_bottom_percent"]) / 100.0) * 2.0
    total = len(rows)
    motion_failures = []

    for idx, (row, img) in enumerate(zip(rows, image_paths), start=1):
        n = row["n"]
        try:
            # ── 이미지 클립 ──────────────────────────────────────────────
            img_dur = row["image_end"] - row["start"]
            # 패닝 컷은 확대 배율을 처음부터 고정해 둔다. 줌 컷은 키프레임이 배율을 맡는다.
            if row["motion"].startswith("pan_"):
                clip = ClipSettings(scale_x=scale, scale_y=scale)
            else:
                clip = ClipSettings()
            seg = VideoSegment(
                img,
                trange("%.3fs" % row["start"], "%.3fs" % img_dur),  # 두 번째 인자는 '지속 시간'
                clip_settings=clip,
            )

            # ── 줌·패닝 ─────────────────────────────────────────────────
            # 키프레임이 막히더라도 배치와 자막은 살린다. 줌은 캡컷 프리셋으로 대체 가능하다.
            try:
                # 초 단위로 다시 곱하면 부동소수 오차가 남는다. 클립이 실제로 쓰는 마이크로초를 그대로 쓴다.
                apply_motion(seg, row["motion"], seg.duration, cfg)
            except Exception as e:
                motion_failures.append((n, row["motion"], str(e)))

            script_file.add_segment(seg, TRACK_IMAGE)

            # ── 자막 ────────────────────────────────────────────────────
            # 시작 시각과 길이를 이미지 클립과 정확히 맞춘다. 캡컷에서 이 트랙을
            # 통째로 선택해 '텍스트 읽기'를 돌리면 음성이 이 위치를 그대로 따라간다.
            # 폰트는 지정하지 않는다 — pycapcut 의 FontType 은 중문 위주라 한글이 깨진다.
            text = TextSegment(
                row["narration"],
                trange("%.3fs" % row["start"], "%.3fs" % row["duration"]),
                style=TextStyle(align=1, auto_wrapping=True),
                clip_settings=ClipSettings(transform_y=sub_y),
            )
            script_file.add_segment(text, TRACK_SUBTITLE)

            print("[%d/%d] 컷 %s 배치 (%.2f초, %s)" % (idx, total, n, row["duration"], row["motion"]))

        except Exception as e:
            die("컷 %s 을(를) 배치하다 실패했습니다.\n"
                "       이미지: %s\n"
                "       사유  : %s: %s" % (n, img, type(e).__name__, e))

    # ── 엔딩카드 (별도 트랙) ────────────────────────────────────────────
    # 트랙을 나누는 이유: 자막A 를 전체 선택해 음성 변환할 때 엔딩카드까지 읽히면 안 된다.
    if script["ending_card"]:
        body_end = rows[-1]["end"]
        card_dur = float(cfg["ending_card_text_seconds"])
        try:
            card = TextSegment(
                script["ending_card"],
                trange("%.3fs" % body_end, "%.3fs" % card_dur),
                style=TextStyle(align=1, auto_wrapping=True),
                clip_settings=ClipSettings(),  # 화면 중앙
            )
            script_file.add_segment(card, TRACK_ENDING)
            print("[엔딩] 엔딩카드 배치 (%.2f초부터 %.2f초간)" % (body_end, card_dur))
        except Exception as e:
            die("엔딩카드를 배치하다 실패했습니다.\n       사유: %s: %s" % (type(e).__name__, e))

    if motion_failures:
        print("")
        print("  [경고] 아래 컷은 줌·패닝을 걸지 못했습니다. 배치와 자막은 정상입니다.")
        print("         캡컷 안에서 줌 프리셋으로 대신 넣으면 됩니다.")
        for n, motion, err in motion_failures:
            print("         컷 %s (%s): %s" % (n, motion, err))

    try:
        script_file.save()
    except Exception as e:
        die("드래프트를 저장하지 못했습니다.\n       사유: %s: %s" % (type(e).__name__, e))

    return os.path.join(draft_root, draft_name)


# ─────────────────────────────────────────────────────────────────────────────
# 7단계 — 예비 파일 (드래프트가 캡컷에서 안 열려도 작업이 헛되지 않도록 항상 만든다)
# ─────────────────────────────────────────────────────────────────────────────
def write_srt(rows, path):
    """자막 파일. UTF-8, BOM 없이. 자막A 트랙(나레이션 28개)만 담는다."""
    lines = []
    for i, r in enumerate(rows, start=1):
        lines.append(str(i))
        lines.append("%s --> %s" % (fmt_srt_time(r["start"]), fmt_srt_time(r["end"])))
        lines.append(r["narration"])
        lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))


def write_durations_md(script, rows, body_total, grand_total, image_paths, path):
    """컷 번호 / 길이 / 시작 / 이미지 끝 / 모션 표."""
    out = []
    out.append("# %s — 컷 길이표" % (script["title"] or "컷 길이표"))
    out.append("")
    out.append("| 컷 | 글자수 | 길이(초) | 시작 | 이미지 끝 | 모션 | 이미지 파일 |")
    out.append("|---:|---:|---:|---|---|---|---|")
    for r, img in zip(rows, image_paths):
        fname = unicodedata.normalize("NFC", os.path.basename(img))
        out.append("| %s | %d | %.2f | %s | %s | %s | %s |"
                   % (r["n"], r["chars"], r["duration"],
                      fmt_clock(r["start"]), fmt_clock(r["image_end"]), r["motion"], fname))
    out.append("")
    out.append("- 본편 총 길이: **%.2f초 (%s)**" % (body_total, fmt_clock(body_total)))
    out.append("- 엔딩카드 포함: **%.2f초 (%s)**" % (grand_total, fmt_clock(grand_total)))
    out.append("")
    out.append("컷 길이 = (나레이션 글자 수 ÷ 초당 낭독 글자 수) + 뒤 여백")
    out.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out))


# ─────────────────────────────────────────────────────────────────────────────
# 진입점
# ─────────────────────────────────────────────────────────────────────────────
def pick_default(*candidates):
    """후보 경로 중 실제로 있는 첫 번째를 고른다. 없으면 첫 번째를 그대로."""
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0]


def main():
    ap = argparse.ArgumentParser(
        description="대본과 이미지로 캡컷 프로젝트(드래프트)를 만든다. 음성 합성과 렌더링은 하지 않는다.")
    ap.add_argument("--script", default=pick_default("script.json", "input/script.json"),
                    help="대본 JSON 경로")
    ap.add_argument("--images", default=pick_default("images", "input/images"),
                    help="이미지 폴더 경로")
    ap.add_argument("--name", default=None,
                    help="캡컷에 보일 프로젝트 이름 (기본: 대본 title)")
    ap.add_argument("--config", default="capcut_config.json",
                    help="설정 파일 경로 (없으면 기본값으로 새로 만든다)")
    ap.add_argument("--draft-folder", default=None,
                    help="캡컷 드래프트 폴더. 생략하면 자동으로 찾는다")
    ap.add_argument("--out", default="capcut_out",
                    help="narration.srt / cut_durations.md 를 쓸 폴더")
    ap.add_argument("--replace", action="store_true",
                    help="같은 이름의 프로젝트가 있으면 덮어쓴다")
    ap.add_argument("--yes", action="store_true",
                    help="이미지 순서 확인을 자동 승인 (표는 그대로 출력된다)")
    args = ap.parse_args()

    try:
        import pycapcut  # noqa: F401
    except ImportError:
        die("pycapcut 이 설치되어 있지 않습니다.\n       pip install pycapcut")

    print("=" * 78)
    print("캡컷 드래프트 생성기")
    print("=" * 78)

    cfg = load_config(args.config)
    script = load_script(args.script)
    cuts = script["cuts"]
    print("대본 파일 : %s  (컷 %d개, 총 %d자)"
          % (args.script, len(cuts), sum(len(c["narration"]) for c in cuts)))

    image_paths = collect_images(args.images, len(cuts))
    print("이미지    : %s  (%d장)" % (args.images, len(image_paths)))

    confirm_order(cuts, image_paths, args.yes)

    rows, body_total, grand_total = build_timeline(cuts, cfg)
    print_timeline_check(rows, body_total, grand_total)

    # 드래프트를 놓을 곳 정하기
    draft_root = args.draft_folder or find_draft_folder()
    fallback = False
    if draft_root is None:
        draft_root = os.path.join(args.out, "드래프트")
        fallback = True
        print("")
        print("  [알림] 이 컴퓨터에서 캡컷 드래프트 폴더를 찾지 못했습니다.")
        print("         대신 %s 에 만듭니다." % draft_root)
        print("         나중에 이 폴더를 캡컷 드래프트 폴더로 통째로 옮기면 됩니다.")

    draft_name = args.name or (script["title"] or "capcut_draft")
    # 폴더 이름으로 못 쓰는 글자를 걸러낸다
    draft_name = re.sub(r'[\\/:*?"<>|]', "_", draft_name).strip() or "capcut_draft"

    print("")
    print("프로젝트  : %s" % draft_name)
    print("드래프트  : %s" % draft_root)
    print("")

    draft_path = build_draft(script, rows, image_paths, cfg,
                             draft_root, draft_name, args.replace)

    # 예비 파일은 드래프트가 안 열려도 작업이 헛되지 않게 '항상' 만든다
    os.makedirs(args.out, exist_ok=True)
    srt_path = os.path.join(args.out, "narration.srt")
    md_path = os.path.join(args.out, "cut_durations.md")
    write_srt(rows, srt_path)
    write_durations_md(script, rows, body_total, grand_total, image_paths, md_path)

    print("")
    print("=" * 78)
    print("완료")
    print("=" * 78)
    print("  프로젝트  : %s" % draft_path)
    print("  자막 파일 : %s" % srt_path)
    print("  컷 길이표 : %s" % md_path)
    print("  총 길이   : %.2f초 (%s)" % (grand_total, fmt_clock(grand_total)))
    print("")
    if fallback:
        print("  이 컴퓨터엔 캡컷이 없어서 드래프트를 임시 폴더에 만들었습니다.")
        print("  캡컷이 깔린 컴퓨터의 드래프트 폴더로 '%s' 폴더째 옮기세요." % draft_name)
        print("")
    print("  ※ 새로 만든 프로젝트가 캡컷 목록에 바로 안 뜰 수 있습니다.")
    print("     기존 프로젝트를 아무거나 열었다 닫거나, 캡컷을 재시작하면 나타납니다.")
    print("")
    print("  캡컷에서 할 일 (15~20분)")
    print("    1. 프로젝트 열기")
    print("    2. '%s' 트랙 전체 선택 → 텍스트 읽기 → 목소리 1회 선택" % TRACK_SUBTITLE)
    print("    3. 자막 스타일 1회 설정 → 모두에 적용")
    print("    4. BGM 추가, 볼륨 10~15%")
    print("    5. 내보내기 1080p 30fps")
    print("")
    print("  캡컷이 만든 음성이 자막보다 길면 %s 의 chars_per_second 를 낮추고,"
          % args.config)
    print("  짧으면 높인 뒤 다시 돌리세요. 한 번 맞추면 다음 화부터는 그대로 갑니다.")


if __name__ == "__main__":
    main()

"""한글 자막 폰트 찾기.

fontconfig 에 이름만 넘기면 안 된다. 'Noto Sans KR' 을 요청해도 한글이 하나도
없는 DejaVu Sans 가 돌아오고, 자막이 통째로 □□□□ 로 나온다.
그래서 한국어를 지원한다고 신고한 폰트만 추려 놓고 그 안에서 고른다.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache

# 위에 있을수록 먼저 쓴다. 중국어 폰트(WenQuanYi 등)는 한글이 있어도
# 글자 모양이 한국어 활자와 달라서 목록에 넣지 않는다 — 마지막 수단으로만 쓰인다.
PREFERRED = [
    "Noto Sans CJK KR",
    "Noto Sans KR",
    "Source Han Sans KR",
    "NanumBarunGothic",
    "NanumGothic",
    "Malgun Gothic",
    "Apple SD Gothic Neo",
    "Pretendard",
    "Spoqa Han Sans Neo",
]

INSTALL_HINT = (
    "한글 자막을 넣을 폰트가 하나도 없습니다.\n"
    "  우분투·데비안 : sudo apt-get install -y fonts-noto-cjk\n"
    "  맥            : brew install --cask font-noto-sans-cjk\n"
    "  윈도우        : 맑은 고딕이 기본 설치되어 있습니다"
)


class FontError(Exception):
    pass


def _norm(name: str) -> str:
    return "".join(name.lower().split())


def _aliases(name: str) -> set[str]:
    """'Noto Sans CJK KR' 과 'Noto Sans KR' 을 같은 것으로 본다."""
    n = _norm(name)
    return {n, n.replace("cjk", "")}


@lru_cache(maxsize=1)
def korean_families() -> list[str]:
    """한국어를 지원한다고 신고한 폰트 가족 이름들."""
    proc = subprocess.run(["fc-list", ":lang=ko", "family"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []

    seen, out = set(), []
    for line in proc.stdout.splitlines():
        # 한 폰트가 "Noto Sans CJK KR,Noto Sans CJK KR Regular" 처럼 여러 이름을 갖는다
        for fam in (f.strip() for f in line.split(",")):
            if fam and fam not in seen:
                seen.add(fam)
                out.append(fam)
    return out


def resolve(preferred: str) -> tuple[str, str | None]:
    """쓸 폰트 이름과, 요청과 달라졌을 때의 알림 문구를 돌려준다."""
    available = korean_families()
    if not available:
        raise FontError(INSTALL_HINT)

    # 설치된 폰트를 별칭까지 펼쳐 둔다. 'Noto Sans CJK KR' 은 'Noto Sans KR' 로도 찾힌다.
    by_norm: dict[str, str] = {}
    for fam in available:
        for alias in _aliases(fam):
            by_norm.setdefault(alias, fam)

    for alias in _aliases(preferred):
        if alias in by_norm:
            return by_norm[alias], None

    for candidate in PREFERRED:
        for alias in _aliases(candidate):
            if alias in by_norm:
                return (
                    by_norm[alias],
                    f"'{preferred}' 폰트가 없어 '{by_norm[alias]}' 로 대신합니다.",
                )

    fallback = available[0]
    return fallback, (
        f"'{preferred}' 도, 권장 한글 폰트도 없습니다. '{fallback}' 로 대신하는데\n"
        "  글자 모양이 어색할 수 있습니다. fonts-noto-cjk 설치를 권합니다."
    )

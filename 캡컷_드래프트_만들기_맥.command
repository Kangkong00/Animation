#!/bin/bash
# ============================================================================
#  캡컷 드래프트 만들기 (맥)
#  이 파일을 더블클릭하면 됩니다. 터미널에 뭘 칠 필요 없습니다.
#
#  처음 한 번은 "권한이 없습니다" 가 뜰 수 있습니다. 그럴 땐 이 파일을
#  오른쪽 클릭 → 열기 를 누르시면 됩니다.
# ============================================================================
cd "$(dirname "$0")" || exit 1

echo
echo "=========================================================="
echo "  캡컷 드래프트 만들기"
echo "=========================================================="
echo

# ── 1. 파이썬 찾기 ──────────────────────────────────────────────────────────
PY=""
for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done

if [ -z "$PY" ]; then
    echo "  [문제] 이 컴퓨터에 파이썬이 없습니다."
    echo
    echo "  해결 방법:"
    echo "    1. https://www.python.org/downloads/  에 들어가서"
    echo "    2. 노란 Download 버튼을 눌러 설치하세요"
    echo "    3. 설치가 끝나면 이 파일을 다시 더블클릭하세요"
    echo
    read -n 1 -s -r -p "  창을 닫으려면 아무 키나 누르세요."
    exit 1
fi
echo "  파이썬 확인 완료."

# ── 2. 필요한 부품(pycapcut) 확인 ───────────────────────────────────────────
if ! "$PY" -c "import pycapcut" >/dev/null 2>&1; then
    echo "  부품을 내려받는 중입니다. 처음 한 번만 걸립니다..."
    "$PY" -m pip install pycapcut >/dev/null 2>&1 \
        || "$PY" -m pip install --user pycapcut \
        || "$PY" -m pip install --user --break-system-packages pycapcut
    if ! "$PY" -c "import pycapcut" >/dev/null 2>&1; then
        echo
        echo "  [문제] 부품을 내려받지 못했습니다."
        echo "  인터넷 연결을 확인하고 다시 해보세요."
        echo
        read -n 1 -s -r -p "  창을 닫으려면 아무 키나 누르세요."
        exit 1
    fi
fi
echo "  부품 확인 완료."
echo

# ── 3. 실행 ─────────────────────────────────────────────────────────────────
"$PY" make_capcut_draft.py || {
    echo
    echo "  위에 이유가 적혀 있습니다. 그대로 복사해서 물어보세요."
}

echo
read -n 1 -s -r -p "  창을 닫으려면 아무 키나 누르세요."
echo

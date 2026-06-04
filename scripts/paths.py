from __future__ import annotations

from typing import Iterable


def normalize(p: str) -> str:
    """경로를 비교 가능한 형태로 정규화: 양끝 공백·슬래시 제거."""
    return p.strip().strip("/")


def overlaps(a: str, b: str) -> bool:
    """두 경로가 같은 영역을 가리키면 True.

    겹침 = 동일하거나, 한쪽이 다른 쪽의 디렉터리 조상.
    'payment'와 'payment2'처럼 단순 문자열 접두는 겹치지 않는다.
    """
    a, b = normalize(a), normalize(b)
    if a == b:
        return True
    return b.startswith(a + "/") or a.startswith(b + "/")


def any_overlap(a: Iterable[str], b: Iterable[str]) -> bool:
    """두 touches 집합이 하나라도 겹치면 True."""
    bs = [normalize(x) for x in b]
    return any(overlaps(x, y) for x in a for y in bs)

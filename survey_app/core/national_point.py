# survey_app/core/national_point.py
# -*- coding: utf-8 -*-
"""
국가지점번호(국토격자) 100m 단위 grid_id(2글자+6숫자) 계산 유틸

- 입력: WGS84 위경도 (lat, lon)
- 출력: 예) "다라062466" 형태의 100m 축약 grid_id

주의:
- 이 로직은 '국가지점번호' 체계의 기준점(가가00000000)을 기준으로 UTM-K(EPSG:5179) 평면좌표에서
  100km 블록(한글2글자) + 100m 인덱스(6자리)로 변환합니다.
- 실제 데이터(예: 다라062466)가 100m 축약 표기라면 이 파일만으로 바로 생성/검증 가능합니다.

필수 패키지:
- pyproj
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple, Optional

from pyproj import Transformer


# -----------------------------------------------------------------------------
# 100km 블록 문자 범위
# - 동쪽 방향: 가~사 (7개)
# - 북쪽 방향: 가~아 (8개)
# -----------------------------------------------------------------------------
E100KM = ["가", "나", "다", "라", "마", "바", "사"]              # Easting (col)
N100KM = ["가", "나", "다", "라", "마", "바", "사", "아"]         # Northing (row)

# -----------------------------------------------------------------------------
# 기준점(가가00000000)의 위경도 (WGS84)
# - 국가지점번호 설명 자료에서 널리 인용되는 마라도 인근 해역 기준점
# -----------------------------------------------------------------------------
BASE_LON = 124 + 20 / 60 + 11 / 3600   # 124°20′11″E
BASE_LAT = 31 + 38 / 60 + 51 / 3600    # 31°38′51″N

# -----------------------------------------------------------------------------
# 좌표 변환기
# - WGS84(4326) <-> UTM-K(5179)
# -----------------------------------------------------------------------------
_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_TO_4326 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

_BASE_X, _BASE_Y = _TO_5179.transform(BASE_LON, BASE_LAT)


@dataclass(frozen=True)
class Grid100m:
    """100m 축약 국가지점번호 표현."""
    grid_id: str
    # 100m 칸의 남서(SW) 모서리: UTM-K meters
    sw_x: float
    sw_y: float
    # 중심점: WGS84
    center_lat: float
    center_lon: float


def latlon_to_grid_id_100m(lat: float, lon: float) -> str:
    """
    WGS84 위경도 -> 국가지점번호 100m 축약 grid_id (2글자 + 6숫자)

    예:
      (lat, lon) -> "다라062466"

    Raises:
      ValueError: 입력 좌표가 커버 범위 밖이거나 형식적으로 이상할 때
    """
    # UTM-K (meters)
    x, y = _TO_5179.transform(lon, lat)

    dx = x - _BASE_X
    dy = y - _BASE_Y

    if dx < 0 or dy < 0:
        raise ValueError("입력 좌표가 기준점(가가00000000)보다 남/서쪽입니다. 좌표를 확인하세요.")

    e_idx_100km = int(dx // 100_000)
    n_idx_100km = int(dy // 100_000)

    if e_idx_100km >= len(E100KM) or n_idx_100km >= len(N100KM):
        raise ValueError(
            f"입력 좌표가 100km 문자 블록 범위를 벗어났습니다. "
            f"(e_idx={e_idx_100km}, n_idx={n_idx_100km})"
        )

    # 100km 블록 내부의 100m 인덱스 (0~999)
    e_in_100m = int((dx - e_idx_100km * 100_000) // 100)
    n_in_100m = int((dy - n_idx_100km * 100_000) // 100)

    return f"{E100KM[e_idx_100km]}{N100KM[n_idx_100km]}{e_in_100m:03d}{n_in_100m:03d}"


def latlon_to_grid100m(lat: float, lon: float) -> Grid100m:
    """
    WGS84 위경도 -> Grid100m(남서 모서리 UTM-K + 중심점 위경도 포함)
    """
    grid_id = latlon_to_grid_id_100m(lat, lon)

    # 같은 계산을 다시 해서 SW 좌표를 함께 구함(중복이지만 명확성을 위해 분리)
    x, y = _TO_5179.transform(lon, lat)
    dx = x - _BASE_X
    dy = y - _BASE_Y

    e_idx_100km = int(dx // 100_000)
    n_idx_100km = int(dy // 100_000)
    e_in_100m = int((dx - e_idx_100km * 100_000) // 100)
    n_in_100m = int((dy - n_idx_100km * 100_000) // 100)

    sw_x = _BASE_X + e_idx_100km * 100_000 + e_in_100m * 100
    sw_y = _BASE_Y + n_idx_100km * 100_000 + n_in_100m * 100

    # 100m 칸 중심점 (UTM-K -> WGS84)
    cx, cy = sw_x + 50.0, sw_y + 50.0
    center_lon, center_lat = _TO_4326.transform(cx, cy)

    return Grid100m(
        grid_id=grid_id,
        sw_x=sw_x,
        sw_y=sw_y,
        center_lat=center_lat,
        center_lon=center_lon,
    )


def grid_id_100m_to_polygon_geojson(grid_id: str) -> Dict:
    """
    100m 축약 grid_id(2글자+6숫자) -> 100m 폴리곤 GeoJSON (EPSG:4326)

    반환:
      {"type":"Polygon","coordinates":[[[lon,lat],...]]}
    """
    if len(grid_id) != 8:
        raise ValueError("100m 축약 grid_id는 2글자+6숫자, 총 8자리여야 합니다. 예: 다라062466")

    c1, c2 = grid_id[0], grid_id[1]
    digits = grid_id[2:]
    if c1 not in E100KM or c2 not in N100KM:
        raise ValueError("grid_id의 앞 2글자(100km 블록)가 유효하지 않습니다.")
    if not digits.isdigit():
        raise ValueError("grid_id의 숫자부는 6자리 숫자여야 합니다.")

    e_idx_100km = E100KM.index(c1)
    n_idx_100km = N100KM.index(c2)

    e_in_100m = int(digits[:3])
    n_in_100m = int(digits[3:])

    sw_x = _BASE_X + e_idx_100km * 100_000 + e_in_100m * 100
    sw_y = _BASE_Y + n_idx_100km * 100_000 + n_in_100m * 100
    ne_x, ne_y = sw_x + 100.0, sw_y + 100.0

    # 꼭지점 (lon, lat)
    p1 = _TO_4326.transform(sw_x, sw_y)  # SW
    p2 = _TO_4326.transform(ne_x, sw_y)  # SE
    p3 = _TO_4326.transform(ne_x, ne_y)  # NE
    p4 = _TO_4326.transform(sw_x, ne_y)  # NW

    return {
        "type": "Polygon",
        "coordinates": [[
            [p1[0], p1[1]],
            [p2[0], p2[1]],
            [p3[0], p3[1]],
            [p4[0], p4[1]],
            [p1[0], p1[1]],
        ]]
    }


def debug_example(lat: float, lon: float) -> Dict[str, object]:
    """
    디버깅/로그 출력용: 위경도 -> grid_id + 중심점 + 폴리곤 요약
    """
    g = latlon_to_grid100m(lat, lon)
    poly = grid_id_100m_to_polygon_geojson(g.grid_id)
    return {
        "input": {"lat": lat, "lon": lon},
        "grid_id_100m": g.grid_id,
        "center": {"lat": g.center_lat, "lon": g.center_lon},
        "sw_utm_k": {"x": g.sw_x, "y": g.sw_y},
        "polygon_geojson": poly,
    }

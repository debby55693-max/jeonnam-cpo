# survey_app/core/national_point.py
# -*- coding: utf-8 -*-
"""
국가지점번호(국토격자) 100m 단위 grid_id(2글자+6숫자) 계산 유틸

프로젝트 통일 기준
- 내부 좌표계: EPSG:5179
- 100km 한글 블록: 동쪽 가~사 / 북쪽 가~아
- 100m 축약 표기: 예) 다라024454
- 프로젝트에서 사용하는 실제 격자 중심좌표 TXT/산출물 기준 원점:
  가가000000의 중심점 = (700050, 1300050)
  => SW 원점은 (700000, 1300000)

중요
- 기존에 위경도 기준점(124°20′11″E, 31°38′51″N)을 5179로 변환한 값을 원점으로 쓰면
  현재 프로젝트의 실제 격자 데이터와 미세하게 어긋난다.
- 그 결과 북쪽 1칸, 또는 경계 부근에서 옆 칸으로 밀리는 현상이 생길 수 있다.
- 따라서 이 프로젝트에서는 반드시 BASE_X=700000, BASE_Y=1300000 을 사용한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict

from pyproj import Transformer


# -----------------------------------------------------------------------------
# 100km 블록 문자 범위
# -----------------------------------------------------------------------------
E100KM = ["가", "나", "다", "라", "마", "바", "사"]              # Easting (col)
N100KM = ["가", "나", "다", "라", "마", "바", "사", "아"]         # Northing (row)

# -----------------------------------------------------------------------------
# 프로젝트 통일 원점 (EPSG:5179)
# -----------------------------------------------------------------------------
BASE_X = 700000.0
BASE_Y = 1300000.0

GRID_SIZE_M = 100.0
BLOCK_SIZE_M = 100_000.0
EPS_M = 1e-6  # 경계/부동소수 오차 보정용 아주 작은 값

# -----------------------------------------------------------------------------
# 좌표 변환기
# -----------------------------------------------------------------------------
_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_TO_4326 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)


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


def _safe_floor_index(value_m: float, step_m: float) -> int:
    """
    value_m >= 0 인 좌표를 step_m 격자 인덱스로 내림.
    EPS_M를 더해 경계선/역변환 오차로 인한 1칸 밀림을 줄인다.
    """
    return int(math.floor((value_m + EPS_M) / step_m))


def latlon_to_grid_id_100m(lat: float, lon: float) -> str:
    """
    WGS84 위경도 -> 국가지점번호 100m 축약 grid_id (2글자 + 6숫자)

    예:
      (lat, lon) -> "다라024454"
    """
    x, y = _TO_5179.transform(lon, lat)

    dx = x - BASE_X
    dy = y - BASE_Y

    if dx < -EPS_M or dy < -EPS_M:
        raise ValueError("입력 좌표가 기준점(가가000000)보다 남/서쪽입니다. 좌표를 확인하세요.")

    e_idx_100km = _safe_floor_index(dx, BLOCK_SIZE_M)
    n_idx_100km = _safe_floor_index(dy, BLOCK_SIZE_M)

    if e_idx_100km >= len(E100KM) or n_idx_100km >= len(N100KM):
        raise ValueError(
            f"입력 좌표가 100km 문자 블록 범위를 벗어났습니다. "
            f"(e_idx={e_idx_100km}, n_idx={n_idx_100km})"
        )

    dx_in_block = dx - e_idx_100km * BLOCK_SIZE_M
    dy_in_block = dy - n_idx_100km * BLOCK_SIZE_M

    e_in_100m = _safe_floor_index(dx_in_block, GRID_SIZE_M)
    n_in_100m = _safe_floor_index(dy_in_block, GRID_SIZE_M)

    # 경계선 오차로 1000이 되는 극단 케이스 방지
    if e_in_100m > 999:
        e_in_100m = 999
    if n_in_100m > 999:
        n_in_100m = 999

    return f"{E100KM[e_idx_100km]}{N100KM[n_idx_100km]}{e_in_100m:03d}{n_in_100m:03d}"


def latlon_to_grid100m(lat: float, lon: float) -> Grid100m:
    """
    WGS84 위경도 -> Grid100m(남서 모서리 UTM-K + 중심점 위경도 포함)
    """
    x, y = _TO_5179.transform(lon, lat)

    dx = x - BASE_X
    dy = y - BASE_Y

    if dx < -EPS_M or dy < -EPS_M:
        raise ValueError("입력 좌표가 기준점(가가000000)보다 남/서쪽입니다. 좌표를 확인하세요.")

    e_idx_100km = _safe_floor_index(dx, BLOCK_SIZE_M)
    n_idx_100km = _safe_floor_index(dy, BLOCK_SIZE_M)

    if e_idx_100km >= len(E100KM) or n_idx_100km >= len(N100KM):
        raise ValueError(
            f"입력 좌표가 100km 문자 블록 범위를 벗어났습니다. "
            f"(e_idx={e_idx_100km}, n_idx={n_idx_100km})"
        )

    dx_in_block = dx - e_idx_100km * BLOCK_SIZE_M
    dy_in_block = dy - n_idx_100km * BLOCK_SIZE_M

    e_in_100m = _safe_floor_index(dx_in_block, GRID_SIZE_M)
    n_in_100m = _safe_floor_index(dy_in_block, GRID_SIZE_M)

    if e_in_100m > 999:
        e_in_100m = 999
    if n_in_100m > 999:
        n_in_100m = 999

    grid_id = f"{E100KM[e_idx_100km]}{N100KM[n_idx_100km]}{e_in_100m:03d}{n_in_100m:03d}"

    sw_x = BASE_X + e_idx_100km * BLOCK_SIZE_M + e_in_100m * GRID_SIZE_M
    sw_y = BASE_Y + n_idx_100km * BLOCK_SIZE_M + n_in_100m * GRID_SIZE_M

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
    """
    if len(grid_id) != 8:
        raise ValueError("100m 축약 grid_id는 2글자+6숫자, 총 8자리여야 합니다. 예: 다라024454")

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

    sw_x = BASE_X + e_idx_100km * BLOCK_SIZE_M + e_in_100m * GRID_SIZE_M
    sw_y = BASE_Y + n_idx_100km * BLOCK_SIZE_M + n_in_100m * GRID_SIZE_M
    ne_x, ne_y = sw_x + GRID_SIZE_M, sw_y + GRID_SIZE_M

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
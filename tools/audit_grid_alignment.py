from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Optional, Tuple

import pandas as pd
from pyproj import Transformer

E100KM = ["가", "나", "다", "라", "마", "바", "사"]
N100KM = ["가", "나", "다", "라", "마", "바", "사", "아"]

GRID_SIZE_M = 100.0
BLOCK_SIZE_M = 100_000.0
BASE_X = 700000.0
BASE_Y = 1300000.0
EPS_M = 1e-6

GRID_RE = re.compile(r"^([가-힣]{2})(\d{3})(\d{3})$")
TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def normalize_grid_id(v) -> Optional[str]:
    if pd.isna(v):
        return None
    s = str(v).strip().replace(" ", "")
    return s or None


def pick_col(df: pd.DataFrame, candidates) -> Optional[str]:
    normalized = {str(c).strip().lower(): c for c in df.columns}

    for cand in candidates:
        key = cand.strip().lower()
        if key in normalized:
            return normalized[key]

    for cand in candidates:
        key = cand.strip().lower()
        for lc, orig in normalized.items():
            if lc == key or key in lc:
                return orig

    return None


def safe_floor_index(value_m: float, step_m: float) -> int:
    return int(math.floor((value_m + EPS_M) / step_m))


def latlon_to_grid_id_100m(lat: float, lon: float) -> str:
    x, y = TO_5179.transform(lon, lat)

    dx = x - BASE_X
    dy = y - BASE_Y

    if dx < -EPS_M or dy < -EPS_M:
        raise ValueError("입력 좌표가 기준점(가가000000)보다 남/서쪽입니다.")

    e_idx_100km = safe_floor_index(dx, BLOCK_SIZE_M)
    n_idx_100km = safe_floor_index(dy, BLOCK_SIZE_M)

    if not (0 <= e_idx_100km < len(E100KM)) or not (0 <= n_idx_100km < len(N100KM)):
        raise ValueError(
            f"입력 좌표가 100km 문자 블록 범위를 벗어났습니다. "
            f"(e_idx={e_idx_100km}, n_idx={n_idx_100km})"
        )

    dx_in_block = dx - e_idx_100km * BLOCK_SIZE_M
    dy_in_block = dy - n_idx_100km * BLOCK_SIZE_M

    e_in_100m = safe_floor_index(dx_in_block, GRID_SIZE_M)
    n_in_100m = safe_floor_index(dy_in_block, GRID_SIZE_M)

    if e_in_100m > 999:
        e_in_100m = 999
    if n_in_100m > 999:
        n_in_100m = 999

    return f"{E100KM[e_idx_100km]}{N100KM[n_idx_100km]}{e_in_100m:03d}{n_in_100m:03d}"


def parse_grid_id(grid_id: Optional[str]) -> Optional[Tuple[str, int, int]]:
    if not grid_id:
        return None
    m = GRID_RE.match(grid_id)
    if not m:
        return None
    return m.group(1), int(m.group(2)), int(m.group(3))


def shift_label(current_grid: Optional[str], recalculated_grid: Optional[str]) -> Optional[str]:
    a = parse_grid_id(current_grid)
    b = parse_grid_id(recalculated_grid)

    if not a or not b:
        return None

    if a[0] != b[0]:
        return "100km블록불일치"

    dx = b[1] - a[1]
    dy = b[2] - a[2]

    if dx == 0 and dy == 0:
        return "일치"
    if dx == 1 and dy == 0:
        return "동쪽1칸"
    if dx == -1 and dy == 0:
        return "서쪽1칸"
    if dx == 0 and dy == 1:
        return "북쪽1칸"
    if dx == 0 and dy == -1:
        return "남쪽1칸"
    if abs(dx) <= 2 and abs(dy) <= 2:
        return f"근접이동(dx={dx},dy={dy})"
    return f"이격큼(dx={dx},dy={dy})"


def choose_name_col(df: pd.DataFrame) -> Optional[str]:
    return pick_col(df, ["shop_name", "bizesNm", "업소명", "상호", "점포명", "업체명", "bizesnm"])


def choose_addr_col(df: pd.DataFrame) -> Optional[str]:
    return pick_col(df, ["address", "rdnmAdr", "lnoAdr", "주소", "도로명주소", "지번주소", "rdnmadr", "lnoadr"])


def build_current_grid(df: pd.DataFrame) -> pd.Series:
    override_col = pick_col(df, ["grid_id_override", "override_grid_id"])
    grid_col = pick_col(df, ["grid_id"])
    calc_col = pick_col(df, ["grid_id_calc"])

    override = df[override_col].map(normalize_grid_id) if override_col else pd.Series([None] * len(df))
    grid = df[grid_col].map(normalize_grid_id) if grid_col else pd.Series([None] * len(df))
    calc = df[calc_col].map(normalize_grid_id) if calc_col else pd.Series([None] * len(df))

    current = override.copy()
    current = current.where(current.notna(), grid)
    current = current.where(current.notna(), calc)
    return current


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--in_csv", required=True, help="점검할 CSV 경로")
    parser.add_argument("--out_all", default="output/grid_alignment_audit_all.csv", help="전체 결과 CSV")
    parser.add_argument("--out_mismatch", default="output/grid_alignment_audit_mismatch.csv", help="불일치 결과 CSV")
    args = parser.parse_args()

    in_path = Path(args.in_csv)
    if not in_path.exists():
        raise FileNotFoundError(f"입력 CSV 없음: {in_path}")

    df = pd.read_csv(in_path, low_memory=False)
    if len(df) == 0:
        raise RuntimeError("입력 CSV가 비어 있습니다.")

    lat_col = pick_col(df, ["lat", "latitude", "위도"])
    lon_col = pick_col(df, ["lon", "longitude", "lng", "경도"])

    if lat_col is None or lon_col is None:
        raise ValueError(f"lat/lon 컬럼을 찾지 못했습니다. 현재 컬럼: {list(df.columns)}")

    current_grid = build_current_grid(df)
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")

    recalculated = []
    for la, lo in zip(lat, lon):
        if pd.isna(la) or pd.isna(lo):
            recalculated.append(None)
            continue
        try:
            recalculated.append(latlon_to_grid_id_100m(float(la), float(lo)))
        except Exception:
            recalculated.append(None)

    result = df.copy()
    result["grid_id_current_resolved"] = current_grid
    result["grid_id_recalculated"] = recalculated
    result["grid_id_match"] = result["grid_id_current_resolved"].fillna("") == result["grid_id_recalculated"].fillna("")
    result["grid_shift_type"] = [
        shift_label(cur, new)
        for cur, new in zip(result["grid_id_current_resolved"], result["grid_id_recalculated"])
    ]

    name_col = choose_name_col(result)
    addr_col = choose_addr_col(result)

    if name_col and name_col != "shop_name_for_audit":
        result = result.rename(columns={name_col: "shop_name_for_audit"})
    if addr_col and addr_col != "address_for_audit":
        result = result.rename(columns={addr_col: "address_for_audit"})

    mismatch = result[
        result["grid_id_current_resolved"].notna()
        & result["grid_id_recalculated"].notna()
        & (~result["grid_id_match"])
    ].copy()

    out_all = Path(args.out_all)
    out_mismatch = Path(args.out_mismatch)
    out_all.parent.mkdir(parents=True, exist_ok=True)
    out_mismatch.parent.mkdir(parents=True, exist_ok=True)

    result.to_csv(out_all, index=False, encoding="utf-8-sig")
    mismatch.to_csv(out_mismatch, index=False, encoding="utf-8-sig")

    print("==== 격자 정합성 점검 결과 ====")
    print(f"- 입력 행 수: {len(result):,}")
    print(f"- 현재 grid_id 보유 행 수: {int(result['grid_id_current_resolved'].notna().sum()):,}")
    print(f"- 재계산 성공 행 수: {int(result['grid_id_recalculated'].notna().sum()):,}")
    print(f"- 불일치 행 수: {len(mismatch):,}")

    if len(mismatch) > 0:
        print("\n[불일치 유형 상위]")
        print(mismatch["grid_shift_type"].fillna("미분류").value_counts().head(10).to_string())

    print(f"\n- 전체 결과: {out_all}")
    print(f"- 불일치 결과: {out_mismatch}")


if __name__ == "__main__":
    main()
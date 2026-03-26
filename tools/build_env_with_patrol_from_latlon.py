import argparse
import glob
import math
import os

import pandas as pd
from pyproj import Transformer

# ------------------------------------------------------------
# 프로젝트 통일 격자 기준
# - EPSG:5179
# - 가가000000의 SW 원점 = (700000, 1300000)
# - 100m 축약 표기: 2글자 + 6숫자
# ------------------------------------------------------------

E100KM = ["가", "나", "다", "라", "마", "바", "사"]
N100KM = ["가", "나", "다", "라", "마", "바", "사", "아"]

BASE_X = 700000.0
BASE_Y = 1300000.0
GRID_SIZE_M = 100.0
BLOCK_SIZE_M = 100_000.0
EPS_M = 1e-6

_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def normalize_grid_id(v):
    if pd.isna(v):
        return None
    s = str(v).strip().replace(" ", "")
    return s or None


def _safe_floor_index(value_m: float, step_m: float) -> int:
    return int(math.floor((value_m + EPS_M) / step_m))


def latlon_to_grid_id_100m(lat: float, lon: float) -> str:
    """WGS84(lat, lon) -> 국가지점번호 100m 축약 grid_id"""
    x, y = _TO_5179.transform(lon, lat)

    dx = x - BASE_X
    dy = y - BASE_Y

    if dx < -EPS_M or dy < -EPS_M:
        raise ValueError("입력 좌표가 기준점(가가000000)보다 남/서쪽입니다.")

    e100km = _safe_floor_index(dx, BLOCK_SIZE_M)
    n100km = _safe_floor_index(dy, BLOCK_SIZE_M)

    if not (0 <= e100km < len(E100KM)) or not (0 <= n100km < len(N100KM)):
        raise ValueError("국가지점번호 커버 범위를 벗어났습니다(100km 한글 블록 범위).")

    dx_in_block = dx - e100km * BLOCK_SIZE_M
    dy_in_block = dy - n100km * BLOCK_SIZE_M

    e100m = _safe_floor_index(dx_in_block, GRID_SIZE_M)
    n100m = _safe_floor_index(dy_in_block, GRID_SIZE_M)

    if e100m > 999:
        e100m = 999
    if n100m > 999:
        n100m = 999

    return f"{E100KM[e100km]}{N100KM[n100km]}{e100m:03d}{n100m:03d}"


def pick_col(df, candidates):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--patrol_dir", default="data/탄력순찰", help="탄력순찰 엑셀 폴더 경로")
    parser.add_argument("--env_csv", default="data/env_grid_result_upload.csv", help="환경점수 CSV 경로")
    parser.add_argument("--out_csv", default="data/env_grid_result_upload_patrol.csv", help="출력 CSV 경로")
    args = parser.parse_args()

    files = sorted(glob.glob(os.path.join(args.patrol_dir, "*.xlsx")))
    if not files:
        raise FileNotFoundError(f"엑셀 파일 없음: {args.patrol_dir}/*.xlsx")

    all_gid = []
    total_rows = 0
    used_rows = 0
    skipped_files = 0

    for fp in files:
        df = pd.read_excel(fp)
        total_rows += len(df)

        lat_col = pick_col(df, ["위도", "lat", "LAT", "Latitude", "latitude"])
        lon_col = pick_col(df, ["경도", "lon", "LON", "Longitude", "longitude", "lng"])

        if lat_col is None or lon_col is None:
            print(f"[SKIP] {os.path.basename(fp)}: 위도/경도 컬럼을 찾지 못함")
            skipped_files += 1
            continue

        def calc(row):
            lat = row[lat_col]
            lon = row[lon_col]
            if pd.isna(lat) or pd.isna(lon):
                return None
            try:
                return normalize_grid_id(latlon_to_grid_id_100m(float(lat), float(lon)))
            except Exception:
                return None

        g = df.apply(calc, axis=1).dropna()
        used_rows += len(g)
        all_gid.append(g)

    if used_rows == 0:
        raise RuntimeError(
            "grid_id 생성 성공 행 수가 0입니다.\n"
            "위도/경도 값이 비어있거나(전부 NaN), 숫자 변환이 불가한 값인지 확인하세요."
        )

    gid_series = pd.concat(all_gid, ignore_index=True)
    patrol_cnt = gid_series.value_counts().rename_axis("grid_id").reset_index(name="cnt_patrol")

    print("==== 탄력순찰 집계 ====")
    print(f"- 파일 수: {len(files)} (스킵: {skipped_files})")
    print(f"- 총 행 수: {total_rows}")
    print(f"- grid_id 생성 성공 행 수: {used_rows}")
    print(f"- 집계된 grid_id 수: {len(patrol_cnt)}")

    if not os.path.exists(args.env_csv):
        raise FileNotFoundError(
            f"env_csv 파일이 없습니다: {args.env_csv}\n"
            "→ 파일을 data 폴더로 옮기거나, --env_csv에 실제 경로를 넣어주세요."
        )

    env = pd.read_csv(args.env_csv, dtype={"grid_id": "string"})
    if "grid_id" not in env.columns or "cnt_patrol" not in env.columns:
        raise ValueError("env_csv에는 grid_id, cnt_patrol 컬럼이 있어야 합니다.")

    env["grid_id"] = env["grid_id"].map(normalize_grid_id)

    merged = env.merge(patrol_cnt, on="grid_id", how="left", suffixes=("", "_new"))
    merged["cnt_patrol"] = merged["cnt_patrol_new"].fillna(0).astype("int64")
    merged = merged.drop(columns=["cnt_patrol_new"])

    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)
    merged.to_csv(args.out_csv, index=False, encoding="utf-8-sig")

    print("==== 완료 ====")
    print(f"- 출력: {args.out_csv}")


if __name__ == "__main__":
    main()
import argparse
import os
import glob
import pandas as pd

from pyproj import Transformer

# ------------------------------------------------------------
# ✅ 국가지점번호(100m) 변환 규칙(프로젝트에서 쓰던 정석 버전)
# - 2글자(100km 격자) + 6숫자(동3 + 북3)
# - 기준점(가가00000000): 위경도 (124°20′11″E, 31°38′51″N)
# - 내부 좌표계: EPSG:5179
# ------------------------------------------------------------

E100KM = ["가", "나", "다", "라", "마", "바", "사"]
N100KM = ["가", "나", "다", "라", "마", "바", "사", "아"]

BASE_LON = 124 + 20/60 + 11/3600
BASE_LAT = 31 + 38/60 + 51/3600

_TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
_BASE_X, _BASE_Y = _TO_5179.transform(BASE_LON, BASE_LAT)

def normalize_grid_id(v):
    if pd.isna(v):
        return None
    s = str(v).strip().replace(" ", "")
    return s or None

def latlon_to_grid_id_100m(lat: float, lon: float) -> str:
    """WGS84(lat, lon) → 국가지점번호 100m 축약 grid_id(예: '다라062466')"""
    x, y = _TO_5179.transform(lon, lat)
    dx = x - _BASE_X
    dy = y - _BASE_Y

    if dx < 0 or dy < 0:
        raise ValueError("입력 좌표가 기준점보다 남/서쪽입니다. 좌표/CRS를 확인하세요.")

    e100km = int(dx // 100_000)
    n100km = int(dy // 100_000)

    if not (0 <= e100km < len(E100KM)) or not (0 <= n100km < len(N100KM)):
        raise ValueError("국가지점번호 커버 범위를 벗어났습니다(100km 한글 블록 범위).")

    e100m = int((dx - e100km * 100_000) // 100)  # 0..999
    n100m = int((dy - n100km * 100_000) // 100)  # 0..999

    return f"{E100KM[e100km]}{N100KM[n100km]}{e100m:03d}{n100m:03d}"

def pick_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
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

        # ✅ 무안 샘플 기준: '위도', '경도' 컬럼이 있음
        lat_col = pick_col(df, ["위도", "lat", "LAT", "Latitude", "latitude"])
        lon_col = pick_col(df, ["경도", "lon", "LON", "Longitude", "longitude"])

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

    # ✅ env_csv 경로 체크 (여기서 네가 FileNotFound 났었음)
    if not os.path.exists(args.env_csv):
        raise FileNotFoundError(
            f"env_csv 파일이 없습니다: {args.env_csv}\n"
            "→ 파일을 data 폴더로 옮기거나, --env_csv에 실제 경로를 넣어주세요."
        )

    env = pd.read_csv(args.env_csv, dtype={"grid_id": "string"})
    if "grid_id" not in env.columns or "cnt_patrol" not in env.columns:
        raise ValueError("env_csv에는 grid_id, cnt_patrol 컬럼이 있어야 합니다.")

    env["grid_id"] = env["grid_id"].map(normalize_grid_id)

    # cnt_patrol만 덮어쓰기(없는 격자는 0)
    merged = env.merge(patrol_cnt, on="grid_id", how="left", suffixes=("", "_new"))
    merged["cnt_patrol"] = merged["cnt_patrol_new"].fillna(0).astype("int64")
    merged = merged.drop(columns=["cnt_patrol_new"])

    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)
    merged.to_csv(args.out_csv, index=False, encoding="utf-8-sig")

    print("==== 완료 ====")
    print(f"- 출력: {args.out_csv}")

if __name__ == "__main__":
    main()

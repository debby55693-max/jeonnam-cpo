from __future__ import annotations

import sys
import csv
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\82104\Desktop\jeonnam_cpo")
IN_PATH = ROOT / "output" / "grid_priority_top10pct.csv"

CENTER_CANDS = [
    ROOT / "data" / "격자2" / "국가지점번호 중심좌표.TXT",
    ROOT / "data" / "격자2" / "국가지점번호중심좌표.TXT",
    ROOT / "data" / "국가지점번호 중심좌표.TXT",
    ROOT / "data" / "국가지점번호중심좌표.TXT",
]
OUT_PATH = ROOT / "output" / "hotspot_grids.geojson"

HALF = 50.0
CENTER_CHUNKSIZE = 1_000_000


def die(msg: str):
    print("\n[중단]", msg)
    sys.exit(1)


def find_center_path() -> Path:
    for p in CENTER_CANDS:
        if p.exists():
            print("✅ 중심좌표 파일:", p)
            return p
    die("중심좌표 TXT를 못 찾음. data/격자2 또는 data 아래에 '국가지점번호 중심좌표.TXT'가 있어야 함.")
    return Path()


def detect_encoding_and_delim(path: Path):
    raw = path.read_bytes()[:20000]
    enc_try = ["cp949", "euc-kr", "utf-8-sig", "utf-8"]
    text, used_enc = None, None
    for enc in enc_try:
        try:
            text = raw.decode(enc, errors="strict")
            used_enc = enc
            break
        except Exception:
            continue
    if text is None:
        text = raw.decode("cp949", errors="ignore")
        used_enc = "cp949"

    try:
        dialect = csv.Sniffer().sniff(text, delimiters=[",", "\t", ";", "|"])
        delim = dialect.delimiter
    except Exception:
        delim = "|"

    return used_enc, delim


def pick_xy_columns(sample_df: pd.DataFrame) -> tuple[int, int]:
    cols = list(sample_df.columns)
    cand_idx = list(range(1, len(cols)))
    if len(cand_idx) < 2:
        die(f"중심좌표 TXT 컬럼 수가 너무 적음: {cols}")

    scores = []
    for i in cand_idx:
        s = pd.to_numeric(sample_df[i], errors="coerce")
        ratio = float(s.notna().mean())
        med = float(np.nanmedian(s.to_numpy())) if ratio > 0 else np.nan
        bonus = 0.0
        if np.isfinite(med) and 10000 < med < 5000000:
            bonus = 0.1
        scores.append((ratio + bonus, i))

    scores.sort(reverse=True, key=lambda x: x[0])
    return scores[0][1], scores[1][1]


def read_centers_for_grid_ids(center_path: Path, grid_ids: set[str]) -> pd.DataFrame:
    used_enc, delim = detect_encoding_and_delim(center_path)

    sample = pd.read_csv(
        center_path,
        sep=delim if delim in [",", "\t", ";", "|"] else None,
        header=None,
        encoding=used_enc,
        nrows=2000,
        engine="python",
        on_bad_lines="skip",
    )
    if sample.shape[1] < 3:
        die(f"중심좌표 TXT 컬럼이 3개 미만: shape={sample.shape}")

    x_i, y_i = pick_xy_columns(sample)
    print(f"✅ 중심좌표 컬럼 자동감지: grid_id_col=0, x_col={x_i}, y_col={y_i}, delim='{delim}', enc='{used_enc}'")

    kept = []
    remaining = set(grid_ids)

    reader = pd.read_csv(
        center_path,
        sep=delim if delim in [",", "\t", ";", "|"] else None,
        header=None,
        encoding=used_enc,
        chunksize=CENTER_CHUNKSIZE,
        engine="python",
        on_bad_lines="skip",
    )

    for chunk in reader:
        gid = chunk.iloc[:, 0].astype(str)
        m = gid.isin(remaining)
        if not m.any():
            continue

        sub = chunk.loc[m, [chunk.columns[0], chunk.columns[x_i], chunk.columns[y_i]]].copy()
        sub.columns = ["grid_id", "x_center", "y_center"]
        sub["x_center"] = pd.to_numeric(sub["x_center"], errors="coerce")
        sub["y_center"] = pd.to_numeric(sub["y_center"], errors="coerce")
        sub = sub.dropna(subset=["x_center", "y_center"])
        kept.append(sub)

        found_now = set(sub["grid_id"].astype(str).tolist())
        remaining -= found_now
        if not remaining:
            break

    if not kept:
        die("중심좌표 TXT에서 grid_id 중심좌표를 하나도 찾지 못함.")

    out = pd.concat(kept, ignore_index=True)
    out["grid_id"] = out["grid_id"].astype(str)
    out = out.drop_duplicates(subset=["grid_id"], keep="first")
    return out


def coalesce_xy(df: pd.DataFrame) -> pd.DataFrame:
    """
    merge로 인해 x_center_x/x_center_y 처럼 갈라진 컬럼을 하나로 합쳐줌
    우선순위: *_x -> *_y -> 원래 x_center
    """
    # 후보 목록
    x_candidates = ["x_center", "x_center_x", "x_center_y"]
    y_candidates = ["y_center", "y_center_x", "y_center_y"]

    def first_existing(cands):
        for c in cands:
            if c in df.columns:
                return c
        return None

    xc = first_existing(x_candidates)
    yc = first_existing(y_candidates)
    if xc is None or yc is None:
        die(f"x/y 중심좌표 컬럼을 찾지 못함. 현재 컬럼: {list(df.columns)}")

    # x_center 최종 만들기: x_center_x가 있으면 그걸 우선, 없으면 x_center_y, 없으면 x_center
    def combine(a, b, c):
        s = None
        if a in df.columns:
            s = pd.to_numeric(df[a], errors="coerce")
        if b in df.columns:
            sb = pd.to_numeric(df[b], errors="coerce")
            s = sb if s is None else s.fillna(sb)
        if c in df.columns:
            sc = pd.to_numeric(df[c], errors="coerce")
            s = sc if s is None else s.fillna(sc)
        return s

    df["x_center"] = combine("x_center_x", "x_center_y", "x_center")
    df["y_center"] = combine("y_center_x", "y_center_y", "y_center")

    # 정리: 중복 컬럼 제거(원하면 유지해도 됨)
    for c in ["x_center_x", "x_center_y", "y_center_x", "y_center_y"]:
        if c in df.columns:
            pass  # 필요하면 주석 풀고 drop 가능
            # df.drop(columns=[c], inplace=True)

    return df


def main():
    if not IN_PATH.exists():
        die(f"입력 파일 없음: {IN_PATH}")

    try:
        import geopandas as gpd
        from shapely.geometry import Polygon
        from pyproj import Transformer
    except Exception:
        die("필요 패키지: geopandas shapely pyproj fiona\n설치: pip install geopandas shapely pyproj fiona")

    df = pd.read_csv(IN_PATH, encoding="utf-8-sig", low_memory=False)
    if "grid_id" not in df.columns:
        die("grid_priority_top10pct.csv에 grid_id 컬럼이 없음.")

    df["grid_id"] = df["grid_id"].astype(str)

    # 이미 x_center가 있으면 merge 없이 바로 사용 가능하지만,
    # 누락이 있을 수 있으니 center TXT로 보강
    need_ids = set(df["grid_id"].tolist())

    center_path = find_center_path()
    centers = read_centers_for_grid_ids(center_path, need_ids)

    # merge (중복 컬럼 생길 수 있음)
    df = df.merge(centers, on="grid_id", how="left", suffixes=("_x", "_y"))

    # x_center/y_center 하나로 정리
    df = coalesce_xy(df)

    miss = int((df["x_center"].isna() | df["y_center"].isna()).sum())
    if miss > 0:
        print(f"⚠ 중심좌표 누락 {miss}개 → geojson에서 제외됨")
        df = df.dropna(subset=["x_center", "y_center"]).copy()

    tf = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    polys = []
    for x, y in zip(df["x_center"].astype(float), df["y_center"].astype(float)):
        ring_5179 = [
            (x - HALF, y - HALF),
            (x + HALF, y - HALF),
            (x + HALF, y + HALF),
            (x - HALF, y + HALF),
            (x - HALF, y - HALF),
        ]
        ring_4326 = [tf.transform(px, py) for px, py in ring_5179]
        polys.append(Polygon(ring_4326))

    gdf = gpd.GeoDataFrame(df, geometry=polys, crs="EPSG:4326")
    gdf.to_file(OUT_PATH, driver="GeoJSON", encoding="utf-8")

    print("✅ 생성 완료:", OUT_PATH)
    print("격자 수:", len(gdf))


if __name__ == "__main__":
    main()
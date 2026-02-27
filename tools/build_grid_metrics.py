# tools/build_grid_metrics.py
from __future__ import annotations

import sys
import re
import csv
from pathlib import Path
from typing import Dict, Tuple, List

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\82104\Desktop\jeonnam_cpo")

STORES_PATH = ROOT / "output" / "jeonnam_stores_with_grid.csv"
SIG_GEOJSON = ROOT / "data" / "jeonnam_sig.geojson"

OUT_GRID_DIR = ROOT / "data" / "out_grid"
IN_112_DIR = OUT_GRID_DIR / "112신고"
IN_CCTV_DIR = OUT_GRID_DIR / "cctv"
IN_CRIME_DIR = OUT_GRID_DIR / "범죄다발지"
IN_PATROL_DIR = OUT_GRID_DIR / "탄력순찰"

# 중심좌표 TXT (grid_id | x | y)
CENTER_CANDS = [
    ROOT / "data" / "격자2" / "국가지점번호 중심좌표.TXT",
    ROOT / "data" / "격자2" / "국가지점번호중심좌표.TXT",
    ROOT / "data" / "국가지점번호 중심좌표.TXT",
    ROOT / "data" / "국가지점번호중심좌표.TXT",
]

OUT_PATH = ROOT / "output" / "grid_metrics_all.csv"


ALLOWED_22 = [
    "목포시","여수시","순천시","나주시","광양시",
    "담양군","곡성군","구례군","고흥군","보성군","화순군",
    "장흥군","강진군","해남군","영암군","무안군","함평군",
    "영광군","장성군","완도군","진도군","신안군"
]
ALLOWED_22_SET = set(ALLOWED_22)


def die(msg: str):
    print("\n[중단]", msg)
    sys.exit(1)


def list_xlsx(folder: Path) -> list[Path]:
    if not folder.exists():
        return []
    return sorted(list(folder.glob("*.xlsx")) + list(folder.glob("*.xls")))


def read_many_xlsx(folder: Path, need_cols: list[str]) -> pd.DataFrame:
    files = list_xlsx(folder)
    if not files:
        return pd.DataFrame(columns=need_cols)

    dfs = []
    for f in files:
        try:
            df = pd.read_excel(f)
            df.columns = [str(c).strip() for c in df.columns]
            keep = [c for c in need_cols if c in df.columns]
            if keep:
                dfs.append(df[keep])
            else:
                if "grid_id_calc" in df.columns:
                    dfs.append(df[["grid_id_calc"]])
        except Exception as e:
            print(f"⚠ 읽기 실패(스킵): {f.name} / {e}")

    if not dfs:
        return pd.DataFrame(columns=need_cols)
    return pd.concat(dfs, ignore_index=True)


def pick_sigungu_col(gdf_cols: list[str]) -> str:
    # geojson 속성에서 시군(또는 읍면동 포함 이름) 컬럼 자동 선택
    candidates = [
        "SIG_KOR_NM", "sig_kor_nm",
        "NAME_2", "name_2",
        "adm_nm", "ADM_NM",
        "name", "NAME",
        "SIGUNGU", "sigungu",
        "시군구", "시군", "시군구명"
    ]
    lower_map = {c.lower(): c for c in gdf_cols}
    for cand in candidates:
        key = cand.lower()
        if key in lower_map:
            return lower_map[key]

    for c in gdf_cols:
        lc = c.lower()
        if "adm" in lc and ("nm" in lc or "name" in lc):
            return c
        if "sig" in lc and ("nm" in lc or "name" in lc):
            return c
        if "name" in lc or lc.endswith("nm"):
            return c

    die(f"시군명 컬럼을 geojson에서 못 찾음. 컬럼 목록: {gdf_cols}")
    return ""


def to_sigungu_22(val) -> str | float:
    """
    '전라남도 광양시 광양읍' -> '광양시'
    '전라남도 무안군 삼향읍' -> '무안군'
    """
    if pd.isna(val):
        return np.nan
    s = str(val).strip()
    if not s:
        return np.nan
    s = re.sub(r"\s+", " ", s)

    m = re.search(r"([가-힣]+시|[가-힣]+군)", s)
    if not m:
        return np.nan
    sig = m.group(1)
    return sig if sig in ALLOWED_22_SET else np.nan


def find_center_path() -> Path:
    for p in CENTER_CANDS:
        if p.exists():
            print("✅ 중심좌표 파일:", p)
            return p
    die("중심좌표 TXT를 못 찾음. data/격자2 또는 data 아래에 '국가지점번호 중심좌표.TXT'가 있어야 함.")
    return Path()


def sniff_delimiter(sample_text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        # 중심좌표는 거의 '|'이라 기본값을 |로
        return "|"


def read_center_xy_for_grid_ids(center_path: Path, grid_ids: set[str]) -> pd.DataFrame:
    """
    중심좌표 TXT에서 필요한 grid_id만 뽑아서 (grid_id, x_center, y_center) 반환
    - 파일이 커서 chunk로 읽음
    """
    # 인코딩/구분자 감지
    sample_bytes = center_path.read_bytes()[:20000]
    enc_try = ["cp949", "euc-kr", "utf-8-sig", "utf-8"]
    used_enc = None
    sample_text = None
    for enc in enc_try:
        try:
            sample_text = sample_bytes.decode(enc, errors="strict")
            used_enc = enc
            break
        except Exception:
            continue
    if sample_text is None:
        sample_text = sample_bytes.decode("cp949", errors="ignore")
        used_enc = "cp949"

    delim = sniff_delimiter(sample_text)

    cols = ["gid", "x", "y", "c3", "c4"]

    kept: List[pd.DataFrame] = []
    chunksize = 1_000_000

    reader = pd.read_csv(
        center_path,
        sep=delim,
        header=None,
        names=cols,
        encoding=used_enc,
        chunksize=chunksize,
        engine="python",
        on_bad_lines="skip",
    )

    for chunk in reader:
        # gid가 섞여서 들어오니 문자열로
        g = chunk["gid"].astype(str)
        m = g.isin(grid_ids)
        if not m.any():
            continue

        sub = chunk.loc[m, ["gid", "x", "y"]].copy()
        sub["x"] = pd.to_numeric(sub["x"], errors="coerce")
        sub["y"] = pd.to_numeric(sub["y"], errors="coerce")
        sub = sub.dropna(subset=["x", "y"])
        kept.append(sub)

        # 다 찾았으면 조기 종료(속도 향상)
        found_now = set(sub["gid"].astype(str).tolist())
        grid_ids -= found_now
        if not grid_ids:
            break

    if not kept:
        die("중심좌표 TXT에서 grid_id를 하나도 찾지 못함. (grid_id 형식이 다르거나 파일이 다른 것일 수 있음)")

    out = pd.concat(kept, ignore_index=True)
    out = out.rename(columns={"gid": "grid_id", "x": "x_center", "y": "y_center"})
    out["grid_id"] = out["grid_id"].astype(str)
    out = out.drop_duplicates(subset=["grid_id"], keep="first")
    return out


def build_sigungu_map_from_centers(centers_df: pd.DataFrame) -> pd.DataFrame:
    """
    centers_df: grid_id, x_center, y_center (EPSG:5179)
    return: grid_id, sigungu(22개)
    """
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except Exception:
        die("시군 조인을 위해 geopandas 필요:\n  pip install geopandas shapely pyproj fiona")

    if not SIG_GEOJSON.exists():
        die(f"시군 geojson 없음: {SIG_GEOJSON}")

    sig = gpd.read_file(SIG_GEOJSON)
    sig_col = pick_sigungu_col(list(sig.columns))

    # geojson CRS 처리
    if sig.crs is None:
        sig = sig.set_crs("EPSG:4326", allow_override=True)
    sig_5179 = sig.to_crs("EPSG:5179")

    pts = centers_df.dropna(subset=["x_center", "y_center"]).copy()
    pts["geometry"] = [Point(xy) for xy in zip(pts["x_center"], pts["y_center"])]
    gpts = gpd.GeoDataFrame(pts, geometry="geometry", crs="EPSG:5179")

    # within은 경계선 위 점이 빠질 수 있어 intersects가 안정적
    joined = gpd.sjoin(gpts, sig_5179[[sig_col, "geometry"]], how="left", predicate="intersects")

    out = joined[["grid_id", sig_col]].rename(columns={sig_col: "sigungu"})
    out["sigungu"] = out["sigungu"].apply(to_sigungu_22)
    return out


def main():
    # 0) 점포 로드
    if not STORES_PATH.exists():
        die(f"점포 파일 없음: {STORES_PATH}")

    # low_memory=False로 DtypeWarning 줄이기(본질 영향 없음)
    stores = pd.read_csv(STORES_PATH, encoding="utf-8-sig", low_memory=False)
    stores.columns = [str(c).strip() for c in stores.columns]
    if "grid_id" not in stores.columns:
        die("점포 파일에 grid_id 컬럼이 없음.")

    stores["grid_id"] = stores["grid_id"].astype(str)

    # 점포 집계
    store_cnt = stores.groupby("grid_id").size().reset_index(name="cnt_store")

    # 1) 112/CCTV/범죄/순찰 로드 (grid_id_calc 기준)
    df112 = read_many_xlsx(IN_112_DIR, ["grid_id_calc"])
    dfcctv = read_many_xlsx(IN_CCTV_DIR, ["grid_id_calc"])
    dfcrime = read_many_xlsx(IN_CRIME_DIR, ["grid_id_calc"])
    dfpatrol = read_many_xlsx(IN_PATROL_DIR, ["grid_id_calc"])

    for d in (df112, dfcctv, dfcrime, dfpatrol):
        if "grid_id_calc" in d.columns:
            d["grid_id_calc"] = d["grid_id_calc"].astype(str)

    cnt_112 = df112.groupby("grid_id_calc").size().reset_index(name="cnt_112").rename(columns={"grid_id_calc": "grid_id"})
    cnt_cctv = dfcctv.groupby("grid_id_calc").size().reset_index(name="cnt_cctv").rename(columns={"grid_id_calc": "grid_id"})
    cnt_5crime = dfcrime.groupby("grid_id_calc").size().reset_index(name="cnt_5crime").rename(columns={"grid_id_calc": "grid_id"})
    cnt_patrol = dfpatrol.groupby("grid_id_calc").size().reset_index(name="cnt_patrol").rename(columns={"grid_id_calc": "grid_id"})

    # 2) grid_metrics 결합 (기준은 점포가 있는 격자)
    grid = store_cnt.copy()
    grid = grid.merge(cnt_112, on="grid_id", how="left")
    grid = grid.merge(cnt_5crime, on="grid_id", how="left")
    grid = grid.merge(cnt_cctv, on="grid_id", how="left")
    grid = grid.merge(cnt_patrol, on="grid_id", how="left")

    for col in ["cnt_112", "cnt_5crime", "cnt_cctv", "cnt_patrol"]:
        grid[col] = grid[col].fillna(0).astype(int)

    # 3) 시군 붙이기(핵심 개선):
    #    점포 격자(grid_id 전체)에 대해 중심좌표 TXT에서 x/y를 찾아서 시군 조인
    center_path = find_center_path()
    need_ids = set(grid["grid_id"].astype(str).tolist())

    centers = read_center_xy_for_grid_ids(center_path, need_ids)
    sig_map = build_sigungu_map_from_centers(centers)

    grid = grid.merge(sig_map, on="grid_id", how="left")
    grid = grid.merge(centers, on="grid_id", how="left")  # x_center, y_center 보존
    # 저장grid = grid.merge(sig_map, on="grid_id", how="left")
    grid.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print("✅ 생성 완료:", OUT_PATH)
    print("행 수:", len(grid))
    print("시군 미부여:", int(grid["sigungu"].isna().sum()))
    print("시군 수:", int(grid["sigungu"].nunique(dropna=True)))


if __name__ == "__main__":
    main()
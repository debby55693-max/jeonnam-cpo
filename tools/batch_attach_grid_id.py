from __future__ import annotations

import sys
import csv
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

# =========================================================
# 0) 고정 경로 (너 PC 기준)
# =========================================================
ROOT = Path(r"C:\Users\82104\Desktop\jeonnam_cpo")
DATA_DIR = ROOT / "data"

# ✅ 현재 너 폴더 구조 그대로 대상 지정
INPUT_DIRS = [
    DATA_DIR / "112신고",
    DATA_DIR / "cctv",
    DATA_DIR / "범죄다발지",
    DATA_DIR / "탄력순찰",
]

# ✅ 결과는 여기로 (원본 폴더 구조 유지)
OUT_DIR = DATA_DIR / "out_grid"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ✅ 중심좌표(TXT)
CENTER_CANDS = [
    DATA_DIR / "격자2" / "국가지점번호 중심좌표.TXT",
    DATA_DIR / "격자2" / "국가지점번호중심좌표.TXT",
    DATA_DIR / "국가지점번호 중심좌표.TXT",
    DATA_DIR / "국가지점번호중심좌표.TXT",
]
CENTER_CHUNKSIZE = 1_000_000

# 100m 격자: 코너~중심 최대 약 70.7m → 80m 안전
MAX_DIST_M = 80.0
BBOX_BUFFER_M = 2000.0

# sklearn/scipy 없이 최근접(블록)
STORE_BLOCK = 800
CENTER_BLOCK = 60000  # 메모리 부족하면 30000으로 낮춰


# =========================================================
# 1) 유틸
# =========================================================
def die(msg: str):
    print("\n[중단]", msg)
    sys.exit(1)

def sniff_delimiter(sample_text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        cands = [",", "\t", ";", "|"]
        counts = {d: sample_text.count(d) for d in cands}
        best = max(counts, key=counts.get)
        return best if counts[best] > 0 else "|"

def find_center_path() -> Path:
    for p in CENTER_CANDS:
        if p.exists():
            print("✅ 중심좌표 파일:", p)
            return p
    die("중심좌표 TXT를 못 찾음. data/격자2 또는 data 아래에 '국가지점번호 중심좌표.TXT'가 있어야 함.")
    return Path()

def get_transformer():
    try:
        from pyproj import Transformer
    except Exception:
        die("pyproj 필요: pip install pyproj")
    return Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

def to_5179_from_lonlat(lon: np.ndarray, lat: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    tf = get_transformer()
    x, y = tf.transform(lon, lat)
    return np.array(x, dtype=float), np.array(y, dtype=float)

def detect_xy_columns(df: pd.DataFrame) -> Tuple[str, str, str]:
    """
    좌표 컬럼 자동 감지
    return (mode, xcol, ycol)
      mode = "lonlat" or "xy"
    """
    cols = [str(c).strip() for c in df.columns]
    lower_map = {c.lower(): c for c in cols}

    def find_contains(keys):
        for k in keys:
            k = k.lower()
            for lc, orig in lower_map.items():
                if k in lc:
                    return orig
        return None

    # 1) 위경도
    lon = find_contains(["lon", "longitude", "경도", "lng"])
    lat = find_contains(["lat", "latitude", "위도"])
    if lon and lat:
        return "lonlat", lon, lat

    # 2) TM/XY
    x = find_contains(["x", "tmx", "좌표x", "posx", "utm_x"])
    y = find_contains(["y", "tmy", "좌표y", "posy", "utm_y"])
    if x and y:
        return "xy", x, y

    die(f"좌표 컬럼 자동 감지 실패. 컬럼 확인 필요: {cols}")

def load_centers_filtered(center_path: Path, minx, maxx, miny, maxy) -> pd.DataFrame:
    # 중심좌표는 보통 cp949 + | + 헤더없음
    sample_bytes = center_path.read_bytes()[:20000]
    enc_try = ["cp949", "euc-kr", "utf-8-sig", "utf-8"]

    sample_text = None
    used_enc = None
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

    cols = ["c0", "c1", "c2", "c3", "c4"]
    kept = []

    reader = pd.read_csv(
        center_path,
        sep=delim,
        header=None,
        names=cols,
        encoding=used_enc,
        chunksize=CENTER_CHUNKSIZE,
        engine="python",
        on_bad_lines="skip",
    )

    for chunk in reader:
        gid = chunk["c0"].astype(str)
        x = pd.to_numeric(chunk["c1"], errors="coerce")
        y = pd.to_numeric(chunk["c2"], errors="coerce")

        sub = pd.DataFrame({"grid_id": gid, "x_center": x, "y_center": y}).dropna(subset=["x_center", "y_center"])
        m = (sub["x_center"].between(minx, maxx)) & (sub["y_center"].between(miny, maxy))
        sub = sub.loc[m]
        if len(sub) > 0:
            kept.append(sub)

    if not kept:
        die("bbox 주변 중심좌표가 0건. 좌표계/데이터 범위 문제 가능.")
    return pd.concat(kept, ignore_index=True)

def nearest_without_sklearn(points_xy: np.ndarray, centers_xy: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    n = points_xy.shape[0]
    best_dist2 = np.full(n, np.inf, dtype=float)
    best_idx = np.full(n, -1, dtype=int)

    for c0 in range(0, centers_xy.shape[0], CENTER_BLOCK):
        c1 = min(c0 + CENTER_BLOCK, centers_xy.shape[0])
        C = centers_xy[c0:c1]

        for s0 in range(0, n, STORE_BLOCK):
            s1 = min(s0 + STORE_BLOCK, n)
            S = points_xy[s0:s1]

            dx = S[:, 0:1] - C[:, 0].reshape(1, -1)
            dy = S[:, 1:2] - C[:, 1].reshape(1, -1)
            d2 = dx * dx + dy * dy

            local_idx = np.argmin(d2, axis=1)
            local_d2 = d2[np.arange(d2.shape[0]), local_idx]

            improved = local_d2 < best_dist2[s0:s1]
            if np.any(improved):
                best_dist2[s0:s1][improved] = local_d2[improved]
                best_idx[s0:s1][improved] = c0 + local_idx[improved]

    return np.sqrt(best_dist2), best_idx

def attach_grid_id(df: pd.DataFrame, center_path: Path) -> pd.DataFrame:
    mode, c1, c2 = detect_xy_columns(df)
    out = df.copy()

    # 좌표 -> 5179
    out[c1] = pd.to_numeric(out[c1], errors="coerce")
    out[c2] = pd.to_numeric(out[c2], errors="coerce")
    valid = out[c1].notna() & out[c2].notna()

    out["grid_id_calc"] = np.nan
    out["dist_to_center_m"] = np.nan
    out["x_5179"] = np.nan
    out["y_5179"] = np.nan
    out["x_center"] = np.nan
    out["y_center"] = np.nan

    if valid.sum() == 0:
        return out

    if mode == "lonlat":
        x, y = to_5179_from_lonlat(out.loc[valid, c1].to_numpy(), out.loc[valid, c2].to_numpy())
    else:
        x = out.loc[valid, c1].to_numpy(dtype=float)
        y = out.loc[valid, c2].to_numpy(dtype=float)

    out.loc[valid, "x_5179"] = x
    out.loc[valid, "y_5179"] = y

    # bbox로 중심점 줄이기
    minx = float(np.nanmin(x) - BBOX_BUFFER_M)
    maxx = float(np.nanmax(x) + BBOX_BUFFER_M)
    miny = float(np.nanmin(y) - BBOX_BUFFER_M)
    maxy = float(np.nanmax(y) + BBOX_BUFFER_M)

    centers = load_centers_filtered(center_path, minx, maxx, miny, maxy)
    centers_xy = centers[["x_center", "y_center"]].to_numpy(dtype=float)

    pts_xy = np.column_stack([x, y]).astype(float)
    dist_m, idx = nearest_without_sklearn(pts_xy, centers_xy)

    gid = centers.iloc[idx]["grid_id"].astype(str).to_numpy()
    gid = np.where(dist_m <= MAX_DIST_M, gid, np.nan)

    out.loc[valid, "grid_id_calc"] = gid
    out.loc[valid, "dist_to_center_m"] = np.round(dist_m, 2)
    out.loc[valid, "x_center"] = centers.iloc[idx]["x_center"].to_numpy()
    out.loc[valid, "y_center"] = centers.iloc[idx]["y_center"].to_numpy()
    return out


# =========================================================
# 2) 배치 실행
# =========================================================
def main():
    if not ROOT.exists():
        die(f"프로젝트 루트 없음: {ROOT}")

    center_path = find_center_path()

    # 대상 파일 수집
    targets = []
    for d in INPUT_DIRS:
        if not d.exists():
            print(f"⚠ 폴더 없음(스킵): {d}")
            continue
        targets += list(d.rglob("*.xlsx"))
        targets += list(d.rglob("*.xls"))

    targets = sorted(set(targets))
    if not targets:
        die("처리할 엑셀 파일이 없음. data/112신고, cctv, 범죄다발지, 탄력순찰 폴더를 확인해줘.")

    print(f"✅ 대상 파일 수: {len(targets)}개")
    print(f"✅ 출력 폴더: {OUT_DIR}")

    ok, fail = 0, 0

    for f in targets:
        try:
            df = pd.read_excel(f)
            df2 = attach_grid_id(df, center_path)

            # 출력 경로: data/out_grid/<원본폴더명>/<파일명>_grid.xlsx
            # 예: data/112신고/112신고_강진.xlsx -> data/out_grid/112신고/112신고_강진_grid.xlsx
            rel = f.relative_to(DATA_DIR)
            out_subdir = OUT_DIR / rel.parent
            out_subdir.mkdir(parents=True, exist_ok=True)
            out_path = out_subdir / (f.stem + "_grid.xlsx")

            df2.to_excel(out_path, index=False)
            ok += 1
            print(f"  ✔ {rel} -> out_grid/{rel.parent}/{out_path.name}")

        except Exception as e:
            fail += 1
            print(f"  ✖ 실패: {f} / {e}")

    print("\n=== 완료 ===")
    print("성공:", ok)
    print("실패:", fail)
    print("결과 위치:", OUT_DIR)

if __name__ == "__main__":
    main()
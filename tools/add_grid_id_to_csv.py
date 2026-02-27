# tools/add_grid_id_to_csv.py
from __future__ import annotations

import sys
from pathlib import Path
import csv
import numpy as np
import pandas as pd

# =========================================================
# 0) 프로젝트 루트 고정
# =========================================================
ROOT = Path(r"C:\Users\82104\Desktop\jeonnam_cpo")
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ✅ 점포 파일: tools가 아니라 "루트에 있음"으로 고정
STORE_PATH = ROOT / "jeonnam_stores.csv"

# ✅ 중심좌표: data/격자2 우선
CENTER_CANDS = [
    DATA_DIR / "격자2" / "국가지점번호 중심좌표.TXT",
    DATA_DIR / "격자2" / "국가지점번호중심좌표.TXT",
    DATA_DIR / "국가지점번호 중심좌표.TXT",
    DATA_DIR / "국가지점번호중심좌표.TXT",
]

OUT_PATH = OUT_DIR / "jeonnam_stores_with_grid.csv"

# 매칭 파라미터
MAX_DIST_M = 80.0
BBOX_BUFFER_M = 2000.0
CENTER_CHUNKSIZE = 1_000_000


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
        return best if counts[best] > 0 else ","


def to_epsg5179(lon: np.ndarray, lat: np.ndarray):
    try:
        from pyproj import Transformer
    except Exception:
        die("pyproj 필요: pip install pyproj")

    tf = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    x, y = tf.transform(lon, lat)
    return np.array(x, dtype=float), np.array(y, dtype=float)


def match_nearest(store_xy: np.ndarray, center_xy: np.ndarray):
    try:
        from sklearn.neighbors import KDTree
        tree = KDTree(center_xy, metric="euclidean")
        dist, idx = tree.query(store_xy, k=1)
        return dist[:, 0], idx[:, 0]
    except Exception:
        try:
            from scipy.spatial import cKDTree
            tree = cKDTree(center_xy)
            dist, idx = tree.query(store_xy, k=1)
            return dist, idx
        except Exception:
            die("최근접 매칭을 위해 scikit-learn 또는 scipy 필요:\n"
                "pip install scikit-learn\n또는\npip install scipy")


def find_center_path() -> Path:
    for p in CENTER_CANDS:
        if p.exists():
            print("✅ 중심좌표 파일:", p)
            return p

    # 마지막: data 아래 재귀 탐색
    if DATA_DIR.exists():
        for p in DATA_DIR.rglob("*.txt"):
            name = p.name.replace(" ", "")
            if "중심좌표" in name or "국가지점번호" in name:
                print("✅ 중심좌표 파일(재귀):", p)
                return p

    die(f"중심좌표 TXT를 못 찾음. 기대 후보:\n- " + "\n- ".join(str(p) for p in CENTER_CANDS))
    return Path()


def read_stores() -> pd.DataFrame:
    if not STORE_PATH.exists():
        die(f"점포 파일 없음: {STORE_PATH}\n"
            f"→ jeonnam_stores.csv를 프로젝트 루트({ROOT})에 두었는지 확인해줘.")

    # 점포는 보통 utf-8-sig
    df = pd.read_csv(STORE_PATH, encoding="utf-8-sig")
    if "lon" not in df.columns or "lat" not in df.columns:
        die(f"점포 파일에 lon/lat 컬럼 없음. 현재 컬럼 일부: {list(df.columns)[:20]}")
    df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
    df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
    return df


def load_centers_filtered(center_path: Path, minx, maxx, miny, maxy) -> pd.DataFrame:
    """
    중심좌표 파일 포맷이 다양한데,
    네 케이스(국가지점번호 중심좌표)는 흔히:
    - 헤더 없음
    - 구분자: | 또는 탭
    - 컬럼: grid_id | x | y
    라서 header=None로 읽고 c0,c1,c2로 처리
    """
    # 샘플로 인코딩/구분자 감지
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
    total = 0

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
        total += len(chunk)

        gid = chunk["c0"].astype(str)
        x = pd.to_numeric(chunk["c1"], errors="coerce")
        y = pd.to_numeric(chunk["c2"], errors="coerce")

        sub = pd.DataFrame({"grid_id": gid, "x": x, "y": y}).dropna(subset=["x", "y"])
        m = (sub["x"].between(minx, maxx)) & (sub["y"].between(miny, maxy))
        sub = sub.loc[m]

        if len(sub) > 0:
            kept.append(sub)

        if total % (CENTER_CHUNKSIZE * 3) == 0:
            print(f"  ...중심좌표 읽는 중: {total:,} rows")

    if not kept:
        die("점포 bbox 주변에서 중심좌표가 0건. (좌표계/파일 포맷이 다를 수 있음)")

    centers = pd.concat(kept, ignore_index=True)
    print(f"✅ 중심좌표 필터 결과: {len(centers):,} rows")
    return centers


def main():
    if not ROOT.exists():
        die(f"프로젝트 루트 없음: {ROOT}")

    print("ROOT:", ROOT)
    print("점포:", STORE_PATH)

    center_path = find_center_path()

    stores = read_stores()
    valid = stores["lon"].notna() & stores["lat"].notna()
    if valid.sum() == 0:
        die("유효한 lon/lat 점포가 0건.")

    x, y = to_epsg5179(stores.loc[valid, "lon"].to_numpy(), stores.loc[valid, "lat"].to_numpy())
    stores.loc[valid, "x_5179"] = x
    stores.loc[valid, "y_5179"] = y

    minx = float(np.nanmin(x) - BBOX_BUFFER_M)
    maxx = float(np.nanmax(x) + BBOX_BUFFER_M)
    miny = float(np.nanmin(y) - BBOX_BUFFER_M)
    maxy = float(np.nanmax(y) + BBOX_BUFFER_M)
    print(f"✅ 점포 bbox(버퍼 포함): x[{minx:.1f},{maxx:.1f}] y[{miny:.1f},{maxy:.1f}]")

    centers = load_centers_filtered(center_path, minx, maxx, miny, maxy)

    center_xy = centers[["x", "y"]].to_numpy(dtype=float)
    store_xy = stores.loc[valid, ["x_5179", "y_5179"]].to_numpy(dtype=float)

    dist_m, idx = match_nearest(store_xy, center_xy)
    gid = centers.iloc[idx]["grid_id"].astype(str).to_numpy()

    gid = np.where(dist_m <= MAX_DIST_M, gid, np.nan)

    stores.loc[valid, "grid_id"] = gid
    stores.loc[valid, "dist_to_grid_center_m"] = np.round(dist_m, 2)

    stores.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    total = len(stores)
    ok = int(pd.notna(stores["grid_id"]).sum())
    fail = total - ok

    print("\n=== 결과 ===")
    print(f"총 점포: {total:,}")
    print(f"매칭 성공: {ok:,}")
    print(f"매칭 실패: {fail:,}")
    print("저장:", OUT_PATH)

    print("\n[거리 통계(m)]")
    print(stores["dist_to_grid_center_m"].describe().to_string())


if __name__ == "__main__":
    main()
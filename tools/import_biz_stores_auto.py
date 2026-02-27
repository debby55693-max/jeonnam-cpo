import os
import sys
from pathlib import Path
import importlib.util

import pandas as pd
from supabase import create_client


# =========================================================
# 0) 프로젝트 경로 세팅 (core import 문제 완전 해결)
#    - 루트 / admin_app / survey_app 모두 sys.path 추가
#    - 그리고 national_point.py를 rglob으로 찾아 "직접 로드"
# =========================================================
ROOT = Path(__file__).resolve().parents[1]

for p in [ROOT, ROOT / "admin_app", ROOT / "survey_app"]:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))


def load_latlon_to_grid_id_100m():
    """
    프로젝트 어디에 있든 national_point.py를 찾아서 latlon_to_grid_id_100m 함수를 로드한다.
    (패키지 구조/__init__.py 유무 상관없이 동작)
    """
    candidates = list(ROOT.rglob("national_point.py"))
    if not candidates:
        raise RuntimeError(f"national_point.py를 프로젝트에서 찾지 못했습니다. ROOT={ROOT}")

    # 우선순위: core/national_point.py 형태를 먼저 선호
    candidates = sorted(
        candidates,
        key=lambda x: (0 if "core" in [p.name for p in x.parents] else 1, len(str(x)))
    )

    last_err = None
    for path in candidates:
        try:
            spec = importlib.util.spec_from_file_location("national_point_dynamic", str(path))
            mod = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(mod)

            fn = getattr(mod, "latlon_to_grid_id_100m", None)
            if callable(fn):
                print(f"[OK] loaded latlon_to_grid_id_100m from: {path}")
                return fn
        except Exception as e:
            last_err = e

    raise RuntimeError(f"latlon_to_grid_id_100m 로드 실패. 마지막 에러: {last_err}")


latlon_to_grid_id_100m = load_latlon_to_grid_id_100m()


# =========================================================
# 1) Supabase 연결
# =========================================================
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# =========================================================
# 2) CSV 로드
# =========================================================
# ✅ 여기에 네 원천 점포 CSV 경로 입력(절대경로 권장)
CSV_PATH = r"C:\Users\82104\Desktop\jeonnam_cpo\output\jeonnam_stores_with_grid.csv"
ENCODING_CANDIDATES = ["utf-8", "cp949", "euc-kr"]


def pick_col(cols, candidates):
    cols_low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand in cols:
            return cand
        if cand.lower() in cols_low:
            return cols_low[cand.lower()]
    return None


df = None
last_err = None
for enc in ENCODING_CANDIDATES:
    try:
        df = pd.read_csv(CSV_PATH, encoding=enc)
        print(f"[OK] CSV loaded with encoding={enc}, rows={len(df)}")
        break
    except Exception as e:
        last_err = e
if df is None:
    raise RuntimeError(f"CSV 로드 실패: {last_err}")


# =========================================================
# 3) 컬럼 자동 탐색
# =========================================================
LAT_COL = pick_col(df.columns, ["lat", "LAT", "위도", "Latitude", "latitude", "y", "Y"])
LON_COL = pick_col(df.columns, ["lon", "LON", "lng", "LNG", "경도", "Longitude", "longitude", "x", "X"])
NAME_COL = pick_col(df.columns, ["store_name", "shop_name", "name", "상호명", "점포명", "bizesNm"])
ADDR_COL = pick_col(df.columns, ["address", "addr", "도로명주소", "지번주소", "rdnmAdr", "lnoAdr"])
CAT_COL  = pick_col(df.columns, ["category", "업종", "업태", "indsLclsNm", "indsMclsNm", "indsSclsNm"])

if not LAT_COL or not LON_COL:
    raise RuntimeError(
        f"위경도 컬럼을 못 찾음. (LAT={LAT_COL}, LON={LON_COL}) / columns={list(df.columns)[:50]}"
    )

print(f"[COL] lat={LAT_COL}, lon={LON_COL}, name={NAME_COL}, addr={ADDR_COL}, cat={CAT_COL}")


# =========================================================
# 4) 위경도 정리 + grid_id 계산
# =========================================================
df[LAT_COL] = pd.to_numeric(df[LAT_COL], errors="coerce")
df[LON_COL] = pd.to_numeric(df[LON_COL], errors="coerce")
df = df.dropna(subset=[LAT_COL, LON_COL]).copy()
print(f"[OK] valid lat/lon rows={len(df)}")

df["grid_id"] = df.apply(lambda r: latlon_to_grid_id_100m(float(r[LAT_COL]), float(r[LON_COL])), axis=1)


# =========================================================
# 5) payload 생성 + 업로드
# =========================================================
payload = []
for _, r in df.iterrows():
    payload.append({
        "grid_id": str(r["grid_id"]),
        "store_name": str(r[NAME_COL]) if NAME_COL else "",
        "address": str(r[ADDR_COL]) if ADDR_COL else "",
        "category": str(r[CAT_COL]) if CAT_COL else "",
        "lat": float(r[LAT_COL]),
        "lon": float(r[LON_COL]),
    })

print(f"[READY] insert rows={len(payload)}")

BATCH = 500
for i in range(0, len(payload), BATCH):
    supabase.table("biz_stores").insert(payload[i:i+BATCH]).execute()
    print(f"[INSERT] {min(i+BATCH, len(payload))}/{len(payload)}")

print("[DONE]", len(payload))
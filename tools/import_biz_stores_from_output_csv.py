import os
from pathlib import Path
import hashlib
import pandas as pd
from supabase import create_client

# =========================================================
# 0) .env 로드(윈도우 인코딩/메모장 utf-16까지 대응)
# =========================================================
ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"

def load_env_file(path: Path) -> bool:
    if not path.exists():
        return False

    text = None
    for enc in ("utf-8", "utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            text = path.read_text(encoding=enc)
            break
        except Exception:
            continue

    if text is None:
        raise RuntimeError(f"[ENV ERROR] .env 파일을 읽을 수 없습니다: {path} (인코딩 문제 가능)")

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and not os.getenv(k):
            os.environ[k] = v

    return True

load_env_file(ENV_PATH)

def must_env(key: str) -> str:
    v = os.getenv(key, "").strip()
    if not v:
        raise RuntimeError(f"[ENV ERROR] {key} 가 없습니다. (.env에 {key}=... 추가)")
    return v

SUPABASE_URL = must_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = must_env("SUPABASE_SERVICE_ROLE_KEY")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ✅ 네 파일 경로로 고정
CSV_PATH = r"C:\Users\82104\Desktop\jeonnam_cpo\output\jeonnam_stores_with_grid.csv"

# =========================================================
# 1) CSV 로드(인코딩 자동)
# =========================================================
df = None
last = None
for enc in ["utf-8", "cp949", "euc-kr"]:
    try:
        df = pd.read_csv(CSV_PATH, encoding=enc, low_memory=False)
        print(f"[OK] loaded enc={enc}, rows={len(df)}")
        break
    except Exception as e:
        last = e
if df is None:
    raise RuntimeError(f"CSV 로드 실패: {last}")

# =========================================================
# 2) 필수 컬럼 확인
# =========================================================
must_cols = ["grid_id", "lat", "lon"]
for c in must_cols:
    if c not in df.columns:
        raise RuntimeError(f"CSV에 '{c}' 컬럼이 없습니다. columns[:40]={list(df.columns)[:40]}")

# =========================================================
# 3) 이름/주소/업종 컬럼 자동 매핑
# =========================================================
def pick(cands):
    for c in cands:
        if c in df.columns:
            return c
    return None

NAME_COL = pick(["bizesNm", "store_name", "shop_name", "name", "상호명", "점포명"])
ADDR_COL = pick(["rdnmAdr", "lnoAdr", "address", "addr", "도로명주소", "지번주소"])
CAT_COL  = pick(["indsSclsNm", "indsMclsNm", "indsLclsNm", "category", "업종", "업태"])

print(f"[COL] name={NAME_COL}, addr={ADDR_COL}, cat={CAT_COL}")

# =========================================================
# 4) 숫자화 + 결측 제거 + 정규화
# =========================================================
df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
df["grid_id"] = df["grid_id"].astype(str).str.strip()
df = df.dropna(subset=["lat", "lon", "grid_id"]).copy()

# 좌표는 흔들림 방지로 소수점 6자리로 통일(중복키 안정화)
df["lat"] = df["lat"].round(6)
df["lon"] = df["lon"].round(6)

print(f"[OK] valid rows={len(df)}")

# =========================================================
# 5) payload 생성 (store_key 포함)
# =========================================================
payload = []
for _, r in df.iterrows():
    gid = str(r["grid_id"]).strip()
    name = (str(r[NAME_COL]) if NAME_COL else "").strip()
    addr = (str(r[ADDR_COL]) if ADDR_COL else "").strip()
    cat = (str(r[CAT_COL]) if CAT_COL else "").strip()
    lat = float(r["lat"])
    lon = float(r["lon"])

    # ✅ grid_id + (name, addr, lat, lon) 기반 유니크키
    store_key = hashlib.md5(f"{gid}|{name}|{addr}|{lat}|{lon}".encode("utf-8")).hexdigest()

    payload.append({
        "store_key": store_key,
        "grid_id": gid,
        "store_name": name,
        "address": addr,
        "category": cat,
        "lat": lat,
        "lon": lon,
    })

print(f"[READY] rows={len(payload)}")

# =========================================================
# 6) 업로드(배치 UPSERT)  ← insert 아님!
# =========================================================
BATCH = 500
ok = 0
for i in range(0, len(payload), BATCH):
    batch = payload[i:i+BATCH]
    supabase.table("biz_stores").upsert(batch, on_conflict="store_key").execute()
    ok += len(batch)
    print(f"[UPSERT] {ok}/{len(payload)}")

print("[DONE] upserted:", ok)
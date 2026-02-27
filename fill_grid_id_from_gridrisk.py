import os
import time
import math
import requests
from pyproj import Transformer
from supabase import create_client

# =========================
# secrets.toml 읽기
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_secrets():
    import tomllib
    path = os.path.join(BASE_DIR, ".streamlit", "secrets.toml")
    if not os.path.exists(path):
        raise FileNotFoundError(f"❌ secrets.toml 없음: {path}")
    with open(path, "rb") as f:
        return tomllib.load(f)

secrets = load_secrets()

SUPABASE_URL = secrets["SUPABASE_URL"]
SUPABASE_KEY = secrets.get("SUPABASE_SERVICE_KEY") or secrets.get("SUPABASE_ANON_KEY")
VWORLD_KEY = secrets["VWORLD_KEY"]
VWORLD_DOMAIN = secrets.get("VWORLD_DOMAIN")

if not SUPABASE_KEY:
    raise KeyError("❌ SUPABASE_SERVICE_KEY 또는 SUPABASE_ANON_KEY가 secrets.toml에 없음")

sb = create_client(SUPABASE_URL, SUPABASE_KEY)

# =========================
# VWorld 주소 → (lon, lat)
# =========================
VWORLD_ADDR_URL = "https://api.vworld.kr/req/address"

def geocode_vworld(address: str):
    for addr_type in ["road", "parcel"]:
        params = {
            "service": "address",
            "request": "getcoord",
            "version": "2.0",
            "crs": "epsg:4326",
            "format": "json",
            "type": addr_type,
            "address": address,
            "key": VWORLD_KEY,
        }
        if VWORLD_DOMAIN:
            params["domain"] = VWORLD_DOMAIN

        r = requests.get(VWORLD_ADDR_URL, params=params, timeout=20)
        r.raise_for_status()
        j = r.json()

        resp = j.get("response", {})
        if resp.get("status") != "OK":
            continue

        p = resp.get("result", {}).get("point", {})
        x, y = p.get("x"), p.get("y")
        if x and y:
            return float(x), float(y)
    return None

# =========================
# lon/lat → EPSG:5179 (meters)
# =========================
tf = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

def lonlat_to_5179(lon, lat):
    return tf.transform(lon, lat)

# =========================
# 100m 격자 "suffix" 계산
# - grid_id가 '다라368245' 처럼 "앞 2글자 + 6숫자" 형태일 때
# - 6숫자는 보통 (E 3자리)(N 3자리)로 쓰이는 케이스가 많음
# - 우리는 "앞 2글자"를 계산하지 않고,
#   Supabase grid_risk에서 station 기준으로 suffix에 맞는 grid_id를 찾아온다!
# =========================
def calc_suffix_6digits(x_5179, y_5179):
    e = int(math.floor(x_5179 / 100.0)) % 1000
    n = int(math.floor(y_5179 / 100.0)) % 1000
    return f"{e:03d}{n:03d}"

def find_grid_id_by_station_and_suffix(station: str, suffix6: str):
    # 패턴: 앞 2글자 + suffix6
    # SQL LIKE에서 _ 는 1글자 와일드카드
    pattern = f"__{suffix6}"

    res = (
        sb.table("grid_risk")
        .select("grid_id,risk")
        .eq("station", station)
        .like("grid_id", pattern)
        .limit(5)
        .execute()
    )
    data = res.data or []
    if not data:
        return None

    # 보통 1개만 나옴. 여러 개면 첫 번째 사용(전남 관서 기준 거의 유일)
    return data[0]

# =========================
# 실행: grid_id 비어있는 shops 채우기
# =========================
LIMIT = 200  # 한번에 200개만 (안전)
SLEEP = 0.15 # VWorld 과속 방지

rows = (
    sb.table("shops")
    .select("id,address,station")
    .is_("grid_id", "null")
    .limit(LIMIT)
    .execute()
    .data
) or []

print("🧾 대상 점포:", len(rows))

ok = 0
fail = 0

for r in rows:
    shop_id = r["id"]
    address = (r.get("address") or "").strip()
    station = (r.get("station") or "").strip()

    if not address or not station:
        print("❌ 주소/관서 없음:", shop_id)
        fail += 1
        continue

    geo = geocode_vworld(address)
    if not geo:
        print("❌ 지오코딩 실패:", shop_id, address)
        fail += 1
        continue

    lon, lat = geo
    x, y = lonlat_to_5179(lon, lat)
    suffix6 = calc_suffix_6digits(x, y)

    match = find_grid_id_by_station_and_suffix(station, suffix6)
    if not match:
        print("❌ grid_id 매칭 실패:", shop_id, station, suffix6, address)
        fail += 1
        continue

    grid_id = match["grid_id"]

    # shops 업데이트 (lat/lng도 같이 저장해두면 지도에 점찍기 쉬움)
    sb.table("shops").update(
        {"grid_id": grid_id, "lng": lon, "lat": lat}
    ).eq("id", shop_id).execute()

    ok += 1
    print("✅", shop_id, station, "→", grid_id)

    time.sleep(SLEEP)

print("\n🎉 완료")
print("성공:", ok)
print("실패:", fail)
print("※ 실패가 나오면 그 점포 주소가 지오코딩 안 되거나, station/suffix가 안 맞는 케이스임")
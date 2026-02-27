import os
import json
import pandas as pd

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

DATA_DIR = os.path.join(BASE_DIR, "data")

CCTV_DIR = os.path.join(DATA_DIR, "cctv")
PATROL_DIR = os.path.join(DATA_DIR, "탄력순찰")

OUT_CSV = os.path.join(BASE_DIR, "security_assets_import.csv")


def station_from_filename(filename: str) -> str:
    """
    예:
      CCTV_무안.xlsx -> 무안경찰서
      탄력순찰_목포.xlsx -> 목포경찰서
    """
    name = os.path.splitext(filename)[0]
    station = name.split("_")[-1].strip()
    if not station.endswith("경찰서"):
        station += "경찰서"
    return station


def read_cctv_files():
    rows = []
    for fname in os.listdir(CCTV_DIR):
        if not fname.lower().endswith(".xlsx"):
            continue

        station = station_from_filename(fname)
        path = os.path.join(CCTV_DIR, fname)
        df = pd.read_excel(path)

        for _, r in df.iterrows():
            try:
                lat = float(r.get("위도"))
                lng = float(r.get("경도"))
            except:
                continue

            grid_id = str(r.get("격자ID") or "").strip()
            if not grid_id:
                continue

            meta = {
                "source": "CCTV",
                "address": r.get("주소"),
                "install_type": r.get("설치형태"),
                "resolution": r.get("화소"),
                "angle": r.get("감시각도"),
                "note": r.get("비고"),
            }

            rows.append({
                "station": station,
                "asset_type": "cctv",
                "name": None,
                "lat": lat,
                "lng": lng,
                "grid_id": grid_id,
                "meta": json.dumps(meta, ensure_ascii=False),
            })
    return rows


def read_patrol_files():
    rows = []
    for fname in os.listdir(PATROL_DIR):
        if not fname.lower().endswith(".xlsx"):
            continue

        station = station_from_filename(fname)
        path = os.path.join(PATROL_DIR, fname)
        df = pd.read_excel(path)

        for _, r in df.iterrows():
            try:
                lat = float(r.get("위도"))
                lng = float(r.get("경도"))
            except:
                continue

            grid_id = str(r.get("격자ID") or "").strip()
            if not grid_id:
                continue

            meta = {
                "source": "탄력순찰",
                "address": r.get("주소"),
                "reason": r.get("사유"),
                "request": r.get("요청내용"),
                "start_date": r.get("시작일자"),
                "end_date": r.get("종료일자"),
                "start_time": r.get("시작시간"),
                "end_time": r.get("종료시간"),
            }

            rows.append({
                "station": station,
                "asset_type": "patrol",
                "name": None,
                "lat": lat,
                "lng": lng,
                "grid_id": grid_id,
                "meta": json.dumps(meta, ensure_ascii=False),
            })
    return rows


def main():
    all_rows = []
    all_rows += read_cctv_files()
    all_rows += read_patrol_files()

    df = pd.DataFrame(all_rows)

    # 중복 제거
    df = df.drop_duplicates(
        subset=["station", "asset_type", "lat", "lng", "grid_id"]
    )

    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    print("✅ security_assets_import.csv 생성 완료")
    print("총 행 수:", len(df))
    print(df.head(5))


if __name__ == "__main__":
    main()

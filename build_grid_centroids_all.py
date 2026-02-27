import glob
import os
import pandas as pd
import geopandas as gpd

# ✅ 9세트 shp가 들어있는 폴더
GRID_DIR = r"C:\Users\82104\Desktop\jeonnam_cpo\data\격자"
# ✅ 결과 저장 경로
OUT_CSV = r"output\grid_centroids_all.csv"

# ✅ 격자 ID 컬럼명 (네 파일은 GRID_CD)
GRID_ID_COL = "GRID_CD"

# centroid 계산은 투영좌표계(미터)에서!
PROJECTED_EPSG = 5179   # Korea 2000 / Unified CS (너 shp가 이거였음)
OUTPUT_EPSG = 4326      # WGS84 (lat/lon)

shps = glob.glob(os.path.join(GRID_DIR, "*.shp"))
if not shps:
    raise SystemExit(f"shp를 못 찾았어. 폴더 확인: {GRID_DIR}")

rows = []
for shp in shps:
    gdf = gpd.read_file(shp)

    if GRID_ID_COL not in gdf.columns:
        raise SystemExit(f"{shp} 에 '{GRID_ID_COL}' 컬럼이 없어. 실제 컬럼: {list(gdf.columns)}")

    if gdf.crs is None:
        raise SystemExit(f"{shp} CRS가 없어. .prj 파일이 같이 있는지 확인해줘.")

    # 1) centroid는 투영좌표계에서 계산
    gdf_proj = gdf.to_crs(epsg=PROJECTED_EPSG)
    cent_proj = gdf_proj.geometry.centroid

    # 2) centroid 점을 4326으로 변환해서 lat/lon 추출
    cent_wgs = gpd.GeoSeries(cent_proj, crs=f"EPSG:{PROJECTED_EPSG}").to_crs(epsg=OUTPUT_EPSG)

    tmp = pd.DataFrame({
        "grid_id": gdf[GRID_ID_COL].astype(str),
        "lat": cent_wgs.y.astype(float),
        "lon": cent_wgs.x.astype(float),
    })

    rows.append(tmp)

df = pd.concat(rows, ignore_index=True)
df = df.dropna(subset=["grid_id", "lat", "lon"]).drop_duplicates(subset=["grid_id"])

os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

print("✅ 저장 완료:", OUT_CSV)
print("행 수:", len(df))
print(df.head(5))
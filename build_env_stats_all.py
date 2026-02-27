import os, glob
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")

BASE = os.path.join(ROOT, "grid_risk_import.csv")   # ✅ 루트에 있는 기준 위험도
DIR_112 = os.path.join(DATA, "112신고")
DIR_CCTV = os.path.join(DATA, "cctv")
DIR_PATROL = os.path.join(DATA, "탄력순찰")

OUT = os.path.join(ROOT, "output", "env_priority_final.csv")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

GRID_COL = "격자ID"  # ✅ 샘플 확인됨

def read_all_excels(folder: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(folder, "*.xlsx"))) + sorted(glob.glob(os.path.join(folder, "*.xls")))
    if not files:
        print(f"[WARN] no excel files in {folder}")
        return pd.DataFrame()

    parts = []
    for fp in files:
        df = pd.read_excel(fp)
        if GRID_COL not in df.columns:
            raise ValueError(f"[ERROR] {fp} 에 '{GRID_COL}' 컬럼이 없음. 현재 컬럼: {list(df.columns)}")
        parts.append(df[[GRID_COL]].copy())
    return pd.concat(parts, ignore_index=True)

def count_by_grid(folder: str, out_col: str) -> pd.DataFrame:
    df = read_all_excels(folder)
    if df.empty:
        return pd.DataFrame(columns=["grid_id", out_col])
    agg = (df.groupby(GRID_COL).size().reset_index(name=out_col))
    agg = agg.rename(columns={GRID_COL: "grid_id"})
    return agg

def minmax(s: pd.Series) -> pd.Series:
    mn, mx = s.min(), s.max()
    if mx == mn:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - mn) / (mx - mn)

# 1) 기준 위험도(유일키 grid_id)
base = pd.read_csv(BASE, encoding="utf-8-sig")[["station", "grid_id", "risk"]].copy()
if base["grid_id"].duplicated().any():
    raise ValueError("[ERROR] 기준 파일(grid_risk_import.csv)에서 grid_id 중복 발견. 기준이 깨졌음.")

# 2) 집계(없으면 0 처리될 예정)
cnt112 = count_by_grid(DIR_112, "cnt_112")
cctv = count_by_grid(DIR_CCTV, "cnt_cctv")
patrol = count_by_grid(DIR_PATROL, "cnt_patrol")

# 3) LEFT JOIN + 0
df = (base
      .merge(cnt112, on="grid_id", how="left")
      .merge(cctv, on="grid_id", how="left")
      .merge(patrol, on="grid_id", how="left"))

for c in ["cnt_112", "cnt_cctv", "cnt_patrol"]:
    df[c] = df[c].fillna(0).astype(int)

df["protect_cnt"] = df["cnt_cctv"] + df["cnt_patrol"]

# 4) 1:1:1 점수 (station별 정규화)
df["risk_norm"] = df.groupby("station")["risk"].transform(minmax)
df["norm_112"] = df.groupby("station")["cnt_112"].transform(lambda x: minmax(np.log1p(x)))
df["protect_norm"] = df.groupby("station")["protect_cnt"].transform(lambda x: minmax(np.log1p(x)))

df["priority_score"] = df["risk_norm"] + df["norm_112"] - df["protect_norm"]
df["priority_rank"] = df.groupby("station")["priority_score"].rank(ascending=False, method="dense").astype(int)

# 5) 저장
out_cols = [
    "station","grid_id","risk",
    "cnt_112","cnt_cctv","cnt_patrol",
    "risk_norm","norm_112","protect_norm",
    "priority_score","priority_rank"
]
df.to_csv(OUT, index=False, encoding="utf-8-sig", columns=out_cols)
print(f"[OK] saved: {OUT} rows={len(df)}")

# tools/select_hotspots_top10pct.py
from __future__ import annotations

import sys
from pathlib import Path
import pandas as pd
import numpy as np

ROOT = Path(r"C:\Users\82104\Desktop\jeonnam_cpo")
IN_PATH = ROOT / "output" / "grid_metrics_all.csv"
OUT_PATH = ROOT / "output" / "grid_priority_top10pct.csv"

TOP_PCT = 0.10  # 시군별 상위 10%


def die(msg: str):
    print("\n[중단]", msg)
    sys.exit(1)


def zscore(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if std == 0 or np.isnan(std):
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - s.mean()) / std


def main():
    if not IN_PATH.exists():
        die(f"입력 파일 없음: {IN_PATH}")

    df = pd.read_csv(IN_PATH, encoding="utf-8-sig", low_memory=False)

    need_cols = ["grid_id", "sigungu", "cnt_store", "cnt_112", "cnt_5crime", "cnt_cctv", "cnt_patrol"]
    for c in need_cols:
        if c not in df.columns:
            die(f"필수 컬럼 없음: {c}")

    base = df.dropna(subset=["sigungu"]).copy()

    # 시군별 상위 10% (최소 1개 보장)
    def mark_hotspot(g: pd.DataFrame) -> pd.DataFrame:
        g = g.sort_values("cnt_store", ascending=False).copy()
        k = max(1, int(np.ceil(len(g) * TOP_PCT)))
        g["hotspot"] = False
        g.iloc[:k, g.columns.get_loc("hotspot")] = True
        return g

    # pandas FutureWarning 회피: group_keys=False 유지 + apply 결과 사용
    base = base.groupby("sigungu", group_keys=False).apply(mark_hotspot)

    hs = base[base["hotspot"] == True].copy()

    # 시군별 z-score로 need_score
    hs["z_112"] = hs.groupby("sigungu")["cnt_112"].transform(zscore)
    hs["z_5crime"] = hs.groupby("sigungu")["cnt_5crime"].transform(zscore)
    hs["z_cctv"] = hs.groupby("sigungu")["cnt_cctv"].transform(zscore)
    hs["z_patrol"] = hs.groupby("sigungu")["cnt_patrol"].transform(zscore)

    hs["need_score"] = hs["z_112"] + hs["z_5crime"] - 0.5 * hs["z_cctv"] - 0.5 * hs["z_patrol"]

    hs["rank_in_sigungu"] = hs.groupby("sigungu")["need_score"].rank(ascending=False, method="dense").astype(int)

    hs = hs.sort_values(["sigungu", "need_score"], ascending=[True, False])
    hs.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    print("✅ 생성 완료:", OUT_PATH)
    print("핫스팟 격자 수:", len(hs))
    print("시군 수:", int(hs["sigungu"].nunique(dropna=True)))


if __name__ == "__main__":
    main()
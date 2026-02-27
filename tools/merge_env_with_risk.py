
import argparse
import os
import pandas as pd

def norm_gid(s):
    if pd.isna(s):
        return None
    return str(s).strip().replace(" ", "")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--env_patrol_csv", required=True, help="순찰 반영된 env 파일")
    p.add_argument("--risk_csv", required=True, help="grid_id별 위험도 파일(grid_risk_import.csv)")
    p.add_argument("--out_csv", required=True, help="최종 출력 파일")
    args = p.parse_args()

    env = pd.read_csv(args.env_patrol_csv, dtype={"grid_id": "string"})
    risk = pd.read_csv(args.risk_csv, dtype={"grid_id": "string"})

    # 컬럼 체크
    need_env = {"grid_id", "cnt_112", "cnt_cctv", "cnt_patrol", "env_score"}
    if not need_env.issubset(set(env.columns)):
        raise ValueError(f"env_patrol_csv 컬럼 부족: 필요={need_env}, 현재={set(env.columns)}")

    if "grid_id" not in risk.columns or "risk" not in risk.columns:
        raise ValueError("risk_csv에는 최소 grid_id, risk 컬럼이 있어야 합니다.")

    # grid_id 정규화
    env["grid_id"] = env["grid_id"].map(norm_gid)
    risk["grid_id"] = risk["grid_id"].map(norm_gid)

    # risk 값 정리 (1~9, 1이 위험)
    risk["risk"] = pd.to_numeric(risk["risk"], errors="coerce").astype("Int64")

    # merge (station은 선택)
    cols = ["grid_id", "risk"]
    if "station" in risk.columns:
        cols.append("station")

    merged = env.merge(risk[cols], on="grid_id", how="left", validate="one_to_one")

    # 누락 체크
    miss = int(merged["risk"].isna().sum())
    if miss > 0:
        print(f"[경고] 위험도 매칭 누락 grid_id: {miss}개 (risk가 비어있음)")
        # 필요하면 여기서 누락 grid_id를 파일로 뽑을 수도 있음

    # (선택) 나중 계산용 risk_score까지 미리 만들어두기
    # risk=1(위험) → risk_score=9(큰 점수)
    merged["risk_score"] = (10 - merged["risk"]).astype("Int64")

    os.makedirs(os.path.dirname(args.out_csv) or ".", exist_ok=True)
    merged.to_csv(args.out_csv, index=False, encoding="utf-8-sig")
    print("완료:", args.out_csv)

if __name__ == "__main__":
    main()

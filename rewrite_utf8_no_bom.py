import pandas as pd

INP = r"C:\Users\82104\Desktop\jeonnam_cpo\grid_risk_import.csv"
OUT = r"C:\Users\82104\Desktop\jeonnam_cpo\grid_risk_import_nobom.csv"

df = pd.read_csv(
    INP,
    dtype={"station": "string", "grid_id": "string"},
    low_memory=False
)

# ✅ BOM 없이 UTF-8로 저장
df.to_csv(OUT, index=False, encoding="utf-8")

print("✅ 저장 완료:", OUT)
print("행 수:", len(df))
print(df.head(5))

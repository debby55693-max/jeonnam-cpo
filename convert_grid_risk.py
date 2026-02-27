import os
import pandas as pd

# =========================
# 파일 경로
# =========================
INPUT_BIG_CSV = r"C:\Users\82104\Desktop\jeonnam_cpo\data\격자별범죄위험도예측결과.csv"
OUTPUT_CSV = r"C:\Users\82104\Desktop\jeonnam_cpo\grid_risk_import.csv"

# =========================
# 위험도로 사용할 컬럼
# =========================
RISK_COL = "dd_all_crim_dgrsd_val"

# =========================
# 옵션
# =========================
FILTER_NPA = "전남청"     # 전남청만 (싫으면 None)
LATEST_ONLY = True       # 최신 날짜만
CHUNKSIZE = 200_000      # 메모리 부족하면 100_000


def read_csv_chunks(path, usecols, chunksize, encodings):
    """
    여러 인코딩을 순서대로 시도해서 성공하는 걸로 읽는다.
    """
    last_err = None
    for enc in encodings:
        try:
            it = pd.read_csv(
                path,
                usecols=usecols,
                chunksize=chunksize,
                encoding=enc,
                low_memory=False,
            )
            # 제너레이터가 진짜로 읽히는지 1chunk 프리뷰로 확인
            first = next(it)
            # 성공했으면 다시 이터레이터를 새로 만들어 반환(처음 chunk 포함)
            it2 = pd.read_csv(
                path,
                usecols=usecols,
                chunksize=chunksize,
                encoding=enc,
                low_memory=False,
            )
            print(f"✅ 사용 인코딩 확정: {enc}")
            return it2, enc
        except Exception as e:
            last_err = e
            print(f"⚠️ 인코딩 실패: {enc} -> {type(e).__name__}: {e}")
            continue
    raise last_err


def main():
    if not os.path.exists(INPUT_BIG_CSV):
        raise FileNotFoundError(f"❌ 파일 없음: {INPUT_BIG_CSV}")

    # ✅ 가장 흔한 조합부터 시도
    encodings_to_try = [
        "utf-8-sig",
        "utf-8",
        "euc-kr",
        "cp949",
        "latin1",  # 최후의 보루(깨져도 에러 없이 읽힘) - 보통 여기까지 안 감
    ]

    # -------------------------
    # 1) 최신 날짜 찾기
    # -------------------------
    latest_ymd = None
    if LATEST_ONLY:
        it, enc_used = read_csv_chunks(
            INPUT_BIG_CSV,
            usecols=["prdt_ymd"],
            chunksize=CHUNKSIZE,
            encodings=encodings_to_try,
        )

        latest_ymd = 0
        for chunk in it:
            s = pd.to_numeric(chunk["prdt_ymd"], errors="coerce")
            if s.notna().any():
                m = int(s.max())
                if m > latest_ymd:
                    latest_ymd = m
        print("✅ 최신 prdt_ymd =", latest_ymd)

    # -------------------------
    # 2) 본 처리
    # -------------------------
    usecols = ["npa_nm", "polstn_nm", "grid_id", "prdt_ymd", RISK_COL]

    it2, enc_used2 = read_csv_chunks(
        INPUT_BIG_CSV,
        usecols=usecols,
        chunksize=CHUNKSIZE,
        encodings=encodings_to_try,
    )

    out_parts = []

    for chunk in it2:
        # 전남청 필터
        if FILTER_NPA:
            chunk = chunk[chunk["npa_nm"] == FILTER_NPA]

        # 최신 날짜만
        if LATEST_ONLY and latest_ymd:
            chunk["prdt_ymd"] = pd.to_numeric(chunk["prdt_ymd"], errors="coerce")
            chunk = chunk[chunk["prdt_ymd"] == latest_ymd]

        # 정리
        chunk["station"] = chunk["polstn_nm"].astype(str).str.strip()
        chunk["grid_id"] = chunk["grid_id"].astype(str).str.strip()
        chunk["risk"] = pd.to_numeric(chunk[RISK_COL], errors="coerce")

        chunk = chunk.dropna(subset=["station", "grid_id", "risk"])
        chunk = chunk[(chunk["station"] != "") & (chunk["grid_id"] != "")]

        g = chunk.groupby(["station", "grid_id"], as_index=False)["risk"].max()
        out_parts.append(g)

    if not out_parts:
        print("❌ 결과 없음 (필터 조건 확인)")
        return

    out = pd.concat(out_parts, ignore_index=True)
    out = out.groupby(["station", "grid_id"], as_index=False)["risk"].max()

    out.to_csv(OUTPUT_CSV, index=False, encoding="utf-8-sig")

    print("🎉 완료!")
    print("파일:", OUTPUT_CSV)
    print("행 수:", len(out))
    print(out.head(10))


if __name__ == "__main__":
    main()
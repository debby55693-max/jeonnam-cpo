# fetch_jeonnam_stores.py
import time
import math
import requests
import pandas as pd

# ✅ 여기에 네 ServiceKey(인증키 URL Encoded) 넣기
SERVICE_KEY = "95d2e6b73bd671d10740cdb3a3f698d80e9502067bc7b48ce2001acdb1a966d4"

# ⚠️ 보통 이 API 베이스 URL이 아래 형태인데,
# 네 “미리보기” 주소창에 보이는 도메인이 다르면 그것으로 바꿔줘.
BASE_URL = "https://apis.data.go.kr/B553077/api/open/sdsc2/storeListInDong"

def fetch_page(page_no: int, num_rows: int = 1000):
    params = {
        "ServiceKey": SERVICE_KEY,
        "pageNo": page_no,
        "numOfRows": num_rows,
        "divId": "ctprvnCd",  # ✅ 시도 단위
        "key": "46",          # ✅ 전남
        "type": "json",       # ✅ json 권장
    }
    r = requests.get(BASE_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()

def main():
    num_rows = 1000
    first = fetch_page(1, num_rows=num_rows)

    # 응답 구조가 환경에 따라 약간 다를 수 있어서 방어적으로 꺼냄
    body = first.get("body") or first.get("response", {}).get("body") or {}
    total = int(body.get("totalCount") or body.get("totalCount", 0) or 0)
    if total == 0:
        raise RuntimeError(f"totalCount가 0이에요. BASE_URL 또는 ServiceKey/파라미터를 확인해줘. body={body}")

    total_pages = math.ceil(total / num_rows)
    print(f"전남 totalCount={total:,} / pages={total_pages:,} (rows={num_rows})")

    rows = []

    for page in range(1, total_pages + 1):
        data = fetch_page(page, num_rows=num_rows)
        body = data.get("body") or data.get("response", {}).get("body") or {}
        items = body.get("items") or {}
        item_list = items.get("item") if isinstance(items, dict) else items

        if item_list is None:
            item_list = []
        if isinstance(item_list, dict):
            item_list = [item_list]

        rows.extend(item_list)

        if page % 10 == 0:
            print(f"{page}/{total_pages} 페이지 수집… 누적 {len(rows):,}건")

        # 과호출 방지(필요시 조절)
        time.sleep(0.15)

    df = pd.DataFrame(rows)

    # lon/lat 컬럼 확인
    if "lon" not in df.columns or "lat" not in df.columns:
        print("컬럼 목록:", df.columns.tolist())
        raise RuntimeError("lon/lat 컬럼이 안 보입니다. type=json 응답 구조를 확인해야 해요.")

    df.to_csv("jeonnam_stores.csv", index=False, encoding="utf-8-sig")
    print("✅ 저장 완료: jeonnam_stores.csv")

if __name__ == "__main__":
    main()

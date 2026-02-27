import streamlit as st
import pandas as pd
from datetime import datetime

# =====================================================
# 전남 22개 경찰서 (관리자 기준 고정)
# =====================================================
JEONNAM_POLICE_STATIONS = [
    "목포경찰서",
    "여수경찰서",
    "순천경찰서",
    "나주경찰서",
    "광양경찰서",
    "담양경찰서",
    "곡성경찰서",
    "구례경찰서",
    "고흥경찰서",
    "보성경찰서",
    "화순경찰서",
    "장흥경찰서",
    "강진경찰서",
    "해남경찰서",
    "영암경찰서",
    "무안경찰서",
    "함평경찰서",
    "영광경찰서",
    "장성경찰서",
    "완도경찰서",
    "진도경찰서",
    "신안경찰서",
]


# -----------------------------
# 안전 변환 함수
# -----------------------------
def safe_int(v, default=0):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            return default
        return int(v)
    except:
        return default


def safe_str(v, default=""):
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
            return default
        return str(v)
    except:
        return default


def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")


# =====================================================
# 관리자(총괄) 페이지
# =====================================================
def admin_page(supabase, my_station="전남청", role="admin"):
    st.title("🛠️ 관리자(총괄) 모드")
    st.caption(f"권한: {role} / 기준 관서: {my_station}")

    # ✅ 즉시 반영을 체감하게 하는 강제 새로고침 버튼(로그인 유지)
    col_r1, col_r2 = st.columns([1, 4])
    with col_r1:
        if st.button("🔄 최신 데이터 불러오기", use_container_width=True):
            st.rerun()
    with col_r2:
        st.caption("※ 점포 등록/수정 후 버튼을 누르면 즉시 최신 점수/순위가 반영된 목록을 다시 불러옵니다.")

    st.divider()

    # -----------------------------
    # 1) 조회 조건
    # -----------------------------
    st.subheader("🔎 조회 조건")

    col1, col2 = st.columns([1, 2])

    with col1:
        station_filter = st.selectbox(
            "경찰서 필터",
            ["전체"] + JEONNAM_POLICE_STATIONS,
            index=0,
        )

    with col2:
        keyword = st.text_input(
            "검색 (점포명 / 주소)",
            placeholder="예) 무안읍, 남악, OO마트",
        ).strip()

    st.divider()

    # -----------------------------
    # 2) 데이터 조회
    # ✅ 핵심: shops가 아니라 v_shops_priority_ranked를 조회해야
    #        env_grid_result 조인된 점수(env_score/cnt_*)가 즉시 반영됨
    # -----------------------------
    q = supabase.table("v_shops_priority_ranked").select("*")

    if station_filter != "전체":
        q = q.eq("station", station_filter)

    # 우선순위: priority_rank(낮을수록 우선) → updated_at 최신
    # supabase python client에서 여러 order가 가능한 경우가 많음
    # (안되면 fallback 정렬은 pandas에서 처리)
    try:
        q = q.order("priority_rank", desc=False).order("updated_at", desc=True).limit(2000)
        res = q.execute()
        data = res.data or []
    except Exception:
        # fallback: 일단 최신순으로 받고, 파이썬에서 정렬
        res = (
            supabase.table("v_shops_priority_ranked")
            .select("*")
            .eq("station", station_filter) if station_filter != "전체" else
            supabase.table("v_shops_priority_ranked").select("*")
        )
        res = res.execute()
        data = res.data or []

    df = pd.DataFrame(data)

    if df.empty:
        st.info("조건에 해당하는 데이터가 없습니다.")
        return

    # -----------------------------
    # 3) 검색 필터
    # -----------------------------
    if keyword:
        df["__shop"] = df.get("shop_name", "").fillna("").astype(str)
        df["__addr"] = df.get("address", "").fillna("").astype(str)
        df = df[
            df["__shop"].str.contains(keyword, case=False, na=False)
            | df["__addr"].str.contains(keyword, case=False, na=False)
        ].copy()

    if df.empty:
        st.info("검색 결과가 없습니다.")
        return

    # -----------------------------
    # 4) 정렬 보장 (priority_rank 우선)
    # -----------------------------
    if "priority_rank" in df.columns:
        df["priority_rank"] = df["priority_rank"].apply(lambda x: safe_int(x, 999999))
        df = df.sort_values(["priority_rank", "updated_at"], ascending=[True, False])
    else:
        # priority_rank가 없으면 기존처럼 priority_score 기반
        if "priority_score" in df.columns:
            df["priority_score"] = df["priority_score"].apply(lambda x: safe_int(x, 0))
            df = df.sort_values("priority_score", ascending=False)
        else:
            df = df.sort_values("updated_at", ascending=False)

    # -----------------------------
    # 5) TOP 10
    # -----------------------------
    st.subheader("🏆 우선순위 TOP 10 (현재 조건 기준)")

    show_cols = [
        "priority_rank",
        "station",
        "shop_name",
        "address",
        "grid_id",
        "env_score",
        "cnt_112",
        "cnt_cctv",
        "cnt_patrol",
        "subjective_score",
        "cpo_score",
        "updated_at",
    ]

    for c in show_cols:
        if c not in df.columns:
            df[c] = None

    df_top = df.head(10).copy()
    df_top["shop_name"] = df_top["shop_name"].fillna("(무명)")
    st.dataframe(df_top[show_cols], use_container_width=True, hide_index=True)

    st.divider()

    # -----------------------------
    # 6) CSV 다운로드
    # -----------------------------
    st.download_button(
        "⬇️ CSV 다운로드 (현재 조회 결과)",
        data=df_to_csv_bytes(df),
        file_name=f"admin_shops_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

    st.divider()

    # -----------------------------
    # 7) 전체 목록
    # -----------------------------
    st.subheader("📋 설문 목록")
    st.dataframe(df, use_container_width=True)

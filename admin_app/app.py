# admin_app/app.py
import streamlit as st

from core.auth import login_ui
from core.supabase_client import get_authed_client
from pages.cpo_view import cpo_page

# 전남 22개 경찰서 (필터용)
JEONNAM_POLICE_STATIONS = [
    "전체",
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]

# streamlit_app.py에서 set_page_config를 이미 호출했으면 여기서 에러가 날 수 있어 방지
try:
    st.set_page_config(
        page_title="소상공인 방범물품 지원",
        layout="wide",
    )
except Exception:
    pass


def main():
    # =============================
    # 1. 로그인
    # =============================
    session = login_ui()
    if not session:
        st.stop()

    access_token = session["access_token"]
    user = session["user"]

    # refresh_token까지 전달 (배포/세션 안정화)
    refresh_token = st.session_state.get("refresh_token")
    supabase = get_authed_client(access_token, refresh_token)

    role = user.get("role")
    my_station = user.get("station")

    # =============================
    # 2. Admin만 경찰서 필터
    # =============================
    if role == "admin":
        st.sidebar.markdown("---")
        st.sidebar.subheader("🏢 경찰서 선택")

        selected_station = st.sidebar.selectbox(
            "조회할 경찰서",
            JEONNAM_POLICE_STATIONS,
            index=0,  # 기본: 전체
            key="admin_station_filter",
        )

        # 전체 선택 시 → None 처리
        station = None if selected_station == "전체" else selected_station
    else:
        # CPO는 무조건 본인 관서
        station = my_station

    # =============================
    # 3. 공통 CPO 화면 호출
    # =============================
    cpo_page(
        supabase=supabase,
        station=station,
        role=role,
    )


if __name__ == "__main__":
    main()
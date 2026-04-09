import streamlit as st

from core.supabase_client import get_supabase
from pages.cpo_view import cpo_page


JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]


def show():
    role = st.session_state.get("role", "")
    station = st.session_state.get("station", "")

    if not st.session_state.get("token"):
        st.warning("먼저 로그인해주세요.")
        st.stop()

    if role != "admin":
        st.error("이 페이지는 관리자만 사용할 수 있습니다.")
        st.stop()

    supabase = get_supabase()
    cpo_page(
        supabase=supabase,
        role="admin",
        station=station,
        station_options=JEONNAM_POLICE_STATIONS,
    )


show()
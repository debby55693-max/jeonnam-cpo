import streamlit as st

from core.auth import login_ui
from core.supabase_client import get_supabase
from pages.cpo_view import cpo_page


st.set_page_config(
    page_title="소상공인 시스템",
    page_icon="🛡️",
    layout="wide",
)


JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]


def main():
    auth_info = login_ui()
    if not auth_info:
        st.title("소상공인 시스템")
        st.info("왼쪽 사이드바에서 로그인해주세요.")
        return

    role = st.session_state.get("role", "")
    station = st.session_state.get("station", "")

    if role not in ["admin", "cpo"]:
        st.error("권한 정보가 올바르지 않습니다. profiles.role 값을 확인하세요.")
        return

    if role == "cpo" and station not in JEONNAM_POLICE_STATIONS:
        st.error("CPO 계정의 관할 경찰서 정보가 올바르지 않습니다.")
        return

    supabase = get_supabase()

    # admin도 동일한 관리화면을 사용하되,
    # admin은 전체/관서별 조회가 가능하고
    # cpo는 본인 관서만 보게 한다.
    cpo_page(
        supabase=supabase,
        role=role,
        station=station,
        station_options=JEONNAM_POLICE_STATIONS,
    )


if __name__ == "__main__":
    main()
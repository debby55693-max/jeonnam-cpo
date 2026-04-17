import streamlit as st

from core.auth import login_ui
from core.supabase_client import get_authed_client
from pages.cpo_view import cpo_page


st.set_page_config(
    page_title="소상공인 안전물품 지원 시스템",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]


def inject_base_css():
    logged_in = bool(st.session_state.get("token"))

    common_css = """
    <style>
    .block-container {
        padding-top: 1.2rem !important;
        padding-bottom: 2rem !important;
    }

    [data-testid="stSidebarNav"] {
        display: none !important;
    }

    section[data-testid="stSidebar"] .css-1d391kg,
    section[data-testid="stSidebar"] .css-1544g2n,
    section[data-testid="stSidebar"] .css-1lcbmhc {
        padding-top: 1rem !important;
    }
    </style>
    """
    st.markdown(common_css, unsafe_allow_html=True)

    if not logged_in:
        logged_out_css = """
        <style>
        section[data-testid="stSidebar"] {
            display: none !important;
        }

        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }

        .block-container {
            padding-left: 2rem !important;
            padding-right: 2rem !important;
        }
        </style>
        """
        st.markdown(logged_out_css, unsafe_allow_html=True)


def main():
    inject_base_css()

    auth_info = login_ui()
    if not auth_info:
        return

    role = st.session_state.get("role", "")
    station = st.session_state.get("station", "")

    if role not in ["admin", "cpo"]:
        st.error("권한 정보가 올바르지 않습니다. profiles.role 값을 확인하세요.")
        return

    if role == "cpo" and station not in JEONNAM_POLICE_STATIONS:
        st.error("CPO 계정의 관할 경찰서 정보가 올바르지 않습니다.")
        return

    access_token = st.session_state.get("token")
    refresh_token = st.session_state.get("refresh_token")

    if not access_token:
        st.error("로그인 토큰이 없습니다. 다시 로그인해주세요.")
        return

    supabase = get_authed_client(
        access_token=access_token,
        refresh_token=refresh_token,
    )

    cpo_page(
        supabase=supabase,
        role=role,
        station=station,
        station_options=JEONNAM_POLICE_STATIONS,
    )


if __name__ == "__main__":
    main()
import streamlit as st

from core.auth import login_ui
from core.supabase_client import get_authed_client
from pages.cpo_view import cpo_page

JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]

try:
    st.set_page_config(page_title="소상공인 시스템", layout="wide")
except Exception:
    pass


def main():
    session = login_ui()
    if not session:
        st.stop()

    access_token = session["access_token"]
    user = session["user"]
    refresh_token = st.session_state.get("refresh_token")
    supabase = get_authed_client(access_token, refresh_token)

    role = user.get("role") or "cpo"
    my_station = user.get("station") or ""

    station_filter = my_station
    if role == "admin":
        with st.sidebar:
            st.markdown("---")
            station_options = ["전체"] + JEONNAM_POLICE_STATIONS
            station_filter = st.selectbox(
                "관할 경찰서",
                station_options,
                index=0,
                key="admin_station_filter",
            )

    cpo_page(
        supabase=supabase,
        role=role,
        station=station_filter,
        station_options=JEONNAM_POLICE_STATIONS,
    )


if __name__ == "__main__":
    main()
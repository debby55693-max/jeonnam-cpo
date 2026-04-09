import streamlit as st
from core.supabase_client import get_supabase


JEONNAM_POLICE_STATIONS = [
    "목포경찰서", "여수경찰서", "순천경찰서", "나주경찰서", "광양경찰서",
    "고흥경찰서", "해남경찰서", "무안경찰서", "장흥경찰서", "보성경찰서",
    "영광경찰서", "화순경찰서", "함평경찰서", "영암경찰서", "장성경찰서",
    "강진경찰서", "담양경찰서", "곡성경찰서", "완도경찰서", "진도경찰서",
    "구례경찰서", "신안경찰서",
]


def _apply_auth_to_postgrest(supabase, access_token: str):
    if not access_token:
        return
    try:
        supabase.postgrest.auth(token=access_token)
    except TypeError:
        supabase.postgrest.auth(access_token)


def _load_station_label(supabase, station_id):
    if not station_id:
        return ""
    try:
        resp = (
            supabase.table("stations")
            .select("id, station_name, station_label")
            .eq("id", station_id)
            .limit(1)
            .execute()
        )
        row = resp.data[0] if resp.data else None
        if not row:
            return ""
        return (row.get("station_label") or "").strip()
    except Exception:
        return ""


def _load_profile_by_uid(supabase, uid: str):
    if not uid:
        return None

    try:
        resp = (
            supabase.table("profiles")
            .select("id, email, full_name, role, station_id, is_active")
            .eq("id", uid)
            .limit(1)
            .execute()
        )
        profile = resp.data[0] if resp.data else None
        if not profile:
            return None

        station_id = profile.get("station_id")
        profile["station"] = _load_station_label(supabase, station_id)
        return profile
    except Exception:
        return None


def _set_profile_session(profile: dict):
    st.session_state["role"] = profile.get("role", "cpo")
    st.session_state["station_id"] = profile.get("station_id")
    st.session_state["station"] = profile.get("station") or ""
    st.session_state["full_name"] = profile.get("full_name") or ""


def _ensure_profile_in_session(supabase):
    token = st.session_state.get("token")
    uid = st.session_state.get("uid")

    if not token:
        return

    _apply_auth_to_postgrest(supabase, token)

    need_role = st.session_state.get("role") in [None, "", "None"]
    need_station = st.session_state.get("station") in [None, "", "None"]

    if not (need_role or need_station):
        return

    if not uid:
        try:
            user_resp = supabase.auth.get_user(token)
            user_obj = getattr(user_resp, "user", None)
            if user_obj:
                uid = getattr(user_obj, "id", None)
                if uid:
                    st.session_state["uid"] = uid
                email = getattr(user_obj, "email", None)
                if email and not st.session_state.get("email"):
                    st.session_state["email"] = email
        except Exception:
            uid = None

    profile = _load_profile_by_uid(supabase, uid)
    if not profile:
        return

    if profile.get("is_active") is False:
        return

    _set_profile_session(profile)


def login_ui():
    supabase = get_supabase()

    if st.session_state.get("token"):
        _apply_auth_to_postgrest(supabase, st.session_state["token"])
        _ensure_profile_in_session(supabase)

    with st.sidebar:
        st.subheader("🔐 로그인")

        if st.session_state.get("token"):
            st.success(f"로그인됨: {st.session_state.get('email')}")
            st.write(f"관서: {st.session_state.get('station') or '-'}")
            st.write(f"권한: {st.session_state.get('role') or '-'}")

            st.markdown("---")
            if st.button("🔄 화면 새로고침(로그인 유지)"):
                st.rerun()

            if st.button("🚪 로그아웃"):
                st.session_state.clear()
                st.rerun()

            return {
                "access_token": st.session_state.get("token"),
                "user": {
                    "id": st.session_state.get("uid"),
                    "email": st.session_state.get("email"),
                    "role": st.session_state.get("role"),
                    "station": st.session_state.get("station"),
                    "station_id": st.session_state.get("station_id"),
                    "full_name": st.session_state.get("full_name"),
                },
            }

        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")

        if st.button("로그인"):
            try:
                auth = supabase.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )

                user = auth.user
                session = auth.session

                st.session_state["token"] = session.access_token
                st.session_state["uid"] = user.id
                st.session_state["email"] = user.email
                st.session_state["refresh_token"] = getattr(session, "refresh_token", None)

                _apply_auth_to_postgrest(supabase, session.access_token)

                profile = _load_profile_by_uid(supabase, user.id)
                if not profile:
                    raise Exception("profiles 테이블에 사용자 프로필이 없습니다. Auth 계정 생성 후 profiles 매핑을 확인하세요.")

                if profile.get("is_active") is False:
                    raise Exception("비활성화된 계정입니다. 관리자에게 문의하세요.")

                role = profile.get("role", "cpo")
                if role not in ["admin", "cpo"]:
                    raise Exception("profiles.role 값이 올바르지 않습니다. admin 또는 cpo로 맞춰주세요.")

                station = profile.get("station") or ""
                if role == "cpo" and station not in JEONNAM_POLICE_STATIONS:
                    raise Exception("CPO 계정은 profiles.station_id가 올바른 경찰서로 매핑되어 있어야 합니다.")

                _set_profile_session(profile)
                st.success("로그인 성공")
                st.rerun()
            except Exception as e:
                st.error(f"로그인 실패: {e}")

        return None
# admin_app/core/auth.py
import streamlit as st
from core.supabase_client import get_supabase


def _apply_auth_to_postgrest(supabase, access_token: str):
    """
    supabase-py에서 로그인 후에도 PostgREST 쿼리에 JWT가 안 붙는 경우가 있어서
    RLS가 걸린 테이블 조회 시 0 rows가 나올 수 있음.
    access_token을 postgrest에 확실히 주입한다.
    """
    if not access_token:
        return
    try:
        supabase.postgrest.auth(token=access_token)  # 일부 버전
    except TypeError:
        supabase.postgrest.auth(access_token)        # 일부 버전


def _load_profile_by_uid(supabase, uid: str):
    """
    app_user_profiles에서 role / station / is_enabled 조회
    """
    if not uid:
        return None

    try:
        resp = (
            supabase
            .table("app_user_profiles")
            .select("role, station, is_enabled")
            .eq("user_id", uid)
            .limit(1)
            .execute()
        )
        return resp.data[0] if resp.data else None
    except Exception:
        return None


def _ensure_profile_in_session(supabase):
    """
    이미 로그인된 세션인데 role/station이 비어 있는 경우,
    app_user_profiles를 다시 읽어서 session_state를 보정한다.
    """
    token = st.session_state.get("token")
    uid = st.session_state.get("uid")

    if not token:
        return

    _apply_auth_to_postgrest(supabase, token)

    need_role = st.session_state.get("role") in [None, "", "None"]
    need_station = st.session_state.get("station") in [None, "", "None"]

    if not (need_role or need_station):
        return

    # uid가 없으면 auth 현재 사용자에서 다시 시도
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

    if profile.get("is_enabled") is False:
        return

    st.session_state["role"] = profile.get("role", "cpo")
    st.session_state["station"] = profile.get("station")


def login_ui():
    supabase = get_supabase()

    # 이미 로그인된 세션이면 토큰 재주입 + role/station 보정
    if "token" in st.session_state and st.session_state.get("token"):
        _apply_auth_to_postgrest(supabase, st.session_state["token"])
        _ensure_profile_in_session(supabase)

    with st.sidebar:
        st.subheader("🔐 로그인")

        # =============================
        # 이미 로그인된 경우
        # =============================
        if "token" in st.session_state and st.session_state.get("token"):
            st.success(f"로그인됨: {st.session_state.get('email')}")
            st.write(f"관서: {st.session_state.get('station')}")
            st.write(f"권한: {st.session_state.get('role')}")

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
                },
            }

        # =============================
        # 로그인 폼
        # =============================
        email = st.text_input("이메일")
        password = st.text_input("비밀번호", type="password")

        if st.button("로그인"):
            try:
                auth = supabase.auth.sign_in_with_password(
                    {"email": email, "password": password}
                )

                user = auth.user
                session = auth.session

                # 토큰 먼저 저장 + postgrest에 주입
                st.session_state["token"] = session.access_token
                st.session_state["uid"] = user.id
                st.session_state["email"] = user.email
                st.session_state["refresh_token"] = getattr(session, "refresh_token", None)

                _apply_auth_to_postgrest(supabase, session.access_token)

                resp = (
                    supabase
                    .table("app_user_profiles")
                    .select("role, station, is_enabled")
                    .eq("user_id", user.id)
                    .limit(1)
                    .execute()
                )

                profile = resp.data[0] if resp.data else None
                if not profile:
                    raise Exception("프로필 매핑이 없습니다(app_user_profiles 0 rows). 관리자에게 매핑 등록 필요")

                if profile.get("is_enabled") is False:
                    raise Exception("비활성화된 계정입니다(관리자에게 문의).")

                st.session_state["role"] = profile.get("role", "cpo")
                st.session_state["station"] = profile.get("station")

                st.success("로그인 성공")
                st.rerun()

            except Exception as e:
                st.error(f"로그인 실패: {e}")

        return None
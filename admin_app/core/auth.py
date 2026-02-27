# admin_app/core/auth.py
import streamlit as st
from core.supabase_client import get_supabase  # ✅ 이것만 import


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


def login_ui():
    supabase = get_supabase()

    # ✅ 이미 로그인된 토큰이 있으면, supabase postgrest에 JWT 다시 주입
    if "token" in st.session_state and st.session_state.get("token"):
        _apply_auth_to_postgrest(supabase, st.session_state["token"])

    with st.sidebar:
        st.subheader("🔐 로그인")

        # =============================
        # 이미 로그인된 경우
        # =============================
        if "token" in st.session_state:
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

                # ✅ 토큰 먼저 저장 + postgrest에 주입 (RLS/조회 안정화)
                st.session_state["token"] = session.access_token
                st.session_state["uid"] = user.id
                st.session_state["email"] = user.email
                st.session_state["refresh_token"] = getattr(session, "refresh_token", None)

                _apply_auth_to_postgrest(supabase, session.access_token)

                # ✅ 우리가 만든 매핑 테이블로 조회 (0건이어도 에러 안 나게)
                resp = (
                    supabase
                    .table("app_user_profiles")  # ✅ 여기!
                    .select("role, station, is_enabled")
                    .eq("user_id", user.id)      # ✅ 여기!
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
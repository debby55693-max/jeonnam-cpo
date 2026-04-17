from pathlib import Path
import time

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
        return (row.get("station_label") or row.get("station_name") or "").strip()
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


def _render_logged_in_sidebar():
    with st.sidebar:
        st.subheader("🔐 로그인")
        st.success(f"로그인됨: {st.session_state.get('email')}")
        st.write(f"관서: {st.session_state.get('station') or '-'}")
        st.write(f"권한: {st.session_state.get('role') or '-'}")

        st.markdown("---")

        if st.button("🔄 화면 새로고침(로그인 유지)", use_container_width=True):
            st.rerun()

        if st.button("🚪 로그아웃", use_container_width=True):
            st.session_state.clear()
            st.rerun()


def _find_login_logo_path() -> Path | None:
    root = Path(__file__).resolve().parents[2]

    candidates = [
        root / "assets" / "login_slogan.png",
        root / "assets" / "login_slogan.jpg",
        root / "assets" / "login_slogan.jpeg",
        root / "assets" / "login_slogan.png",
        root / "admin_app" / "assets" / "login_slogan.png",
        root / "admin_app" / "assets" / "login_slogan.png",
    ]

    for path in candidates:
        if path.exists():
            return path

    return None


def _render_login_main(error_message: str = ""):
    st.markdown(
        """
        <style>
        .login-title {
            font-size: 2.4rem;
            font-weight: 800;
            margin: 0.4rem 0 0.25rem 0;
            text-align: center;
            color: #1f2a44;
        }
        .login-desc {
            color: #666666;
            margin-bottom: 1rem;
            text-align: center;
            font-size: 1rem;
        }
        .login-card-box {
            border: 1px solid rgba(49, 51, 63, 0.15);
            border-radius: 22px;
            padding: 1.45rem 1.35rem 1.2rem 1.35rem;
            background: #ffffff;
            box-shadow: 0 12px 30px rgba(0, 0, 0, 0.06);
        }
        .login-top-gap {
            height: 0.2rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<div class="login-top-gap"></div>', unsafe_allow_html=True)

    left, center, right = st.columns([1.15, 1.7, 1.15])

    with center:
        logo_path = _find_login_logo_path()
        if logo_path:
            st.image(str(logo_path), use_container_width=True)

        with st.container(border=False):
            st.markdown('<div class="login-title">소상공인 시스템</div>', unsafe_allow_html=True)
            st.markdown(
                '<div class="login-desc">관리자 / CPO 계정으로 로그인해주세요.</div>',
                unsafe_allow_html=True,
            )

            if error_message:
                st.error(error_message)

            st.markdown('<div class="login-card-box">', unsafe_allow_html=True)
            with st.form("login_form_main", clear_on_submit=False):
                email = st.text_input("이메일", key="login_email_main")
                password = st.text_input("비밀번호", type="password", key="login_password_main")
                submit = st.form_submit_button("로그인", use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

    return email, password, submit


def _friendly_login_error(exc: Exception) -> str:
    raw = str(exc)
    lowered = raw.lower()

    if "502" in lowered or "bad gateway" in lowered:
        return (
            "로그인 실패: Supabase 인증 서버 응답이 잠시 불안정합니다. "
            "10~30초 뒤 다시 시도해주세요. 계속 반복되면 Streamlit Secrets의 "
            "SUPABASE_URL / SUPABASE_ANON_KEY를 확인해주세요."
        )

    if "504" in lowered or "timeout" in lowered:
        return "로그인 실패: 인증 응답이 지연되었습니다. 잠시 후 다시 시도해주세요."

    if "invalid login credentials" in lowered:
        return "로그인 실패: 이메일 또는 비밀번호가 맞지 않습니다."

    if "email not confirmed" in lowered:
        return "로그인 실패: 이메일 인증이 완료되지 않은 계정입니다."

    return f"로그인 실패: {raw}"


def _sign_in_with_retry(supabase, email: str, password: str, retries: int = 3, wait_sec: float = 1.2):
    last_error = None

    for attempt in range(retries):
        try:
            return supabase.auth.sign_in_with_password(
                {"email": email, "password": password}
            )
        except Exception as exc:
            last_error = exc
            lowered = str(exc).lower()
            is_retryable = (
                "502" in lowered
                or "bad gateway" in lowered
                or "504" in lowered
                or "timeout" in lowered
            )

            if attempt < retries - 1 and is_retryable:
                time.sleep(wait_sec)
                continue

            raise last_error


def login_ui():
    supabase = get_supabase()

    if st.session_state.get("token"):
        _apply_auth_to_postgrest(supabase, st.session_state["token"])
        _ensure_profile_in_session(supabase)
        _render_logged_in_sidebar()
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

    login_error = st.session_state.pop("login_error_message", "")
    email, password, submit = _render_login_main(login_error)

    if submit:
        if not email or not password:
            st.session_state["login_error_message"] = "로그인 실패: 이메일과 비밀번호를 모두 입력해주세요."
            st.rerun()

        try:
            auth = _sign_in_with_retry(supabase, email, password)

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
            st.session_state.pop("login_error_message", None)
            st.rerun()

        except Exception as e:
            st.session_state["login_error_message"] = _friendly_login_error(e)
            st.rerun()

    return None
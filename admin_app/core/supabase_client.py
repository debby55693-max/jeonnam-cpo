import streamlit as st
from supabase import create_client, Client


def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    anon_key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, anon_key)


def _apply_auth(client: Client, access_token: str):
    """RLS용 JWT를 PostgREST에 확실히 주입."""
    if not access_token:
        return
    try:
        client.postgrest.auth(token=access_token)  # 일부 버전
    except TypeError:
        client.postgrest.auth(access_token)        # 일부 버전


def get_authed_client(access_token: str, refresh_token: str | None = None) -> Client:
    """
    access_token/refresh_token이 있으면 세션을 세팅하고,
    어떤 경우든 PostgREST에 JWT를 주입해서 RLS 조회가 흔들리지 않게 한다.
    """
    client = get_supabase()

    if refresh_token:
        # 세션 복구(토큰 갱신 포함)
        client.auth.set_session(access_token, refresh_token)

    # ✅ refresh_token이 있든 없든, RLS용으로 JWT는 항상 postgrest에 주입
    _apply_auth(client, access_token)

    return client
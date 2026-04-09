import streamlit as st
from supabase import create_client, Client


def _read_secret(name: str) -> str:
    try:
        return str(st.secrets[name]).strip()
    except Exception:
        return ""


def get_supabase() -> Client:
    url = _read_secret("SUPABASE_URL")
    anon_key = _read_secret("SUPABASE_ANON_KEY")

    if not url or not anon_key:
        st.error("Streamlit Secrets에 SUPABASE_URL 또는 SUPABASE_ANON_KEY가 없습니다.")
        st.stop()

    return create_client(url, anon_key)


def _apply_auth(client: Client, access_token: str):
    if not access_token:
        return
    try:
        client.postgrest.auth(token=access_token)
    except TypeError:
        client.postgrest.auth(access_token)


def get_authed_client(access_token: str, refresh_token: str | None = None) -> Client:
    client = get_supabase()

    if refresh_token:
        client.auth.set_session(access_token, refresh_token)

    _apply_auth(client, access_token)
    return client
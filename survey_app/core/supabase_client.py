import streamlit as st
from supabase import create_client, Client


def get_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    anon_key = st.secrets["SUPABASE_ANON_KEY"]
    return create_client(url, anon_key)


def get_authed_client(access_token: str, refresh_token: str | None = None) -> Client:
    client = get_supabase()

    if refresh_token:
        client.auth.set_session(access_token, refresh_token)
    else:
        try:
            client.postgrest.auth(access_token)
        except TypeError:
            client.postgrest.auth(token=access_token)

    return client

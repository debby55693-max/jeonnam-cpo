import streamlit as st

from core.supabase_client import get_supabase
from pages.field_public import field_public_page

st.set_page_config(page_title="소상공인 방범물품 지원 - 현장", layout="wide")

supabase = get_supabase()
field_public_page(supabase)

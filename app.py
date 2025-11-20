import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium.plugins import LocateControl
import google.generativeai as genai
import json
import os
import uuid
from datetime import datetime
import time
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="FiscalGuard - Alrotek",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed" # Arranca colapsado
)

# --- ESTILOS CSS "MODO APP LIMPIA" ---
# Ocultamos barra superior, flecha del menú y footer.
# La app ocupará toda la pantalla.
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            [data-testid="stSidebarCollapsedControl"] {display: none;}
            .block-container {padding-top: 2rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Cargar variables
load_dotenv()

# --- CONEXIÓN BASE DE DATOS (GOOGLE SHEETS) ---
def get_db_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" not in st.secrets:
        st.error("Faltan los secretos de Google Cloud.")
        return None
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    try:
        sheet = client.open("FiscalGuard_DB").sheet1
        return sheet
    except Exception as e:
        st.error(f"Error DB: {e}")
        return None

def load_data():
    sheet = get_db_connection()
    if not sheet: return []
    try:
        data = sheet.get_all_records()
        return data
    except: return []

def save_data(data):
    sheet = get_db_connection()
    if not sheet: return
    try:
        sheet.clear()
        if not data: return 
        headers = list(data[0].keys())
        sheet.append_row(headers)
        rows_to_upload = [list(item.values()) for item in data]
        sheet.append_rows(rows_to_upload)
    except Exception as e:
        st.error(f"Error guardando: {e}")

# --- SERVICIOS GEMINI (IA) ---
def get_api_key():
    return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def configure_gemini():
    api_key = get_api_key()
    if api_key:
        genai.configure(api_key=api_key)
        return True
    return False

def suggest_coordinates(address, province):
    if not configure_gemini(): return None
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f'Give me the approximate latitude and longitude for {address}, {province}, Costa Rica. Return ONLY JSON: {{ "lat": number, "lng": number }}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except: return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        Extract restaurant info. Normalize provinces. Return JSON schema: 
        {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}
        Text: {raw_text}
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        data = json.loads(response.text)
        return data.get("restaurants", [])
    except: return []

# --- INTERFAZ DE USUARIO ---

# Cargar datos
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# CABECERA (Logo y Título en el centro, ya no en Sidebar)
col_logo, col_title = st.columns([1, 4])
with col_logo:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=100)
    else:
        st.write("🛡️") # Icono si no hay logo
with col_title:
    st.title("FiscalGuard")

# BARRA DE BÚSQUEDA (Con acceso secreto)
with st.container(border=True):
    col_search, col_prov = st.columns([2, 1])
    with col_search:
        # AQUÍ ESTÁ EL TRUCO:
        search_query = st.text_input("🔍 Buscar", placeholder="Local, dirección...")
        
        # --- PUERTA TRASERA ---
        if search_query == "alrotek-admin":
            st.session_state['is_admin'] = True
            st.toast("🔓 Acceso Concedido", icon="😎")
            time.sleep(1)
            st.rerun()
        # ----------------------

    with col_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# Filtrado
df = pd.DataFrame(st.session_state['restaurants'])
if not df.empty:
    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query and search_query != "alrotek-admin":
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# --- VISTA ADMINISTRADOR ---
if st.session_state['is_admin']:
    st.markdown("---")
    # Cabecera Admin con botón de salir
    c_adm, c_out = st.columns([4,1])
    with c_adm: st.subheader("⚙️ Panel de Administración")
    with c_out: 
        if st.button("🔒 Salir"):
            st.session_state['is_admin'] = False
            st.rerun()

    tab1, tab2, tab3 = st.tabs(["📋 Gestión", "➕ Agregar (IA)", "📊 Datos"])
    
    with tab

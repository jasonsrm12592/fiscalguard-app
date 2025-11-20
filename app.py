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
    initial_sidebar_state="collapsed"
)

# --- ESTILOS CSS (Modo Pantalla Completa Limpia) ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            [data-testid="stSidebarCollapsedControl"] {display: none;}
            .block-container {padding-top: 1rem;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

load_dotenv()

# --- FUNCIONES DE BASE DE DATOS ---
def get_db_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" not in st.secrets:
        st.error("Error: Faltan secretos de Google.")
        return None
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    try: return client.open("FiscalGuard_DB").sheet1
    except: return None

def load_data():
    sheet = get_db_connection()
    if not sheet: return []
    try: return sheet.get_all_records()
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
    except: pass

# --- FUNCIONES IA ---
def get_api_key(): return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")
def configure_gemini():
    k = get_api_key()
    if k: genai.configure(api_key=k); return True
    return False

def suggest_coordinates(address, province):
    if not configure_gemini(): return None
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f'Give me latitude/longitude for {address}, {province}, Costa Rica. JSON: {{ "lat": number, "lng": number }}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except: return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f'Extract info. JSON: {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}. Text: {raw_text}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text).get("restaurants", [])
    except: return []

# --- ESTADO DE SESIÓN ---
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# --- INTERFAZ PRINCIPAL ---

# 1. Cabecera (Logo y Título)
col_logo, col_title = st.columns([1, 5])
with col_logo:
    if os.path.exists("logo.png"): st.image("logo.png", width=80)
    else: st.write("🛡️")
with col_title:
    st.title("FiscalGuard")

# 2. Filtros Globales
with st.container(border=True):
    c_search, c_prov = st.columns([2, 1])
    with c_search:
        search_query = st.text_input("🔍 Buscar local o dirección")
    with c_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# Filtrado
df = pd.DataFrame(st.session_state['restaurants'])
if not df.empty:
    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# 3. PESTAÑAS PRINCIPALES (La solución que pediste)
tab_map, tab_list, tab_admin = st.tabs(["🗺️ Mapa", "📋 Listado", "🔐 Acceso Admin"])

# --- PESTAÑA 1: MAPA ---
with tab_map:
    m = folium.Map(location=[9.93, -84.08], zoom_start=9)
    LocateControl(auto_start=False, strings={"title": "Mi Ubicación"}, locateOptions={'enableHighAccuracy': True, 'maxZoom': 18}).add_to(m)
    
    for _, row in df.iterrows():
        if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
            folium.CircleMarker(
                location=[row['lat'], row['lng']], radius=8,
                popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=200),
                color="#dc2626", fill=True, fill_color="#ef4444"
            ).add_to(m)
    st_folium(m, width="100%", height=500, returned_objects=[])

# --- PESTAÑA 2: LISTADO ---
with tab_list:
    st.info(f"Se encontraron {len(df)} locales.")
    for _, row in df.iterrows():
        with st.container(border=True):
            st.subheader(f"🚫 {row['name']}")
            st.text(f"📍 {row['province']}")
            st.caption(row['address'])

# --- PESTAÑA 3: ADMINISTRACIÓN ---
with tab_admin:
    # Si NO está logueado, mostramos el Login
    if not st.session_state['is_admin']:
        st.subheader("Identifícate")
        with st.form("login_form"):
            password = st.text_input("Contraseña de Acceso", type="password")
            if st.form_submit_button("Ingresar"):
                if password in ["4610A"]:
                    st.session_state['is_admin'] = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
    
    # Si SÍ está logueado, mostramos el Panel Completo
    else:
        c_head, c_out = st.columns([3, 1])
        with c_head: st.success("✅ Modo Administrador Activo")
        with c_out:
            if st.button("Cerrar Sesión"):
                st.session_state['is_admin'] = False
                st.rerun()
        
        st.markdown("---")
        
        # Sub-pestañas de gestión
        subtab1, subtab2 = st.tabs(["📝 Editar Tabla", "➕ Agregar Nuevo"])
        
        with subtab1:
            st.caption("Edita las celdas y guarda al final.")
            edited_df = st.data_editor(
                df, num_rows="dynamic", use_container_width=True, key="editor",
                column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")}
            )
            if st.button("💾 Guardar Cambios (Nube)", type="primary"):
                updated_data = edited_df.to_dict(orient='records')
                st.session_state['restaurants'] = updated_data
                save_data(updated_data)
                st.toast('Base de datos actualizada', icon='✅')
                time.sleep(1.5)
                st.rerun()

        with subtab2:
            c_man, c_ai = st.columns(2)
            with c_man:
                st.write("📍 **Manual**")
                with st.form("man"):
                    n = st.text_input("Nombre")
                    p = st.selectbox("Provincia", provinces[1:])
                    a = st.text_input("Dirección")
                    lt = st.number_input("Latitud", format="%.5f")
                    lg = st.number_input("Longitud", format="%.5f")
                    if st.form_submit_button("Guardar"):
                        nr = {"id":str(uuid.uuid4()),"name":n,"province":p,"address":a,"lat":lt,"lng":lg,"addedAt":str(datetime.now())}
                        st.session_state['restaurants'].append(nr)
                        save_data(st.session_state['restaurants'])
                        st.toast('Guardado', icon='🎉')
                        time.sleep(1.5)
                        st.rerun()
            with c_ai:
                st.write("🤖 **Importar con IA**")
                txt = st.text_area("Pega texto desordenado")
                if st.button("Procesar Texto"):
                    with st.spinner("Analizando..."):
                        its = parse


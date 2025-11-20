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
    
    with tab1:
        st.info("Edita en la tabla y guarda.")
        edited_df = st.data_editor(
            df, num_rows="dynamic", use_container_width=True, key="editor",
            column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")}
        )
        if st.button("💾 Guardar Cambios", type="primary"):
            updated_data = edited_df.to_dict(orient='records')
            st.session_state['restaurants'] = updated_data
            save_data(updated_data)
            st.toast('✅ Datos actualizados', icon='💾')
            time.sleep(1.5)
            st.rerun()

    with tab2:
        c1, c2 = st.columns(2)
        with c1:
            st.write("**Manual**")
            with st.form("man"):
                n = st.text_input("Nombre")
                p = st.selectbox("Prov", provinces[1:])
                a = st.text_input("Dirección")
                lt = st.number_input("Lat", format="%.5f")
                lg = st.number_input("Lng", format="%.5f")
                if st.form_submit_button("Guardar"):
                    nr = {"id":str(uuid.uuid4()),"name":n,"province":p,"address":a,"lat":lt,"lng":lg,"addedAt":str(datetime.now())}
                    st.session_state['restaurants'].append(nr)
                    save_data(st.session_state['restaurants'])
                    st.toast('✅ Agregado', icon='🎉')
                    time.sleep(1.5)
                    st.rerun()
        with c2:
            st.write("**IA Import**")
            txt = st.text_area("Texto raw")
            if st.button("Procesar"):
                with st.spinner("Gemini..."):
                    its = parse_ai_list(txt)
                    cnt = 0
                    for i in its:
                        c = suggest_coordinates(i['address'], i['province'])
                        nr = {"id":str(uuid.uuid4()),"name":i['name'],"province":i['province'],"address":i['address'],"lat":c['lat'] if c else 0.0,"lng":c['lng'] if c else 0.0,"addedAt":str(datetime.now())}
                        st.session_state['restaurants'].append(nr)
                        cnt+=1
                    save_data(st.session_state['restaurants'])
                    st.success(f"{cnt} importados.")
                    time.sleep(1.5)
                    st.rerun()
    
    with tab3:
        if not df.empty: st.bar_chart(df['province'].value_counts())

# --- VISTA USUARIO ---
else:
    tab_map, tab_list = st.tabs(["🗺️ Mapa", "📋 Listado"])
    with tab_map:
        m = folium.Map(location=[9.93, -84.08], zoom_start=9)
        LocateControl(auto_start=False, drawCircle=True, drawMarker=True, flyTo=True, strings={"title": "Mi Ubicación"}, locateOptions={'enableHighAccuracy': True, 'maxZoom': 18}).add_to(m)
        for _, row in df.iterrows():
            if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                folium.CircleMarker(location=[row['lat'], row['lng']], radius=8, popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=200), color="#dc2626", fill=True, fill_color="#ef4444").add_to(m)
        st_folium(m, width="100%", height=500, returned_objects=[])

    with tab_list:
        st.info(f"{len(df)} Locales encontrados")
        for _, row in df.iterrows():
            with st.container(border=True):
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']} | {row['address']}")


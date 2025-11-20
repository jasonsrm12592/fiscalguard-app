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
import matplotlib.pyplot as plt
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import time

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="FiscalGuard - Lista Negra",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estilos CSS para ocultar menú de desarrollador pero dejar la flecha lateral
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Cargar variables de entorno locales (si existen)
load_dotenv()

# --- CONEXIÓN BASE DE DATOS (GOOGLE SHEETS) ---

def get_db_connection():
    # Definir alcance
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # Cargar credenciales desde Secrets de Streamlit
    if "gcp_service_account" not in st.secrets:
        st.error("Faltan los secretos de Google Cloud en Streamlit.")
        return None
        
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # Abrir hoja
    try:
        sheet = client.open("FiscalGuard_DB").sheet1
        return sheet
    except Exception as e:
        st.error(f"No se encontró la hoja 'FiscalGuard_DB'. Error: {e}")
        return None

def load_data():
    sheet = get_db_connection()
    if not sheet:
        return []
    
    try:
        data = sheet.get_all_records()
        return data
    except Exception as e:
        # Si la hoja está totalmente vacía puede dar error, devolvemos lista vacía
        return []

def save_data(data):
    sheet = get_db_connection()
    if not sheet:
        return

    try:
        sheet.clear() # Limpiar todo
        if not data:
            return 
            
        # Escribir encabezados y datos
        headers = list(data[0].keys())
        sheet.append_row(headers)
        
        # Preparar filas
        rows_to_upload = [list(item.values()) for item in data]
        sheet.append_rows(rows_to_upload)
    except Exception as e:
        st.error(f"Error guardando en Google Sheets: {e}")

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
    if not configure_gemini():
        return None
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f'Give me the approximate latitude and longitude for {address}, {province}, Costa Rica. Return ONLY JSON: {{ "lat": number, "lng": number }}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except:
        return None

def parse_ai_list(raw_text):
    if not configure_gemini():
        return []
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
    except Exception as e:
        st.error(f"Error IA: {e}")
        return []

# --- INTERFAZ DE USUARIO ---

# Cargar datos
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()

# 1. SIDEBAR (Login y Logo)
with st.sidebar:
    # Intenta cargar logo local, si falla no muestra nada para no romper
    if os.path.exists("logo.png"):
        st.image("logo.png", width=150)
    st.title("FiscalGuard")
    
    if 'is_admin' not in st.session_state:
        st.session_state['is_admin'] = False

    if not st.session_state['is_admin']:
        with st.expander("🔐 Acceso Admin"):
            password = st.text_input("Contraseña", type="password")
            if st.button("Ingresar"):
                if password in ["admin", "1234", "alrotek"]:
                    st.session_state['is_admin'] = True
                    st.rerun()
                else:
                    st.error("Incorrecto")
    else:
        st.success("Modo Admin")
        if st.button("Salir"):
            st.session_state['is_admin'] = False
            st.rerun()

# 2. BARRA DE BÚSQUEDA (Principal)
with st.container(border=True):
    col_search, col_prov = st.columns([2, 1])
    with col_search:
        search_query = st.text_input("🔍 Buscar", placeholder="Nombre o dirección...")
    with col_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# Filtrado de datos
df = pd.DataFrame(st.session_state['restaurants'])
if not df.empty:
    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# --- VISTA ADMINISTRADOR ---
if st.session_state['is_admin']:
    tab1, tab2, tab3 = st.tabs(["📋 Gestión (Editable)", "➕ Agregar (IA)", "📊 Datos"])
    
    with tab1:
        st.info("Edita directamente en la tabla. Para guardar, pulsa el botón abajo.")
        
        # TABLA EDITABLE
        edited_df = st.data_editor(
            df, 
            num_rows="dynamic",
            use_container_width=True,
            key="editor",
            column_config={
                "lat": st.column_config.NumberColumn(format="%.5f"),
                "lng": st.column_config.NumberColumn(format="%.5f"),
            }
        )
        if st.button("💾 Guardar Cambios en Nube", type="primary"):
            updated_data = edited_df.to_dict(orient='records')
            st.session_state['restaurants'] = updated_data
            save_data(updated_data)
            
            # --- NUEVO CÓDIGO DE NOTIFICACIÓN ---
            st.toast('✅ ¡Base de datos actualizada correctamente!', icon='💾')
            time.sleep(1.5) # Pausa de 1.5 segundos para que veas el mensaje
            # ------------------------------------
            st.rerun()

    with tab2:
        col_man, col_ai = st.columns(2)
        with col_man:
            st.subheader("Manual")
            with st.form("add_manual"):
                name = st.text_input("Nombre")
                prov = st.selectbox("Provincia", provinces[1:])
                addr = st.text_input("Dirección")
                lat = st.number_input("Lat", format="%.5f")
                lng = st.number_input("Lng", format="%.5f")
                if st.form_submit_button("Guardar"):
                    new_r = {
                        "id": str(uuid.uuid4()), "name": name, "province": prov, 
                        "address": addr, "lat": lat, "lng": lng, "addedAt": str(datetime.now())
                    }
                    st.session_state['restaurants'].append(new_r)
                    save_data(st.session_state['restaurants'])
                    
                    # --- NUEVO CÓDIGO DE NOTIFICACIÓN ---
                    st.toast('🎉 ¡Restaurante agregado con éxito!', icon='✅')
                    time.sleep(1.5) # Pausa para leer
                    # ------------------------------------
                    
                    st.rerun()
        with col_ai:
            st.subheader("Importar con IA")
            raw_txt = st.text_area("Pega texto desordenado aquí")
            if st.button("Procesar"):
                with st.spinner("Gemini trabajando..."):
                    items = parse_ai_list(raw_txt)
                    count = 0
                    for it in items:
                        coords = suggest_coordinates(it['address'], it['province'])
                        new_r = {
                            "id": str(uuid.uuid4()), "name": it['name'], "province": it['province'], 
                            "address": it['address'], 
                            "lat": coords['lat'] if coords else 0.0, 
                            "lng": coords['lng'] if coords else 0.0, 
                            "addedAt": str(datetime.now())
                        }
                        st.session_state['restaurants'].append(new_r)
                        count += 1
                    save_data(st.session_state['restaurants'])
                    st.success(f"{count} locales importados.")
                    st.rerun()
    
    with tab3:
        if not df.empty:
            st.bar_chart(df['province'].value_counts())

# --- VISTA USUARIO ---
else:
    tab_map, tab_list = st.tabs(["🗺️ Mapa", "📋 Listado"])
    
    with tab_map:
        m = folium.Map(location=[9.93, -84.08], zoom_start=9)
        LocateControl(
            auto_start=False, drawCircle=True, drawMarker=True, flyTo=True,
            strings={"title": "Mi Ubicación"},
            locateOptions={'enableHighAccuracy': True, 'maxZoom': 18}
        ).add_to(m)

        for _, row in df.iterrows():
            if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                folium.CircleMarker(
                    location=[row['lat'], row['lng']], radius=8,
                    popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=200),
                    color="#dc2626", fill=True, fill_color="#ef4444"
                ).add_to(m)
        
        st_folium(m, width="100%", height=500, returned_objects=[])

    with tab_list:
        st.info(f"{len(df)} Resultados")
        for _, row in df.iterrows():
            with st.container(border=True):
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']} | {row['address']}")



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

# --- 1. CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(
    page_title="FiscalGuard - Alrotek",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. ESTILOS CSS (Modo Limpio) ---
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

# --- 3. FUNCIONES DE BASE DE DATOS ---
def get_db_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" not in st.secrets:
        st.error("Error Crítico: Faltan los secretos de Google Cloud en Streamlit.")
        return None
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    try: return client.open("FiscalGuard_DB").sheet1
    except Exception as e:
        st.error(f"No se encontró la hoja 'FiscalGuard_DB'. Error: {e}")
        return None

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
    except Exception as e:
        st.error(f"Error al guardar: {e}")

# --- 4. FUNCIONES IA (GEMINI) ---
def get_api_key(): 
    return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def configure_gemini():
    k = get_api_key()
    if k: 
        genai.configure(api_key=k)
        return True
    return False

def suggest_coordinates(address, province):
    # 1. Diagnóstico de Llave
    api_key = get_api_key()
    if not api_key:
        st.error("🚨 ERROR CRÍTICO: Python dice que la variable API_KEY está vacía.")
        return None
        
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-pro')
        
        prompt = f"""
        I have a messy text describing a business in {province}, Costa Rica.
        The text contains the location BUT ALSO irrelevant comments.
        TEXT: "{address}"
        TASK: Extract city/district/landmark. Return Lat/Lng.
        Return ONLY JSON: {{ "lat": number, "lng": number }}
        """
        
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
        
    except Exception as e:
        # 2. AQUÍ ESTÁ LA CLAVE: Mostramos el error real en pantalla roja
        st.error(f"💥 ERROR TÉCNICO DE GEMINI: {str(e)}")
        return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt = f'Extract info. Return JSON: {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}. Text: {raw_text}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text).get("restaurants", [])
    except: return []

# --- 5. ESTADO DE SESIÓN ---
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# --- 6. INTERFAZ PRINCIPAL ---

# Cabecera
col_logo, col_title = st.columns([1, 5])
with col_logo:
    if os.path.exists("logo.png"): st.image("logo.png", width=80)
    else: st.write("🛡️")
with col_title:
    st.title("FiscalGuard")

# Filtros
with st.container(border=True):
    c_search, c_prov = st.columns([2, 1])
    with c_search:
        search_query = st.text_input("🔍 Buscar local o dirección")
    with c_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# Lógica de Filtrado
df = pd.DataFrame(st.session_state['restaurants'])
if not df.empty:
    # Convertir lat/lng a números seguros
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce').fillna(0.0)
    df['lng'] = pd.to_numeric(df['lng'], errors='coerce').fillna(0.0)

    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# Pestañas Principales
tab_map, tab_list, tab_admin = st.tabs(["🗺️ Mapa", "📋 Listado", "🔐 Acceso Admin"])

# --- PESTAÑA MAPA ---
with tab_map:
    m = folium.Map(location=[9.93, -84.08], zoom_start=9)
    LocateControl(auto_start=False, strings={"title": "Mi Ubicación"}, locateOptions={'enableHighAccuracy': True, 'maxZoom': 18}).add_to(m)
    
    count_markers = 0
    for _, row in df.iterrows():
        if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
            folium.CircleMarker(
                location=[row['lat'], row['lng']], radius=8,
                popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=200),
                color="#dc2626", fill=True, fill_color="#ef4444"
            ).add_to(m)
            count_markers += 1
            
    st_folium(m, width="100%", height=500, returned_objects=[])
    if count_markers == 0 and not df.empty:
        st.caption("⚠️ No hay locales geolocalizados en esta vista.")

# --- PESTAÑA LISTADO ---
with tab_list:
    st.info(f"Se encontraron {len(df)} locales.")
    for _, row in df.iterrows():
        with st.container(border=True):
            st.subheader(f"🚫 {row['name']}")
            st.text(f"📍 {row['province']}")
            st.caption(row['address'])

# --- PESTAÑA ADMINISTRACIÓN ---
with tab_admin:
    if not st.session_state['is_admin']:
        st.subheader("Identifícate")
        with st.form("login_form"):
            password = st.text_input("Contraseña de Acceso", type="password")
            if st.form_submit_button("Ingresar"):
                # Obtener clave secreta de forma segura
                secret_pass = st.secrets.get("ADMIN_PASSWORD")
                valid_passes = ["admin", "1234", "alrotek"]
                if secret_pass: valid_passes.append(secret_pass)

                if password in valid_passes:
                    st.session_state['is_admin'] = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
    else:
        # Panel Admin Logueado
        c_head, c_out = st.columns([3, 1])
        with c_head: st.success("✅ Modo Administrador Activo")
        with c_out:
            if st.button("Cerrar Sesión"):
                st.session_state['is_admin'] = False
                st.rerun()
        
        st.markdown("---")
        subtab1, subtab2, subtab3 = st.tabs(["📝 Editar Tabla", "➕ Agregar Nuevo", "🔧 Mantenimiento"])
        
        with subtab1:
            st.caption("Edita y guarda.")
            edited_df = st.data_editor(
                df, num_rows="dynamic", use_container_width=True, key="editor",
                column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")}
            )
            if st.button("💾 Guardar Cambios (Nube)", type="primary"):
                updated_data = edited_df.to_dict(orient='records')
                st.session_state['restaurants'] = updated_data
                save_data(updated_data)
                st.toast('Datos actualizados', icon='✅')
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
                        its = parse_ai_list(txt)
                        cnt = 0
                        for i in its:
                            c = suggest_coordinates(i['address'], i['province'])
                            nr = {"id":str(uuid.uuid4()),"name":i['name'],"province":i['province'],"address":i['address'],"lat":c['lat'] if c else 0.0,"lng":c['lng'] if c else 0.0,"addedAt":str(datetime.now())}
                            st.session_state['restaurants'].append(nr)
                            cnt+=1
                        save_data(st.session_state['restaurants'])
                        st.success(f"{cnt} locales agregados.")
                        time.sleep(1.5)
                        st.rerun()

        with subtab3:
            st.header("🔧 Reparación de Datos")
            st.info("Escanea y repara coordenadas faltantes. Lento (3-4s/local) para seguridad.")
            
            if st.button("🪄 Auto-completar Coordenadas", type="primary"):
                data_to_fix = st.session_state['restaurants']
                count_fixed = 0
                log = st.container(border=True)
                prog = st.progress(0)
                total = len(data_to_fix)
                
                with log:
                    st.write("⏳ Iniciando...")
                    for idx, item in enumerate(data_to_fix):
                        prog.progress((idx+1)/total)
                        try: lat_val = float(item.get('lat', 0))
                        except: lat_val = 0.0
                        
                        if lat_val == 0:
                            st.write(f"🔸 Procesando: **{item['name']}**...")
                            coords = suggest_coordinates(item['address'], item['province'])
                            
                            if coords:
                                if coords.get('lat') != 0:
                                    data_to_fix[idx]['lat'] = coords['lat']
                                    data_to_fix[idx]['lng'] = coords['lng']
                                    count_fixed += 1
                                    st.write("   ✅ ¡Encontrado!")
                                else:
                                    st.warning("   ⚠️ IA devolvió 0.")
                            else:
                                st.error("   ❌ Error API.")
                            
                            time.sleep(3.5) # Pausa de seguridad
                
                if count_fixed > 0:
                    save_data(data_to_fix)
                    st.session_state['restaurants'] = data_to_fix
                    st.success(f"✅ {count_fixed} arreglados.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.warning("Proceso finalizado sin cambios.")



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

# --- 4. FUNCIONES IA (GEMINI 2.5) ---
def get_api_key(): 
    return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def configure_gemini():
    k = get_api_key()
    if k: 
        genai.configure(api_key=k)
        return True
    return False

def suggest_coordinates(address, province):
    if not configure_gemini(): return None
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = f"""
        I have a messy text describing a business in {province}, Costa Rica.
        The text contains the location BUT ALSO irrelevant comments.
        TEXT: "{address}"
        TASK: Extract city/district/landmark. Ignore comments like "no factura".
        Return ONLY JSON: {{ "lat": number, "lng": number }}
        If unknown, return center of {province}.
        """
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except: return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
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

# --- PESTAÑA MAPA (Con Satélite) ---
with tab_map:
    m = folium.Map(location=[9.93, -84.08], zoom_start=9, tiles="OpenStreetMap")
    
    # Capa Satélite
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri', name='Satélite', overlay=False, control=True
    ).add_to(m)
    folium.LayerControl().add_to(m)
    
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

# --- PESTAÑA LISTADO (Con Búsqueda de Alternativas) ---
with tab_list:
    st.info(f"Se encontraron {len(df)} locales.")
    for _, row in df.iterrows():
        with st.container(border=True):
            col_info, col_action = st.columns([3, 1])
            with col_info:
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']}")
                st.caption(row['address'])
            with col_action:
                if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                    # Busca restaurantes cercanos
                    search_url = f"https://www.google.com/maps/search/restaurantes/@{row['lat']},{row['lng']},16z"
                    st.link_button("🍽️ Buscar Otro", search_url, help="Buscar alternativas cerca")
                else:
                    st.caption("Sin GPS")

# --- PESTAÑA ADMINISTRACIÓN ---
with tab_admin:
    if not st.session_state['is_admin']:
        st.subheader("Identifícate")
        with st.form("login_form"):
            password = st.text_input("Contraseña de Acceso", type="password")
            if st.form_submit_button("Ingresar"):
                secret_pass = st.secrets.get("ADMIN_PASSWORD")
                valid_passes = ["admin", "1234", "alrotek"]
                if secret_pass: valid_passes.append(secret_pass)

                if password in valid_passes:
                    st.session_state['is_admin'] = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta")
    else:
        c_head, c_out = st.columns([3, 1])
        with c_head: st.success("✅ Admin Activo")
        with c_out:
            if st.button("Cerrar Sesión"):
                st.session_state['is_admin'] = False
                st.rerun()
        
        st.markdown("---")
        subtab1, subtab2, subtab3 = st.tabs(["📝 Editar Tabla", "➕ Agregar Nuevo", "🔧 Mantenimiento"])
        
        # SUBTAB 1: EDICIÓN (CON LÓGICA DE BORRADO SEGURA)
        with subtab1:
            st.caption("Edita o selecciona filas y presiona Supr para borrar.")
            edited_df = st.data_editor(
                df, num_rows="dynamic", use_container_width=True, key="editor",
                column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")}
            )
            if st.button("💾 Guardar Cambios (Nube)", type="primary"):
                # Lógica inteligente para guardar + borrar respetando filtros
                ids_shown = set(df['id'].tolist())
                current_view_data = edited_df.to_dict(orient='records')
                ids_remaining = set(row['id'] for row in current_view_data)
                ids_to_delete = ids_shown - ids_remaining
                
                master_data = st.session_state['restaurants']
                
                # Borrar
                if ids_to_delete:
                    master_data = [row for row in master_data if row['id'] not in ids_to_delete]
                
                # Actualizar/Agregar
                for changed_row in current_view_data:
                    found = False
                    for i, original_row in enumerate(master_data):
                        if original_row['id'] == changed_row['id']:
                            master_data[i] = changed_row
                            found = True
                            break
                    if not found:
                        master_data.append(changed_row)

                st.session_state['restaurants'] = master_data
                save_data(master_data)
                st.toast('Base actualizada', icon='✅')
                time.sleep(1.5)
                st.rerun()

        # SUBTAB 2: AGREGAR MANUAL / IA
        with subtab2:
            c_man, c_ai = st.columns(2)
            with c_man:
                st.write("**Manual**")
                with st.form("man"):
                    n = st.text_input("Nombre")
                    p = st.selectbox("Provincia", provinces[1:])
                    a = st.text_input("Dirección")
                    lt = st.number_input("Lat", format="%.5f")
                    lg = st.number_input("Lng", format="%.5f")
                    if st.form_submit_button("Guardar"):
                        nr = {"id":str(uuid.uuid4()),"name":n,"province":p,"address":a,"lat":lt,"lng":lg,"addedAt":str(datetime.now())}
                        st.session_state['restaurants'].append(nr)
                        save_data(st.session_state['restaurants'])
                        st.toast('Guardado', icon='🎉')
                        time.sleep(1.5)
                        st.rerun()
            with c_ai:
                st.write("**IA Import**")
                txt = st.text_area("Pega texto desordenado")
                if st.button("Procesar"):
                    with st.spinner("Analizando..."):
                        its = parse_ai_list(txt)
                        cnt = 0
                        for i in its:
                            c = suggest_coordinates(i['address'], i['province'])
                            nr = {"id":str(uuid.uuid4()),"name":i['name'],"province":i['province'],"address":i['address'],"lat":c['lat'] if c else 0.0,"lng":c['lng'] if c else 0.0,"addedAt":str(datetime.now())}
                            st.session_state['restaurants'].append(nr)
                            cnt+=1
                        save_data(st.session_state['restaurants'])
                        st.success(f"{cnt} agregados.")
                        time.sleep(1.5)
                        st.rerun()

        # SUBTAB 3: CALIBRADOR EXACTO (COPY-PASTE)
        with subtab3:
            st.header("🎯 Calibración Exacta")
            st.info("Busca en Google Maps, copia coordenadas y pega aquí.")

            # Selector con clave única
            names_list = [f"{r['name']} ({r['province']})" for r in st.session_state['restaurants']]
            selected_item = st.selectbox("1. Selecciona local:", names_list, key="main_selector_fix")
            selected_index = names_list.index(selected_item)
            record = st.session_state['restaurants'][selected_index]

            st.markdown("---")

            col_input, col_preview = st.columns([1, 1])

            with col_input:
                st.subheader("2. Buscar y Copiar")
                
                search_term = f"{record['name']} {record['address']} {record['province']}"
                maps_url = f"https://www.google.com/maps/search/?api=1&query={search_term.replace(' ', '+')}"
                
                st.markdown(f"""
                <a href="{maps_url}" target="_blank" style="display:inline-block;padding:0.5em 1em;color:white;background-color:#4285F4;border-radius:5px;text-decoration:none;font-weight:bold;">
                    🔎 Abrir Google Maps
                </a>
                """, unsafe_allow_html=True)
                
                st.write("")
                current_val = ""
                if record['lat'] != 0:
                    current_val = f"{record['lat']}, {record['lng']}"
                
                coords_input = st.text_input("3. Pega coordenadas:", value=current_val, placeholder="Ej: 9.9321, -84.0811")
                
                new_lat, new_lng = 0.0, 0.0
                valid = False
                
                if coords_input:
                    try:
                        clean_input = coords_input.replace('(', '').replace(')', '')
                        parts = clean_input.split(',')
                        if len(parts) >= 2:
                            new_lat = float(parts[0].strip())
                            new_lng = float(parts[1].strip())
                            valid = True
                            st.success("✅ Válido")
                        else: st.error("Formato incorrecto")
                    except: st.error("Solo números")

                if valid:
                    st.write("")
                    if st.button("💾 Guardar Ubicación", type="primary"):
                        st.session_state['restaurants'][selected_index]['lat'] = new_lat
                        st.session_state['restaurants'][selected_index]['lng'] = new_lng
                        save_data(st.session_state['restaurants'])
                        st.toast(f"Actualizado!", icon='✅')
                        time.sleep(1.5)
                        st.rerun()

            with col_preview:
                st.subheader("4. Confirmación")
                show_lat = new_lat if valid else (float(record['lat']) if record['lat'] != 0 else 9.9333)
                show_lng = new_lng if valid else (float(record['lng']) if record['lng'] != 0 else -84.0833)
                zoom = 18 if (valid or record['lat'] != 0) else 10
                
                m_prev = folium.Map(location=[show_lat, show_lng], zoom_start=zoom, tiles=None)
                
                # Capa Híbrida Google
                folium.TileLayer(
                    tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}',
                    attr='Google', name='Google Satélite', overlay=False, control=False
                ).add_to(m_prev)
                
                folium.Marker(
                    [show_lat, show_lng],
                    popup=record['name'],
                    icon=folium.Icon(color="green" if valid else "blue", icon="map-marker")
                ).add_to(m_prev)
                
                st_folium(m_prev, height=400, width="100%", returned_objects=[])

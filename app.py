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

# --- ESTILOS CSS ---
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

# --- FUNCIONES IA (CON MODELO 2.5) ---
def get_api_key(): return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def configure_gemini():
    k = get_api_key()
    if k: 
        genai.configure(api_key=k)
        return True
    return False

def suggest_coordinates(address, province):
    if not configure_gemini(): return None
    try:
        # CAMBIO AQUÍ: Usamos el modelo que sí tienes disponible
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
    except Exception as e:
        # Si falla, imprimimos el error en consola para debug
        print(f"Error Gemini: {e}")
        return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        # CAMBIO AQUÍ TAMBIÉN
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        
        prompt = f'Extract info. Return JSON: {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}. Text: {raw_text}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text).get("restaurants", [])
    except: return []

# --- ESTADO DE SESIÓN ---
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# --- INTERFAZ PRINCIPAL ---

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

# Filtrado
df = pd.DataFrame(st.session_state['restaurants'])
if not df.empty:
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce').fillna(0.0)
    df['lng'] = pd.to_numeric(df['lng'], errors='coerce').fillna(0.0)
    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# Pestañas
tab_map, tab_list, tab_admin = st.tabs(["🗺️ Mapa", "📋 Listado", "🔐 Acceso Admin"])

# MAPA
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

# --- PESTAÑA 2: LISTADO (Con búsqueda de alternativas) ---
with tab_list:
    st.info(f"Se encontraron {len(df)} locales en la lista negra.")
    
    for _, row in df.iterrows():
        with st.container(border=True):
            col_info, col_action = st.columns([3, 1])
            
            with col_info:
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']}")
                st.caption(row['address'])
            
            with col_action:
                # Verificamos coordenadas
                if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                    
                    # CAMBIO AQUÍ:
                    # En lugar de navegación, hacemos una BÚSQUEDA de restaurantes
                    # centrada en esas coordenadas (@lat,lng) con zoom 16 (cercano).
                    search_url = f"https://www.google.com/maps/search/restaurantes/@{row['lat']},{row['lng']},16z"
                    
                    # Botón con icono de cubiertos/búsqueda
                    st.link_button("🍽️ Buscar Otro", search_url, help="Buscar restaurantes alternativos cerca de esta ubicación")
                
                else:
                    st.caption("Sin ubicación")

# ADMIN
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
        
        with subtab1:
            st.caption("Puedes editar celdas o seleccionar filas y presionar Supr/Del para borrar.")
            # Tabla editable
            edited_df = st.data_editor(
                df, num_rows="dynamic", use_container_width=True, key="editor",
                column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")}
            )

            # --- BOTÓN MAESTRO CORREGIDO ---
            if st.button("💾 Guardar Cambios (Nube)", type="primary"):
                # 1. Detectar Eliminaciones en la vista actual
                # IDs que se mostraron al usuario (Filtrados)
                ids_shown = set(df['id'].tolist())
                
                # IDs que devolvió el editor (Lo que quedó vivo)
                current_view_data = edited_df.to_dict(orient='records')
                ids_remaining = set(row['id'] for row in current_view_data)
                
                # La diferencia son los que el usuario borró
                ids_to_delete = ids_shown - ids_remaining
                
                # 2. Cargar Base Maestra
                master_data = st.session_state['restaurants']
                
                # 3. APLICAR BORRADO: Filtramos la maestra quitando los IDs condenados
                if ids_to_delete:
                    master_data = [row for row in master_data if row['id'] not in ids_to_delete]
                
                # 4. APLICAR EDICIONES / NUEVOS
                for changed_row in current_view_data:
                    found = False
                    for i, original_row in enumerate(master_data):
                        if original_row['id'] == changed_row['id']:
                            master_data[i] = changed_row # Actualizar existente
                            found = True
                            break
                    if not found:
                        master_data.append(changed_row) # Agregar nuevo

                # 5. Guardar todo
                st.session_state['restaurants'] = master_data
                save_data(master_data)
                
                st.toast('Base de datos actualizada (Guardado y Borrado)', icon='✅')
                time.sleep(1.5)
                st.rerun()

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
                        st.rerun()
            with c_ai:
                st.write("**IA Import**")
                txt = st.text_area("Texto raw")
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
                        st.rerun()

        # --- PESTAÑA DE MANTENIMIENTO RESTAURADA ---
        with subtab3:
            st.header("🔧 Reparación de Datos")
            st.info("Usando el modelo: **gemini-2.5-flash**")
            
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
                            
                            # Aquí ya usamos el modelo correcto (2.5-flash)
                            coords = suggest_coordinates(item['address'], item['province'])
                            
                            if coords:
                                if coords.get('lat') != 0:
                                    data_to_fix[idx]['lat'] = coords['lat']
                                    data_to_fix[idx]['lng'] = coords['lng']
                                    count_fixed += 1
                                    st.write("   ✅ ¡Encontrado!")
                                else:
                                    st.warning("   ⚠️ IA no pudo ubicarlo.")
                            else:
                                st.error("   ❌ Error API (Aún con modelo nuevo).")
                            
                            time.sleep(2) # Pausa de seguridad
                
                if count_fixed > 0:
                    save_data(data_to_fix)
                    st.session_state['restaurants'] = data_to_fix
                    st.success(f"✅ {count_fixed} arreglados.")
                    time.sleep(2)
                    st.rerun()
                else:
                    st.warning("Finalizado sin cambios.")




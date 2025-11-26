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

# --- 1. CONFIGURACIÓN ---
st.set_page_config(
    page_title="FiscalGuard - Alrotek",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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

# --- 2. BASE DE DATOS ---
def get_db_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    if "gcp_service_account" not in st.secrets:
        st.error("Error: Faltan secretos.")
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

# --- 3. IA (GEMINI 2.5) ---
def get_api_key(): 
    return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def configure_gemini():
    k = get_api_key()
    if k: genai.configure(api_key=k); return True
    return False

def suggest_coordinates(address, province):
    if not configure_gemini(): return None
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = f'Get lat/lng for "{address}" in {province}, Costa Rica. Return JSON {{ "lat": number, "lng": number }}.'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except: return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('models/gemini-2.5-flash')
        prompt = f'Extract to JSON {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}. Text: {raw_text}'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text).get("restaurants", [])
    except: return []

# --- 4. ESTADO ---
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()
if 'is_admin' not in st.session_state:
    st.session_state['is_admin'] = False

# --- 5. INTERFAZ ---

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
        search_query = st.text_input("🔍 Buscar")
    with c_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# Datos
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
    m = folium.Map(location=[9.93, -84.08], zoom_start=9, tiles=None)
    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Google Satélite', overlay=False, control=True).add_to(m)
    folium.TileLayer(tiles='OpenStreetMap', name='Calles', overlay=False, control=True).add_to(m)
    folium.LayerControl().add_to(m)
    LocateControl(auto_start=False, strings={"title": "Mi Ubicación"}, locateOptions={'enableHighAccuracy': True, 'maxZoom': 18}).add_to(m)

    cnt = 0
    for _, row in df.iterrows():
        if pd.notna(row['lat']) and row['lat'] != 0:
            folium.CircleMarker([row['lat'], row['lng']], radius=8, popup=row['name'], color="#dc2626", fill=True, fill_color="#ef4444").add_to(m)
            cnt += 1
    st_folium(m, width="100%", height=500, returned_objects=[])
    if cnt == 0: st.caption("⚠️ Sin ubicaciones visibles.")

# LISTADO
with tab_list:
    st.info(f"{len(df)} locales.")
    for _, row in df.iterrows():
        with st.container(border=True):
            c1, c2 = st.columns([3, 1])
            with c1:
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']}")
                st.caption(row['address'])
            with c2:
                if pd.notna(row['lat']) and row['lat'] != 0:
                    url = f"https://www.google.com/maps/search/restaurantes/@{row['lat']},{row['lng']},16z"
                    st.link_button("🍽️ Buscar Otro", url)
                else:
                    st.caption("Sin GPS")

# ADMIN
with tab_admin:
    if not st.session_state['is_admin']:
        st.subheader("Login")
        with st.form("login"):
            pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Entrar"):
                s_pass = st.secrets.get("ADMIN_PASSWORD")
                v_pass = ["admin", "1234", "alrotek"]
                if s_pass: v_pass.append(s_pass)
                if pwd in v_pass:
                    st.session_state['is_admin'] = True
                    st.rerun()
                else: st.error("Incorrecto")
    else:
        c_h, c_o = st.columns([3, 1])
        with c_h: st.success("✅ Admin")
        with c_o:
            if st.button("Salir"):
                st.session_state['is_admin'] = False
                st.rerun()

        st.markdown("---")
        t1, t2, t3 = st.tabs(["📝 Editar", "➕ Agregar", "🔧 Calibrar"])

        with t1:
            ed = st.data_editor(df, num_rows="dynamic", key="ed1", column_config={"lat": st.column_config.NumberColumn(format="%.5f"), "lng": st.column_config.NumberColumn(format="%.5f")})
            if st.button("💾 Guardar Cambios", type="primary"):
                ids_S = set(df['id'].tolist())
                curr = ed.to_dict(orient='records')
                ids_R = set(row['id'] for row in curr)
                del_ids = ids_S - ids_R
                master = st.session_state['restaurants']
                if del_ids: master = [r for r in master if r['id'] not in del_ids]
                for c_row in curr:
                    found = False
                    for i, m_row in enumerate(master):
                        if m_row['id'] == c_row['id']:
                            master[i] = c_row; found = True; break
                    if not found: master.append(c_row)
                st.session_state['restaurants'] = master
                save_data(master)
                st.toast('Guardado', icon='✅'); time.sleep(1.5); st.rerun()

        with t2:
            c_m, c_a = st.columns(2)
            with c_m:
                st.write("**Manual**")
                with st.form("man"):
                    n = st.text_input("Nombre"); p = st.selectbox("Prov", provinces[1:]); a = st.text_input("Dir")
                    if st.form_submit_button("Guardar"):
                        nr = {"id":str(uuid.uuid4()),"name":n,"province":p,"address":a,"lat":0.0,"lng":0.0,"addedAt":str(datetime.now())}
                        st.session_state['restaurants'].append(nr)
                        save_data(st.session_state['restaurants'])
                        st.toast('Guardado', icon='🎉'); st.rerun()
            with c_a:
                st.write("**IA**")
                txt = st.text_area("Texto")
                if st.button("Procesar"):
                    with st.spinner("..."):
                        its = parse_ai_list(txt)
                        for i in its:
                            c = suggest_coordinates(i['address'], i['province'])
                            nr = {"id":str(uuid.uuid4()),"name":i['name'],"province":i['province'],"address":i['address'],"lat":c['lat'] if c else 0.0,"lng":c['lng'] if c else 0.0,"addedAt":str(datetime.now())}
                            st.session_state['restaurants'].append(nr)
                        save_data(st.session_state['restaurants'])
                        st.success("Listo"); st.rerun()

        # --- CALIBRADOR SIMPLE Y SEGURO ---
        # --- HERRAMIENTA HÍBRIDA (PEGAR O TOCAR) ---
        with t3:
            st.header("🎯 Calibración")
            st.info("Busca en Maps, copia coordenadas y pega.")

            nm_list = [f"{r['name']} ({r['province']})" for r in st.session_state['restaurants']]
            sel = st.selectbox("Local:", nm_list, key="sel_calib")
            sel = st.selectbox("1. Local:", nm_list, key="sel_calib_final")
            idx = nm_list.index(sel)
            rec = st.session_state['restaurants'][idx]

            col1, col2 = st.columns(2)
            # SELECTOR DE MODO
            mode = st.radio("2. Método de ubicación:", ["📋 Pegar Coordenadas (Desde Maps)", "👆 Tocar en el Mapa (Visual)"], horizontal=True)

            with col1:
                # CAMBIO: Usamos st.link_button simple en vez de HTML complejo
                # Esto evita el error de colores azules en VS Code
                search_t = f"{rec['name']} {rec['address']} {rec['province']}"
                url_maps = f"https://www.google.com/maps/search/?api=1&query={search_t.replace(' ', '+')}"
                st.link_button("🔎 Buscar en Google Maps", url_maps)
            st.markdown("---")

            # --- MODO A: PEGAR ---
            if mode == "📋 Pegar Coordenadas (Desde Maps)":
                c1, c2 = st.columns(2)
                with c1:
                    st.info("Busca en Maps > Clic derecho > Copia números")
                    search_t = f"{rec['name']} {rec['address']} {rec['province']}"
                    url_maps = f"https://www.google.com/maps/search/?api=1&query={search_t.replace(' ', '+')}"
                    st.link_button("🔎 Abrir Google Maps", url_maps)
                    
                    curr_v = f"{rec['lat']}, {rec['lng']}" if rec['lat'] != 0 else ""
                    inp = st.text_input("Pega aquí:", value=curr_v, placeholder="Ej: 9.935123, -84.051234")
                    
                    n_lat, n_lng, valid = 0.0, 0.0, False
                    if inp:
                        try:
                            cl = inp.replace('(','').replace(')','')
                            pts = cl.split(',')
                            if len(pts)>=2:
                                n_lat = float(pts[0]) # SIN REDONDEO
                                n_lng = float(pts[1]) # SIN REDONDEO
                                valid = True
                                st.success(f"✅ {n_lat}, {n_lng}")
                        except: st.error("Error formato")
                    
                    if valid and st.button("💾 Guardar Pegado", type="primary"):
                        st.session_state['restaurants'][idx]['lat'] = n_lat
                        st.session_state['restaurants'][idx]['lng'] = n_lng
                        save_data(st.session_state['restaurants'])
                        st.toast('Listo', icon='✅'); time.sleep(1.5); st.rerun()

                with c2:
                    slat = n_lat if valid else (float(rec['lat']) if rec['lat']!=0 else 9.9333)
                    slng = n_lng if valid else (float(rec['lng']) if rec['lng']!=0 else -84.0833)
                    zm = 18 if (valid or rec['lat']!=0) else 10
                    mp = folium.Map([slat, slng], zoom_start=zm, tiles=None)
                    folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satélite', overlay=False).add_to(mp)
                    folium.Marker([slat, slng], icon=folium.Icon(color="green" if valid else "blue")).add_to(mp)
                    st_folium(mp, height=350, width="100%", returned_objects=[])

            # --- MODO B: TOCAR ---
            else:
                st.info("Navega y haz clic en el techo exacto.")

                curr_v = f"{rec['lat']}, {rec['lng']}" if rec['lat'] != 0 else ""
                inp = st.text_input("Pega Coordenadas:", value=curr_v, placeholder="Ej: 9.935, -84.051")
                # Coordenadas iniciales del mapa
                start_lat = float(rec['lat']) if rec['lat'] != 0 else 9.9333
                start_lng = float(rec['lng']) if rec['lng'] != 0 else -84.0833
                start_zoom = 18 if rec['lat'] != 0 else 10

                m_click = folium.Map([start_lat, start_lng], zoom_start=start_zoom, tiles=None)
                folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satélite', overlay=False).add_to(m_click)
                folium.TileLayer(tiles='OpenStreetMap', name='Calles', overlay=False).add_to(m_click)
                folium.LayerControl().add_to(m_click)

                n_lat, n_lng, valid = 0.0, 0.0, False
                if inp:
                    try:
                        cl = inp.replace('(','').replace(')','')
                        pts = cl.split(',')
                        if len(pts)>=2:
                            n_lat = round(float(pts[0]), 5)
                            n_lng = round(float(pts[1]), 5)
                            valid = True
                            st.success(f"✅ {n_lat}, {n_lng}")
                    except: st.error("Error formato")
                # Marcador actual
                if rec['lat'] != 0:
                    folium.Marker([rec['lat'], rec['lng']], popup="Actual", icon=folium.Icon(color="blue")).add_to(m_click)

                if valid and st.button("💾 Guardar", type="primary"):
                    st.session_state['restaurants'][idx]['lat'] = n_lat
                    st.session_state['restaurants'][idx]['lng'] = n_lng
                    save_data(st.session_state['restaurants'])
                    st.toast('Listo', icon='✅'); time.sleep(1.5); st.rerun()

            with col2:
                slat = n_lat if valid else (float(rec['lat']) if rec['lat']!=0 else 9.9333)
                slng = n_lng if valid else (float(rec['lng']) if rec['lng']!=0 else -84.0833)
                zm = 18 if (valid or rec['lat']!=0) else 10
                # Habilitar clic
                m_click.add_child(folium.LatLngPopup())

                mp = folium.Map([slat, slng], zoom_start=zm, tiles=None)
                folium.TileLayer(tiles='https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}', attr='Google', name='Satélite', overlay=False).add_to(mp)
                folium.Marker([slat, slng], icon=folium.Icon(color="green" if valid else "blue")).add_to(mp)
                st_folium(mp, height=350, width="100%", returned_objects=[])
                # Output del mapa
                out = st_folium(m_click, height=500, width="100%", returned_objects=["last_clicked"])
                
                if out and out['last_clicked']:
                    clat = out['last_clicked']['lat']
                    clng = out['last_clicked']['lng']
                    st.success(f"📍 Seleccionado: {clat}, {clng}")
                    
                    if st.button("💾 Guardar Clic", type="primary"):
                        st.session_state['restaurants'][idx]['lat'] = clat
                        st.session_state['restaurants'][idx]['lng'] = clng
                        save_data(st.session_state['restaurants'])
                        st.toast('Ubicación guardada', icon='✅')
                        time.sleep(1.5)
                        st.rerun()

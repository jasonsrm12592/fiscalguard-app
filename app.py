import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
import google.generativeai as genai
import json
import os
import uuid
from datetime import datetime
import matplotlib.pyplot as plt
from dotenv import load_dotenv
from folium.plugins import LocateControl

# --- CARGAR VARIABLES DE ENTORNO ---
load_dotenv()

# --- CONFIGURACIÓN INICIAL ---
st.set_page_config(
    page_title="FiscalGuard - Lista Negra",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)
# --- OCULTAR MENÚ Y FOOTER DE STREAMLIT ---
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# Archivo local para persistencia de datos
DATA_FILE = "restaurants_data.json"

# --- SERVICIOS (Gemini & Data) ---

def get_api_key():
    # Intenta obtener de variables de entorno o secrets de streamlit
    return os.getenv("API_KEY") or st.secrets.get("API_KEY", "")

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    else:
        # Datos semilla si no existe el archivo
        return [
            {"id": "1", "name": "Soda La Evasora", "province": "San José", "address": "Av Central", "lat": 9.9333, "lng": -84.0833, "addedAt": str(datetime.now())},
            {"id": "2", "name": "Bar El Sin Papel", "province": "Heredia", "address": "Cerca del parque", "lat": 9.9981, "lng": -84.1198, "addedAt": str(datetime.now())}
        ]

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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
    except Exception as e:
        st.error(f"Error IA Geolocalización: {e}")
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
        st.error(f"Error IA Parsing: {e}")
        return []

# --- INTERFAZ DE USUARIO ---

# Cargar datos al estado de sesión
if 'restaurants' not in st.session_state:
    st.session_state['restaurants'] = load_data()

# 1. SIDEBAR (Solo dejamos el Login y Logo para limpiar espacio)
with st.sidebar:
    st.image("logo.png", width=150)
    st.title("FiscalGuard")
    
    # Modo Admin Toggle
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

# 2. BARRA DE BÚSQUEDA (Ahora en la pantalla principal)
# Usamos un contenedor para que destaque
with st.container(border=True):
    col_search, col_prov = st.columns([2, 1])
    
    with col_search:
        search_query = st.text_input("🔍 Buscar", placeholder="Nombre del local o dirección...")
    
    with col_prov:
        provinces = ["Todas", "San José", "Alajuela", "Cartago", "Heredia", "Guanacaste", "Puntarenas", "Limón"]
        selected_province = st.selectbox("Provincia", provinces)

# --- LÓGICA PRINCIPAL ---

# Filtrar datos para mostrar
df = pd.DataFrame(st.session_state['restaurants'])

if not df.empty:
    if selected_province != "Todas":
        df = df[df['province'] == selected_province]
    if search_query:
        df = df[df['name'].str.contains(search_query, case=False) | df['address'].str.contains(search_query, case=False)]

# --- VISTA ADMINISTRADOR ---
if st.session_state['is_admin']:
    tab1, tab2, tab3 = st.tabs(["📋 Lista & Gestión", "➕ Agregar (Manual/IA)", "📊 Estadísticas"])
    
    with tab1:
        st.subheader("📋 Lista y Gestión de Locales")
        st.info("Puedes editar las celdas directamente en la tabla.")

        # Usamos st.data_editor para una tabla editable
        edited_df = st.data_editor(
            df[['id', 'name', 'province', 'address', 'lat', 'lng', 'addedAt']], # Columnas a mostrar y editar
            num_rows="dynamic", # Permite al usuario añadir filas (aunque las nuevas no tienen ID auto)
            hide_index=True,    # Oculta el índice numérico de Pandas
            use_container_width=True, # Adapta al ancho de la columna
            key="editable_restaurants_table" # Identificador único para este widget
        )

        st.markdown("---")
        col_save, col_delete_selected = st.columns([1, 1])

        with col_save:
            # Botón para guardar los cambios editados
            if st.button("💾 Guardar Cambios Editados", type="primary"):
                # Convertimos el DataFrame editado a la lista de diccionarios original
                updated_restaurants = edited_df.to_dict(orient='records')
                
                # Sincronizar con st.session_state
                # OJO: Aquí estamos reemplazando completamente la lista.
                # En un sistema real, verificarías IDs y fusionarías.
                st.session_state['restaurants'] = updated_restaurants
                save_data(st.session_state['restaurants'])
                st.success("¡Cambios guardados con éxito!")
                st.rerun() # Recargar la app para mostrar los datos actualizados

        with col_delete_selected:
            # Opción para eliminar múltiples filas seleccionadas
            if not edited_df.empty:
                st.write("Selecciona filas para eliminar en la tabla de arriba.")
                # st.data_editor devuelve el DataFrame editado.
                # Las filas eliminadas no aparecen en edited_df.
                # Para implementar la eliminación de UNA LÍNEA como querías,
                # st.data_editor es un poco más complejo porque no te da un botón por fila.
                # La mejor forma de hacer un "botón de basurero por fila" es con un enfoque más manual.
                # Por ahora, con data_editor se edita/añade, la eliminación es un poco más indirecta
                # o requiere que el usuario borre el contenido de la fila.

                # Para una eliminación directa, podemos volver a una tabla manual
                # o esperar a una futura mejora de Streamlit.
                # Por ahora, el usuario puede borrar el contenido de la fila y luego "Guardar Cambios".
                # O una opción de 'Eliminar todo lo que NO está en esta tabla editada'.
                pass # Eliminación por fila directa es más avanzada con data_editor.

    with tab2:
        col_manual, col_ai = st.columns(2)
        
        with col_manual:
            st.subheader("Manual")
            with st.form("manual_add"):
                name = st.text_input("Nombre")
                prov = st.selectbox("Provincia", provinces[1:]) # Skip 'Todas'
                addr = st.text_input("Dirección")
                
                lat = st.number_input("Latitud", min_value=-90.0, max_value=90.0, format="%.6f", value=0.0)
                lng = st.number_input("Longitud", min_value=-180.0, max_value=180.0, format="%.6f", value=0.0)
                
                submitted = st.form_submit_button("Guardar")
                if submitted:
                    if any(r['name'].lower() == name.lower() for r in st.session_state['restaurants']):
                        st.error("El restaurante ya existe.")
                    else:
                        new_r = {
                            "id": str(uuid.uuid4()),
                            "name": name,
                            "province": prov,
                            "address": addr,
                            "lat": lat if lat != 0 else None,
                            "lng": lng if lng != 0 else None,
                            "addedAt": str(datetime.now())
                        }
                        st.session_state['restaurants'].append(new_r)
                        save_data(st.session_state['restaurants'])
                        st.success("Agregado correctamente")
                        st.rerun()

        with col_ai:
            st.subheader("Importar con IA")
            st.info("Pega texto desordenado o celdas de Excel.")
            raw_text = st.text_area("Texto Raw")
            if st.button("Procesar con Gemini"):
                with st.spinner("Analizando y geolocalizando..."):
                    parsed = parse_ai_list(raw_text)
                    count = 0
                    for p in parsed:
                        if any(r['name'].lower() == p['name'].lower() for r in st.session_state['restaurants']):
                            continue
                        
                        coords = suggest_coordinates(p['address'], p['province'])
                        
                        new_r = {
                            "id": str(uuid.uuid4()),
                            "name": p['name'],
                            "province": p['province'],
                            "address": p['address'],
                            "lat": coords['lat'] if coords else None,
                            "lng": coords['lng'] if coords else None,
                            "addedAt": str(datetime.now())
                        }
                        st.session_state['restaurants'].append(new_r)
                        count += 1
                    
                    save_data(st.session_state['restaurants'])
                    st.success(f"Se importaron {count} restaurantes nuevos.")
                    st.rerun()

    with tab3:
        st.subheader("Restaurantes por Provincia")
        if not df.empty:
            chart_data = df['province'].value_counts()
            st.bar_chart(chart_data)
        else:
            st.warning("Sin datos.")

# --- VISTA USUARIO (MAPA Y LISTA) ---
else:
    # CAMBIO RESPONSIVE: Usamos Pestañas en lugar de Columnas.
    # Esto hace que en el celular se vea perfecto (uno a la vez).
    tab_map, tab_list = st.tabs(["🗺️ Mapa Interactiva", "📋 Lista de Locales"])
    
  # 1. Pestaña del Mapa (Aprovecha todo el ancho)
    with tab_map:
        # Mapa Base
        m = folium.Map(location=[9.7489, -83.7534], zoom_start=8)
        
        # --- GPS DE ALTA PRECISIÓN ---
        LocateControl(
            auto_start=False,
            drawCircle=True,
            drawMarker=True,
            flyTo=True,
            strings={"title": "Mostrar mi ubicación precisa"},
            locateOptions={
                'enableHighAccuracy': True,
                'maxZoom': 18
            }
        ).add_to(m)
        # -----------------------------

        for idx, row in df.iterrows():
            # Mantenemos la corrección de seguridad (NaN)
            if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                folium.CircleMarker(
                    location=[row['lat'], row['lng']],
                    radius=8,
                    popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=250),
                    color="#dc2626",
                    fill=True,
                    fill_color="#ef4444"
                ).add_to(m)
        
        # Ajustamos la altura para que quepa bien en celulares (500px está bien)
        # CAMBIO AQUÍ: Agregamos returned_objects=[]
        st_folium(m, width="100%", height=500, returned_objects=[])
        for idx, row in df.iterrows():
            # Mantenemos la corrección de seguridad (NaN)
            if pd.notna(row['lat']) and pd.notna(row['lng']) and row['lat'] != 0:
                folium.CircleMarker(
                    location=[row['lat'], row['lng']],
                    radius=8,
                    popup=folium.Popup(f"<b>{row['name']}</b><br>{row['address']}", max_width=250),
                    color="#dc2626",
                    fill=True,
                    fill_color="#ef4444"
                ).add_to(m)
        
        # Ajustamos la altura para que quepa bien en celulares (500px está bien)
        st_folium(m, width="100%", height=500)

    # 2. Pestaña del Listado
    with tab_list:
        st.info(f"Se encontraron {len(df)} registros.")
        for idx, row in df.iterrows():
            # Usamos un contenedor con borde para que se vea como tarjeta en el cel
            with st.container(border=True):
                st.subheader(f"🚫 {row['name']}")
                st.text(f"📍 {row['province']}")
                st.caption(row['address'])

                st.warning("Reporte: No entrega factura electrónica")

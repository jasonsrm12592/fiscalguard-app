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
        # Prompt optimizado para geolocalización
        prompt = f'Give me latitude/longitude for {address}, {province}, Costa Rica. Return ONLY JSON: {{ "lat": number, "lng": number }}. If unknown, estimate district center.'
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except: return None

def parse_ai_list(raw_text):
    if not configure_gemini(): return []
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f'Extract info. Return JSON: {{ "restaurants": [ {{ "name": str, "province": str, "address": str }} ] }}. Text: {raw_text}'
        response = model.generate_content(prompt

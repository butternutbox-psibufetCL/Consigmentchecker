import streamlit as st
import pandas as pd
import re
import difflib
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import time

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="Butternut Box | BRT System", page_icon="🚚", layout="wide")
st.title("🚚 Hybrydowy System Logistyczny BRT")
st.markdown("Walidacja ISTAT + AI + Automatyczny Radar Opóźnień.")

# --- KONFIGURACJA AI (PASEK BOCZNY) ---
st.sidebar.header("⚙️ Ustawienia AI")
api_key = st.sidebar.text_input("Wklej klucz Gemini API:", type="password")

if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        st.sidebar.success("AI połączone! Funkcje odblokowane.")
    except Exception as e:
        st.sidebar.error("Błąd połączenia z API.")

# --- BAZA LOKALNA ---
@st.cache_data
def load_cap_database():
    try:
        df_cap = pd.read_csv('gi_comuni_cap.csv', dtype=str, sep=';') 
        df_cap.columns = [col.lower().strip() for col in df_cap.columns]
        return df_cap
    except FileNotFoundError:
        return None

df_cap = load_cap_database()
if df_cap is None:
    st.error("❌ Brakuje pliku 'gi_comuni_cap.csv'.")
    st.stop()

# --- GŁÓWNY SILNIK WALIDUJĄCY (OFFLINE) ---
def validate_address(street, city, zip_code, df_cap):
    issues = []
    status = "✅ OK"
    
    street = str(street)
    city = str(city).strip()
    zip_code = str(zip_code).strip()

    if len(zip_code) < 5 and zip_code != 'nan' and zip_code != '':
        zip_code = zip_code.zfill(5)
        issues.append(f"Dodano zera: {zip_code}")

    if re.search(r"[éàòìùÉÀÒÌÙ’‘`]", street) or re.search(r"[’‘`]", city):
        street = re.sub(r'[éÉ]', 'e', street)
        street = re.sub(r'[àÀ]', 'a', street)
        street = re.sub(r'[òÒ]', 'o', street)
        street = re.sub(r'[ìÌ]', 'i', street)
        street = re.sub(r'[ùÙ]', 'u', street)
        street = re.sub(r"[’‘`]", "'", street)
        city = re.sub(r"[’‘`]", "'", city)
        issues.append("Naprawiono akcenty/apostrofy")

    clean_city = re.sub(r'\s*\([A-Za-z]{2}\)', '', city)
    clean_city = re.sub(r'\s+[A-Za-z]{2}$', '', clean_city).strip() # Fix na prowincje bez nawiasów np. PV
    clean_city = clean_city.split('/')[0].strip()

    if 'cap' in df_cap.columns and 'denominazione_ita' in df_cap.columns:
        matching_rows = df_cap[df_cap['cap'] == zip_code]
        if matching_rows.empty:
            status = "❌ Wymaga poprawy"
            issues.append(f"KRYTYCZNE: CAP {zip_code} nie istnieje.")
        else:
            official_cities = matching_rows['denominazione_ita'].str.lower().tolist()
            matches = difflib.get_close_matches(clean_city.lower(), official_cities, n=1, cutoff=0.75)
            if not matches:
                status = "❌ Wymaga poprawy"
                suggested_city = matching_rows.iloc[0]['denominazione_ita'].title()
                issues.append(f"BŁĄD: Miasto '{city}' nie pasuje do {zip_code}. Powinno być: {suggested_city}")
    return status, " | ".join(issues)

# --- SCRAPER STATUSÓW BRT ---
def check_brt_status(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text().lower()
        
        if "consegnata" in page_text: return "✅ Dostarczona (Consegnata)"
        elif "in consegna" in page_text: return "🚚 W doręczeniu (In consegna)"
        elif "rifiutata" in page_text or "respinta" in page_text: return "❌ Odrzucona przez klienta"
        elif "indirizzo errato" in page_text or "manca" in page_text or "errato" in page_text: return "❌ Błąd adresu"
        elif "lasciato avviso" in page_text or "assente" in page_text: return "⚠️ Nikogo nie było w domu (Awizo)"
        elif "giacenza" in page_text: return "📦 Utknęła w oddziale (Giacenza)"
        else: return "⚠️ Wymaga sprawdzenia ręcznego"
    except:
        return "❌ Błąd połączenia ze stroną"

# --- ZAKŁADKI ---
tab1, tab2, tab3 = st.tabs(["📁 Masowe sprawdzanie", "🔍 AI Support", "📡 Radar Opóźnień BRT"])

# --- ZAKŁADKA 1: MASOWE SPRAWDZANIE ---
with tab1:
    uploaded_file = st.file_uploader("Wgraj plik CSV z adresami", type=["csv"], key="csv_upload")
    if uploaded_file:
        df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
        if st.button("🚀 Uruchom Walidację", type="primary"):
            results_status, results_fixes = [], []
            for index, row in df.iterrows():
                status, fixes = validate_address(row.get('Address 1', row.get('Address', '')), row.get('City', row.get('Delivery Area', '')), row.get('Postcode', ''), df_cap)
                results_status.append(status)
                results_fixes.append(fixes)
            df['Status Systemowy'] = results_status
            df['Raport'] = results_fixes
            st.success("✅ Dane gotowe!")
            st.dataframe(df[df['Status Systemowy'] != "✅ OK"] if not df[df['Status Systemowy'] != "✅ OK"].empty else df)
            st.download_button("📥 Pobierz plik", df.to_csv(index=False).encode('utf-8'), 'Gotowe_BRT.csv', 'text/csv')

# --- ZAKŁADKA 2: SUPPORT / AI ---
with tab2:
    st.markdown("### 🕵️‍♂️ Narzędzie dla Customer Supportu")
    col1, col2, col3 = st.columns(3)
    with col1: man_street = st.text_input("Ulica")
    with col2: man_city = st.text_input("Miasto")
    with col3: man_zip = st.text_input("Kod pocztowy")
        
    if st.button("🔍 Waliduj dla nShift"):
        if man_city and man_zip:
            status, fixes = validate_address(man_street, man_city, man_zip, df_cap)
            st.markdown("---")
            if status == "✅ OK":
                st.success(f"**Status:** {status}")
                if fixes: st.info(f"**Autokorekta:** {fixes}")
            else:
                st.error("ODRZUCONY przez nShift")
                st.warning(f"**Błąd:** {fixes}")
                
                if api_key:
                    if st.button("🛠️ AI: Napraw Adres"):
                        with st.spinner("AI analizuje..."):
                            response = model.generate_content(f'Zrekonstruuj błędny adres dla kuriera nShift. Oddziel Ulicę, Miasto i Kod. Adres: "{man_street} {man_city} {man_zip}". Zwróć tylko czysty JSON: {{"Ulica": "", "Miasto": "", "Kod": ""}}')
                            st.code(response.text.replace('```json', '').replace('```', '').strip(), language='json')
        else:
            st.error("⚠️ Podaj miasto i kod.")

# --- ZAKŁADKA 3: RADAR OPÓŹNIEŃ BRT ---
with tab3:
    st.markdown("### 📡 Radar Opóźnień (Skaner Trackingu)")
    st.markdown("Wgraj raport `Details.csv`, a system sam sprawdzi włoskie statusy na stronie BRT i wyciągnie paczki wymagające interwencji (Ad-hoc box).")
    
    details_file = st.file_uploader("Wgraj plik 'Details.csv'", type=["csv"], key="details_upload")
    
    if details_file:
        # Próba wczytania pliku (często raporty mają przesunięty nagłówek)
        df_details = pd.read_csv(details_file)
        if 'Tracking URL' not in df_details.columns:
            details_file.seek(0)
            df_details = pd.read_csv(details_file, header=1) # Jeżeli Looker dodaje puste wiersze u góry
            
        if 'Tracking URL' in df_details.columns and 'Soc Link' in df_details.columns:
            # Odrzucamy te z jawnym statusem delivered w nShift
            if 'Consignment Status' in df_details.columns:
                df_pending = df_details[df_details['Consignment Status'] != 'delivered'].copy()
            else:
                df_pending = df_details.copy()
                
            # Filtrujemy tylko te, które mają fizycznie wygenerowany link
            df_pending = df_pending.dropna(subset=['Tracking URL'])
            
            st.info(f"🔎 Znaleziono {len(df_pending)} paczek wymagających weryfikacji. Rozpoczynam skanowanie BRT...")
            
            if st.button("🚀 Uruchom skanowanie linków BRT", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                real_statuses = []
                total = len(df_pending)
                
                for i, row in enumerate(df_pending.iterrows()):
                    url = str(row[1]['Tracking URL'])
                    if "http" in url:
                        # Pobieramy prawdziwy status ze strony BRT
                        brt_status = check_brt_status(url)
                    else:
                        brt_status = "Brak prawidłowego linku"
                        
                    real_statuses.append(brt_status)
                    
                    # Aktualizacja paska postępu
                    progress_bar.progress((i + 1) / total)
                    status_text.text(f"Skanowanie: {i + 1} z {total} paczek...")
                    time.sleep(0.5) # Krótka pauza, by BRT nie zablokowało bota
                
                df_pending['Prawdziwy Status BRT'] = real_statuses
                
                # Zostawiamy tylko problemy (odrzucamy te, które na stronie okazały się już dostarczone)
                df_critical = df_pending[~df_pending['Prawdziwy Status BRT'].str.contains("Dostarczona", na=False)]
                
                st.success("✅ Skanowanie zakończone!")
                st.markdown("### 🚨 Akcje Krytyczne (Zamówienia wymagające interwencji):")
                
                # Przygotowujemy ładną tabelę dla Supportu
                df_display = df_critical[['Prawdziwy Status BRT', 'Tracking URL', 'Soc Link']]
                
                # Używamy st.data_editor z formatowaniem linków, żeby można było w nie klikać
                st.data_editor(
                    df_display,
                    column_config={
                        "Tracking URL": st.column_config.LinkColumn("Link BRT"),
                        "Soc Link": st.column_config.LinkColumn("Profil Klienta (CRM)")
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                st.download_button(
                    label="📥 Pobierz listę problemów",
                    data=df_critical.to_csv(index=False).encode('utf-8'),
                    file_name='Raport_Krytyczny_BRT.csv',
                    mime='text/csv'
                )
        else:
            st.error("Błąd: Plik nie zawiera wymaganych kolumn ('Tracking URL', 'Soc Link'). Upewnij się, że wgrywasz poprawny raport Details.csv.")

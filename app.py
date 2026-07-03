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
st.markdown("Walidacja ISTAT + AI + Automatyczny Radar Opóźnień (Teraz z oryginalnymi komunikatami BRT!).")

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
    clean_city = re.sub(r'\s+[A-Za-z]{2}$', '', clean_city).strip() 
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

# --- SCRAPER STATUSÓW BRT (NOWA WERSJA) ---
def check_brt_status(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text().lower()
        
        # 1. Kategoryzacja na podstawie słów kluczowych
        basic_status = "⚠️ W drodze / Inny"
        if "consegnata" in page_text: basic_status = "✅ Dostarczona"
        elif "in consegna" in page_text: basic_status = "🚚 W doręczeniu"
        elif "rifiutata" in page_text or "respinta" in page_text: basic_status = "❌ Odrzucona"
        elif "indirizzo errato" in page_text or "manca" in page_text or "errato" in page_text: basic_status = "❌ Błąd adresu"
        elif "lasciato avviso" in page_text or "assente" in page_text: basic_status = "⚠️ Awizo (Nieobecność)"
        elif "giacenza" in page_text: basic_status = "📦 Utknęła w oddziale (Giacenza)"

        # 2. Inteligentne wyciąganie tekstu z kolumny "Stato della spedizione"
        exact_status = "Brak szczegółów na stronie"
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            if not rows: continue
            
            # Szukamy kolumny ze statusem w nagłówku tabeli
            col_index = -1
            header_cells = rows[0].find_all(['th', 'td'])
            
            for i, cell in enumerate(header_cells):
                cell_text = cell.get_text(strip=True).lower()
                if "stato della spedizione" in cell_text or "esito" in cell_text:
                    col_index = i
                    break
            
            # Jeśli znaleźliśmy nagłówek, pobieramy komórkę z pierwszego wiersza z danymi poniżej
            if col_index != -1 and len(rows) > 1:
                data_cells = rows[1].find_all(['td', 'th'])
                if col_index < len(data_cells):
                    exact_status = data_cells[col_index].get_text(separator=" ", strip=True)
                break

        return basic_status, exact_status
    except:
        return "❌ Błąd połączenia", "Nie udało się pobrać strony"

# --- SMART DETEKTOR KOLUMN ---
def load_robust_csv(uploaded_file, required_columns):
    uploaded_file.seek(0)
    df_temp = pd.read_csv(uploaded_file, header=None) 
    
    header_idx = None
    for idx, row in df_temp.head(20).iterrows():
        row_str = " ".join([str(val) for val in row.values])
        if all(req in row_str for req in required_columns):
            header_idx = idx
            break
            
    if header_idx is not None:
        uploaded_file.seek(0)
        return pd.read_csv(uploaded_file, header=header_idx)
    return None

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
                            response = model.generate_content(f'Zrekonstruuj błędny adres. Oddziel Ulicę, Miasto i Kod. Adres: "{man_street} {man_city} {man_zip}". Zwróć JSON: {{"Ulica": "", "Miasto": "", "Kod": ""}}')
                            st.code(response.text.replace('```json', '').replace('```', '').strip(), language='json')
        else:
            st.error("⚠️ Podaj miasto i kod.")

# --- ZAKŁADKA 3: RADAR OPÓŹNIEŃ BRT ---
with tab3:
    st.markdown("### 📡 Radar Opóźnień (Odporny na formatowanie)")
    st.markdown("Wgraj raport CSV. System sam znajdzie paczki niedoręczone, połączy się z BRT i pobierze **dokładny tekst komunikatu kuriera**.")
    
    details_file = st.file_uploader("Wgraj plik raportu BRT/Looker", type=["csv"], key="details_upload")
    
    if details_file:
        df_details = load_robust_csv(details_file, ['Tracking URL', 'Soc Link'])
            
        if df_details is not None:
            status_col = [col for col in df_details.columns if 'status' in col.lower()]
            if status_col:
                df_pending = df_details[df_details[status_col[0]].astype(str).str.lower() != 'delivered'].copy()
            else:
                df_pending = df_details.copy()
                
            df_pending = df_pending.dropna(subset=['Tracking URL'])
            df_pending = df_pending[df_pending['Tracking URL'].astype(str).str.contains('http')]
            
            st.info(f"🔎 Oczyszczono plik! Wyizolowano {len(df_pending)} paczek wymagających sprawdzenia na serwerach BRT.")
            
            if st.button("🚀 Skanuj statusy BRT", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                real_statuses = []
                exact_statuses = []
                total = len(df_pending)
                
                for i, row in enumerate(df_pending.iterrows()):
                    url = str(row[1]['Tracking URL'])
                    basic, exact = check_brt_status(url)
                    
                    real_statuses.append(basic)
                    exact_statuses.append(exact)
                    
                    progress_bar.progress((i + 1) / total)
                    status_text.text(f"Sprawdzam na serwerach BRT: {i + 1} / {total}")
                    time.sleep(0.5) 
                
                df_pending['Kategoria Statusu'] = real_statuses
                df_pending['Ostatni Status z BRT'] = exact_statuses
                
                df_critical = df_pending[~df_pending['Kategoria Statusu'].str.contains("Dostarczona", na=False)]
                
                st.success("✅ Skanowanie zakończone!")
                st.markdown("### 🚨 Wymagane Akcje (Szczegóły z portalu BRT):")
                
                df_display = df_critical[['Kategoria Statusu', 'Ostatni Status z BRT', 'Tracking URL', 'Soc Link']]
                st.data_editor(
                    df_display,
                    column_config={
                        "Tracking URL": st.column_config.LinkColumn("Link BRT"),
                        "Soc Link": st.column_config.LinkColumn("Profil CRM"),
                        "Ostatni Status z BRT": st.column_config.TextColumn("Dokładny Komunikat Kuriera")
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                st.download_button(
                    label="📥 Pobierz pełny raport problemów",
                    data=df_critical.to_csv(index=False).encode('utf-8'),
                    file_name='Raport_Krytyczny_BRT_Szczegolowy.csv',
                    mime='text/csv'
                )
        else:
            st.error("❌ Błąd: Nie znalazłem w tym pliku kolumn 'Tracking URL' ani 'Soc Link'.")

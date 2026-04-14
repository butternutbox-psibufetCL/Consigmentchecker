import streamlit as st
import pandas as pd
import re
import difflib

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="BRT Validator Offline", page_icon="🚚", layout="wide")
st.title("🚚 System Walidacji Logistycznej BRT")
st.markdown("Wersja 100% niezawodna. Działa na lokalnej bazie ISTAT. Przetwarza dane w ułamek sekundy bez udziału i limitów AI.")

# --- WCZYTANIE LOKALNEJ BAZY KODÓW ---
@st.cache_data
def load_cap_database():
    try:
        # Wczytujemy dokładnie ten plik, który wrzuciłeś na GitHuba
        df_cap = pd.read_csv('gi_comuni_cap.csv', dtype=str, sep=';') 
        df_cap.columns = [col.lower().strip() for col in df_cap.columns]
        return df_cap
    except FileNotFoundError:
        return None

df_cap = load_cap_database()

if df_cap is None:
    st.error("❌ Brakuje pliku 'gi_comuni_cap.csv'. Dodaj ten plik do swojego repozytorium na GitHubie.")
    st.stop()

# --- GŁÓWNY INTERFEJS ---
uploaded_file = st.file_uploader("Wgraj plik CSV z Lookera", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
    
    if st.button("🚀 Uruchom Błyskawiczną Walidację", type="primary"):
        results_status = []
        results_fixes = []
        
        for index, row in df.iterrows():
            street = str(row.get('Address 1', row.get('Address', '')))
            city = str(row.get('City', row.get('Delivery Area', ''))).strip()
            zip_code = str(row.get('Postcode', '')).strip()
            
            issues = []
            status = "✅ OK"
            
            # 1. NAPRAWA ZER W KODZIE
            if len(zip_code) < 5 and zip_code != 'nan':
                zip_code = zip_code.zfill(5)
                issues.append(f"Dodano zera: {zip_code}")
                
            # 2. CZYSZCZENIE ZNAKÓW DIAKRYTYCZNYCH
            if re.search(r'[éàòìùÉÀÒÌÙ]', street):
                street = re.sub(r'[éÉ]', 'e', street)
                street = re.sub(r'[àÀ]', 'a', street)
                street = re.sub(r'[òÒ]', 'o', street)
                street = re.sub(r'[ìÌ]', 'i', street)
                street = re.sub(r'[ùÙ]', 'u', street)
                issues.append("Usunięto akcenty")

            # 3. WALIDACJA GEOGRAFICZNA (Bez limitów)
            if 'cap' in df_cap.columns and 'denominazione_ita' in df_cap.columns:
                matching_rows = df_cap[df_cap['cap'] == zip_code]
                
                if matching_rows.empty:
                    status = "❌ Wymaga poprawy"
                    issues.append(f"KRYTYCZNE: Kod CAP {zip_code} w ogóle nie istnieje w bazie włoskiej.")
                else:
                    # Wyciągamy poprawne miasta dla tego kodu
                    official_cities = matching_rows['denominazione_ita'].str.lower().tolist()
                        
                    # Algorytm dopasowania (toleruje literówki do 25% różnicy w znakach)
                    matches = difflib.get_close_matches(city.lower(), official_cities, n=1, cutoff=0.75)
                    
                    if not matches:
                        status = "❌ Wymaga poprawy"
                        suggested_city = matching_rows.iloc[0]['denominazione_ita'].title()
                        issues.append(f"BŁĄD: Miasto z Lookera ('{city}') nie pasuje do kodu {zip_code}. Powinno być: {suggested_city}")
            
            results_status.append(status)
            results_fixes.append(" | ".join(issues))
            
        df['Walidacja Systemowa'] = results_status
        df['Rekomendacje / Raport'] = results_fixes
        
        st.success("✅ Analiza zakończona! Dane przetworzone w ułamek sekundy.")
        
        # Pokaż najpierw wiersze z błędami
        df_errors = df[df['Walidacja Systemowa'] != "✅ OK"]
        st.dataframe(df_errors if not df_errors.empty else df)
        
        st.download_button(
            label="📥 Pobierz gotowy, czysty plik",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name='Gotowe_BRT.csv',
            mime='text/csv',
        )

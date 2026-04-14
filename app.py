import streamlit as st
import pandas as pd
import google.generativeai as genai
import re
import time
import json

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="BRT Validator AI", page_icon="🚚", layout="wide")
st.title("🚚 AI Logistics Validator (BRT/nShift)")
st.markdown("Wgraj plik CSV z Lookera. AI przeanalizuje miasta i kody pocztowe, a system automatycznie naprawi ucięte zera i włoskie akcenty.")

# --- STAŁY KLUCZ API ---
API_KEY = "AIzaSyCad9SeljWKjwb7S5Pp4RbtTB4FhrakxK4"
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- GŁÓWNY INTERFEJS ---
uploaded_file = st.file_uploader("Wgraj plik CSV z Lookera", type=["csv"])

if uploaded_file:
    # Wczytanie pliku - wymuszamy, aby kod pocztowy był traktowany jako tekst!
    df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
    
    st.subheader("Oryginalne dane (Podgląd):")
    st.dataframe(df.head())

    if st.button("🚀 Uruchom Analizę AI", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        results_status = []
        results_fixes = []
        
        total_rows = len(df)
        
        for index, row in df.iterrows():
            progress_bar.progress((index + 1) / total_rows)
            status_text.text(f"Analizowanie wiersza {index + 1} z {total_rows}...")
            
            street = str(row.get('Address 1', row.get('Address', '')))
            city = str(row.get('City', row.get('Delivery Area', '')))
            zip_code = str(row.get('Postcode', '')).strip()
            
            # --- FAZA 1: Szybkie czyszczenie w Pythonie ---
            issues = []
            
            if len(zip_code) < 5 and zip_code != 'nan':
                zip_code = zip_code.zfill(5)
                issues.append(f"Zaktualizowano CAP na {zip_code}")
                
            if re.search(r'[éàòìùÉÀÒÌÙ]', street):
                street = re.sub(r'[éÉ]', 'e', street)
                street = re.sub(r'[àÀ]', 'a', street)
                street = re.sub(r'[òÒ]', 'o', street)
                street = re.sub(r'[ìÌ]', 'i', street)
                street = re.sub(r'[ùÙ]', 'u', street)
                issues.append("Usunięto akcenty z adresu")

            # --- FAZA 2: Analiza AI (Tylko logistyka) ---
            prompt = f"""
            Analyze this Italian address for shipping:
            City: {city}
            ZIP Code: {zip_code}
            
            Task:
            1. Check if the ZIP matches the City.
            2. Check if the City is a "Frazione". If yes, find the main municipality.
            
            Respond ONLY in valid JSON format:
            {{"status": "OK" or "ERROR", "message": "Short explanation or empty if OK"}}
            """
            
            try:
                response = model.generate_content(prompt)
                ai_text = response.text.replace('```json', '').replace('```', '').strip()
                ai_data = json.loads(ai_text)
                
                if ai_data.get("status") == "ERROR":
                    issues.append(ai_data.get("message"))
                    
            except Exception as e:
                issues.append(f"Błąd API: Odczekaj chwilę")
                time.sleep(2) 
            
            if len(issues) == 0:
                results_status.append("✅ OK")
                results_fixes.append("")
            else:
                results_status.append("❌ Wymaga poprawy")
                results_fixes.append(" | ".join(issues))
                
            time.sleep(0.5) # Bezpieczny odstęp
            
        df['AI Status'] = results_status
        df['Rekomendacje'] = results_fixes
        
        status_text.text("✅ Analiza zakończona sukcesem!")
        
        st.subheader("Wyniki Analizy:")
        df_errors = df[df['AI Status'] != "✅ OK"]
        st.dataframe(df_errors if not df_errors.empty else df)
        
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Pobierz zwalidowany plik CSV",
            data=csv,
            file_name='Validated_BRT_Deliveries.csv',
            mime='text/csv',
        )

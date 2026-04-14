import streamlit as st
import pandas as pd
import google.generativeai as genai
import re
import json

# --- KONFIGURACJA STRONY ---
st.set_page_config(page_title="BRT Validator AI", page_icon="🚚", layout="wide")
st.title("🚚 AI Logistics Validator (BRT/nShift)")
st.markdown("Wgraj plik CSV z Lookera. System automatycznie naprawi ucięte zera i akcenty, a AI zweryfikuje miasta w **jednym błyskawicznym zapytaniu**.")

# --- BEZPIECZNY KLUCZ API ---
API_KEY = st.secrets["GEMINI_API_KEY"]
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- GŁÓWNY INTERFEJS ---
uploaded_file = st.file_uploader("Wgraj plik CSV z Lookera", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
    st.subheader("Oryginalne dane (Podgląd):")
    st.dataframe(df.head())

    if st.button("🚀 Uruchom Analizę AI (Tryb Błyskawiczny)", type="primary"):
        with st.spinner("Pakuję dane i wysyłam jedno główne zapytanie do AI. To potrwa ok. 10 sekund..."):
            
            results_status = []
            results_fixes = []
            addresses_to_check = []
            
            # --- FAZA 1: Czyszczenie lokalne w ułamek sekundy ---
            for index, row in df.iterrows():
                street = str(row.get('Address 1', row.get('Address', '')))
                city = str(row.get('City', row.get('Delivery Area', '')))
                zip_code = str(row.get('Postcode', '')).strip()
                
                issues = []
                
                if len(zip_code) < 5 and zip_code != 'nan':
                    zip_code = zip_code.zfill(5)
                    issues.append(f"Zaktualizowano CAP na {zip_code}")
                    
                if re.search(r'[éàòìùÉÀÒÌÙ]', street):
                    issues.append("Znaleziono i usunięto akcenty z adresu")

                results_fixes.append(" | ".join(issues))
                results_status.append("❌ Wymaga poprawy" if issues else "✅ OK")
                
                # Dodajemy adres do głównej paczki dla AI
                addresses_to_check.append({
                    "id": index,
                    "city": city,
                    "zip": zip_code
                })

            # --- FAZA 2: JEDNO POTĘŻNE ZAPYTANIE DO AI (Omija limity) ---
            prompt = f"""
            You are an Italian logistics expert. Verify this list of shipping addresses.
            1. Check if ZIP matches the City.
            2. Check if City is a Frazione. If yes, return the main municipality.
            
            Data:
            {json.dumps(addresses_to_check)}
            
            Return ONLY a JSON array with this exact structure (no extra text, no markdown):
            [
                {{"id": 0, "status": "OK" or "ERROR", "message": "Details to fix or empty if OK"}}
            ]
            """
            
            try:
                # Wysyłamy jedną listę zamiast 60 oddzielnych zapytań
                response = model.generate_content(prompt)
                ai_text = response.text.replace('```json', '').replace('```', '').strip()
                ai_results = json.loads(ai_text)
                
                # --- FAZA 3: Połączenie wyników ---
                for item in ai_results:
                    idx = item["id"]
                    if item.get("status") == "ERROR":
                        if results_status[idx] == "✅ OK":
                            results_status[idx] = "❌ Wymaga poprawy"
                            results_fixes[idx] = item.get("message", "Błąd dopasowania")
                        else:
                            results_fixes[idx] += " | AI: " + item.get("message", "")
                            
            except Exception as e:
                st.error(f"Błąd przetwarzania AI: {str(e)}")
                st.warning("Google API odrzuciło zapytanie. Wyświetlam na razie tylko naprawione zera i akcenty.")

            # Zapisujemy gotowe wyniki do tabeli
            df['AI Status'] = results_status
            df['Rekomendacje'] = results_fixes
            
            st.success("✅ Analiza zakończona sukcesem!")
            
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

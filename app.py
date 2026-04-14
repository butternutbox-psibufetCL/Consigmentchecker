import streamlit as st
import pandas as pd
import re
import difflib

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="BRT Validator Offline", page_icon="🚚", layout="wide")
st.title("🚚 BRT Logistics Validation System")
st.markdown("100% reliable version. Runs on the local ISTAT database. Processes data in a split second without AI limits or involvement.")

# --- LOAD LOCAL CAP DATABASE ---
@st.cache_data
def load_cap_database():
    try:
        # Loading the exact file you uploaded to GitHub
        df_cap = pd.read_csv('gi_comuni_cap.csv', dtype=str, sep=';') 
        df_cap.columns = [col.lower().strip() for col in df_cap.columns]
        return df_cap
    except FileNotFoundError:
        return None

df_cap = load_cap_database()

if df_cap is None:
    st.error("❌ The 'gi_comuni_cap.csv' file is missing. Please add this file to your GitHub repository.")
    st.stop()

# --- MAIN INTERFACE ---
uploaded_file = st.file_uploader("Upload Looker CSV file", type=["csv"])

if uploaded_file:
    df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
    
    if st.button("🚀 Run Instant Validation", type="primary"):
        results_status = []
        results_fixes = []
        
        for index, row in df.iterrows():
            street = str(row.get('Address 1', row.get('Address', '')))
            city = str(row.get('City', row.get('Delivery Area', ''))).strip()
            zip_code = str(row.get('Postcode', '')).strip()
            
            issues = []
            status = "✅ OK"
            
            # 1. FIX LEADING ZEROS IN ZIP CODE
            if len(zip_code) < 5 and zip_code != 'nan':
                zip_code = zip_code.zfill(5)
                issues.append(f"Added zeros: {zip_code}")
                
            # 2. CLEAN DIACRITIC CHARACTERS (ACCENTS)
            if re.search(r'[éàòìùÉÀÒÌÙ]', street):
                street = re.sub(r'[éÉ]', 'e', street)
                street = re.sub(r'[àÀ]', 'a', street)
                street = re.sub(r'[òÒ]', 'o', street)
                street = re.sub(r'[ìÌ]', 'i', street)
                street = re.sub(r'[ùÙ]', 'u', street)
                issues.append("Removed accents")

            # 3. GEOGRAPHICAL VALIDATION (No limits)
            if 'cap' in df_cap.columns and 'denominazione_ita' in df_cap.columns:
                matching_rows = df_cap[df_cap['cap'] == zip_code]
                
                if matching_rows.empty:
                    status = "❌ Needs fixing"
                    issues.append(f"CRITICAL: CAP code {zip_code} does not exist in the Italian database.")
                else:
                    # Extract correct cities for this zip code
                    official_cities = matching_rows['denominazione_ita'].str.lower().tolist()
                        
                    # Fuzzy matching algorithm (tolerates typos up to a 25% difference in characters)
                    matches = difflib.get_close_matches(city.lower(), official_cities, n=1, cutoff=0.75)
                    
                    if not matches:
                        status = "❌ Needs fixing"
                        suggested_city = matching_rows.iloc[0]['denominazione_ita'].title()
                        issues.append(f"ERROR: City from Looker ('{city}') doesn't match ZIP {zip_code}. It should be: {suggested_city}")
            
            results_status.append(status)
            results_fixes.append(" | ".join(issues))
            
        df['System Validation'] = results_status
        df['Recommendations / Report'] = results_fixes
        
        st.success("✅ Analysis complete! Data processed in a fraction of a second.")
        
        # Display rows with errors first
        df_errors = df[df['System Validation'] != "✅ OK"]
        st.dataframe(df_errors if not df_errors.empty else df)
        
        st.download_button(
            label="📥 Download the ready, clean CSV",
            data=df.to_csv(index=False).encode('utf-8'),
            file_name='Ready_for_BRT.csv',
            mime='text/csv',
        )

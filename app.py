import streamlit as st
import pandas as pd
import re
import difflib
import google.generativeai as genai
import requests
from bs4 import BeautifulSoup
import time

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="Butternut Box | BRT System", page_icon="🚚", layout="wide")
st.title("🚚 Hybrid BRT Logistics System")
st.markdown("ISTAT Validation + AI + Automated Delay Radar (Looker Export Proof).")

# --- AI CONFIGURATION (SIDEBAR) ---
st.sidebar.header("⚙️ AI Settings")
api_key = st.sidebar.text_input("Paste Gemini API Key:", type="password")

if api_key:
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        st.sidebar.success("AI connected! Features unlocked.")
    except Exception as e:
        st.sidebar.error("API connection error.")

# --- LOCAL DATABASE ---
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
    st.error("❌ Missing 'gi_comuni_cap.csv' file.")
    st.stop()

# --- MAIN VALIDATION ENGINE (OFFLINE) ---
def validate_address(street, city, zip_code, df_cap):
    issues = []
    status = "✅ OK"
    
    street = str(street)
    city = str(city).strip()
    zip_code = str(zip_code).strip()

    if len(zip_code) < 5 and zip_code != 'nan' and zip_code != '':
        zip_code = zip_code.zfill(5)
        issues.append(f"Added zeros: {zip_code}")

    if re.search(r"[éàòìùÉÀÒÌÙ’‘`]", street) or re.search(r"[’‘`]", city):
        street = re.sub(r'[éÉ]', 'e', street)
        street = re.sub(r'[àÀ]', 'a', street)
        street = re.sub(r'[òÒ]', 'o', street)
        street = re.sub(r'[ìÌ]', 'i', street)
        street = re.sub(r'[ùÙ]', 'u', street)
        street = re.sub(r"[’‘`]", "'", street)
        city = re.sub(r"[’‘`]", "'", city)
        issues.append("Fixed accents/apostrophes")

    clean_city = re.sub(r'\s*\([A-Za-z]{2}\)', '', city)
    clean_city = re.sub(r'\s+[A-Za-z]{2}$', '', clean_city).strip() 
    clean_city = clean_city.split('/')[0].strip()

    if 'cap' in df_cap.columns and 'denominazione_ita' in df_cap.columns:
        matching_rows = df_cap[df_cap['cap'] == zip_code]
        if matching_rows.empty:
            status = "❌ Needs fixing"
            issues.append(f"CRITICAL: CAP {zip_code} does not exist.")
        else:
            official_cities = matching_rows['denominazione_ita'].str.lower().tolist()
            matches = difflib.get_close_matches(clean_city.lower(), official_cities, n=1, cutoff=0.75)
            if not matches:
                status = "❌ Needs fixing"
                suggested_city = matching_rows.iloc[0]['denominazione_ita'].title()
                issues.append(f"ERROR: City '{city}' doesn't match {zip_code}. Should be: {suggested_city}")
    return status, " | ".join(issues)

# --- BRT STATUS SCRAPER ---
def check_brt_status(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        page_text = soup.get_text().lower()
        
        if "consegnata" in page_text: return "✅ Delivered (Consegnata)"
        elif "in consegna" in page_text: return "🚚 Out for delivery (In consegna)"
        elif "rifiutata" in page_text or "respinta" in page_text: return "❌ Rejected by customer"
        elif "indirizzo errato" in page_text or "manca" in page_text or "errato" in page_text: return "❌ Bad address"
        elif "lasciato avviso" in page_text or "assente" in page_text: return "⚠️ Customer not home (Awizo)"
        elif "giacenza" in page_text: return "📦 Stuck at depot (Giacenza)"
        else: return "⚠️ Manual check required"
    except:
        return "❌ Connection error"

# --- SMART COLUMN DETECTOR (ROBUST VERSION) ---
def load_robust_csv(uploaded_file, required_columns):
    try:
        uploaded_file.seek(0)
        df_temp = pd.read_csv(uploaded_file, header=None, sep=None, engine='python') 
        
        header_idx = None
        req_lower = [req.lower() for req in required_columns]
        
        for idx, row in df_temp.head(30).iterrows():
            row_str = " ".join([str(val).lower() for val in row.values])
            if all(req in row_str for req in req_lower):
                header_idx = idx
                break
                
        if header_idx is not None:
            uploaded_file.seek(0)
            return pd.read_csv(uploaded_file, header=header_idx, sep=None, engine='python')
        return None
    except Exception as e:
        return None

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📁 Bulk Validation", "🔍 AI Support", "📡 BRT Delay Radar"])

# --- TAB 1: BULK VALIDATION ---
with tab1:
    uploaded_file = st.file_uploader("Upload CSV file with addresses", type=["csv"], key="csv_upload")
    if uploaded_file:
        df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
        if st.button("🚀 Run Validation", type="primary"):
            results_status, results_fixes = [], []
            for index, row in df.iterrows():
                status, fixes = validate_address(row.get('Address 1', row.get('Address', '')), row.get('City', row.get('Delivery Area', '')), row.get('Postcode', ''), df_cap)
                results_status.append(status)
                results_fixes.append(fixes)
            df['System Status'] = results_status
            df['Report'] = results_fixes
            st.success("✅ Data ready!")
            st.dataframe(df[df['System Status'] != "✅ OK"] if not df[df['System Status'] != "✅ OK"].empty else df)
            st.download_button("📥 Download file", df.to_csv(index=False).encode('utf-8'), 'Ready_BRT.csv', 'text/csv')

# --- TAB 2: SUPPORT / AI ---
with tab2:
    st.markdown("### 🕵️‍♂️ Customer Support Tool")
    col1, col2, col3 = st.columns(3)
    with col1: man_street = st.text_input("Street")
    with col2: man_city = st.text_input("City")
    with col3: man_zip = st.text_input("Zip Code")
        
    if st.button("🔍 Validate for nShift"):
        if man_city and man_zip:
            status, fixes = validate_address(man_street, man_city, man_zip, df_cap)
            st.markdown("---")
            if status == "✅ OK":
                st.success(f"**Status:** {status}")
                if fixes: st.info(f"**Auto-correction:** {fixes}")
            else:
                st.error("REJECTED by nShift")
                st.warning(f"**Error:** {fixes}")
                
                if api_key:
                    if st.button("🛠️ AI: Fix Address"):
                        with st.spinner("AI is analyzing..."):
                            response = model.generate_content(f'Reconstruct the incorrect address. Separate Street, City, and Zip Code. Address: "{man_street} {man_city} {man_zip}". Return ONLY JSON: {{"Street": "", "City": "", "Zip": ""}}')
                            st.code(response.text.replace('```json', '').replace('```', '').strip(), language='json')
        else:
            st.error("⚠️ Please provide at least City and Zip Code.")

# --- TAB 3: BRT DELAY RADAR ---
with tab3:
    st.markdown("### 📡 Delay Radar (Format-proof)")
    st.markdown("Upload Looker/BRT CSV report. The system will find the correct columns regardless of the file format.")
    
    details_file = st.file_uploader("Upload Looker/BRT CSV report", type=["csv"], key="details_upload")
    
    if details_file:
        df_details = load_robust_csv(details_file, ['Tracking URL', 'Soc Link'])
            
        if df_details is not None and not df_details.empty:
            
            status_col = [col for col in df_details.columns if 'status' in col.lower()]
            if status_col:
                df_pending = df_details[df_details[status_col[0]].astype(str).str.lower() != 'delivered'].copy()
            else:
                df_pending = df_details.copy()
                
            url_col = [col for col in df_pending.columns if 'tracking url' in col.lower()][0]
            soc_col = [col for col in df_pending.columns if 'soc link' in col.lower()][0]
            
            df_pending = df_pending.dropna(subset=[url_col])
            df_pending = df_pending[df_pending[url_col].astype(str).str.contains('http')]
            
            st.info(f"🔎 File cleaned! Headers found and {len(df_pending)} packages isolated for checking.")
            
            if st.button("🚀 Scan BRT Statuses", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                real_statuses = []
                total = len(df_pending)
                
                for i, row in enumerate(df_pending.iterrows()):
                    url = str(row[1][url_col])
                    brt_status = check_brt_status(url)
                    real_statuses.append(brt_status)
                    
                    progress_bar.progress((i + 1) / total)
                    status_text.text(f"Scanning: {i + 1} / {total}")
                    time.sleep(0.5) 
                
                df_pending['Real BRT Status'] = real_statuses
                df_critical = df_pending[~df_pending['Real BRT Status'].str.contains("Delivered", na=False)]
                
                st.success("✅ Scan complete!")
                st.markdown("### 🚨 Required Actions (Delays & Issues):")
                
                df_display = df_critical[['Real BRT Status', url_col, soc_col]]
                st.data_editor(
                    df_display,
                    column_config={
                        url_col: st.column_config.LinkColumn("BRT Link"),
                        soc_col: st.column_config.LinkColumn("CRM Profile")
                    },
                    hide_index=True,
                    use_container_width=True
                )
                
                st.download_button(
                    label="📥 Download issues list",
                    data=df_critical.to_csv(index=False).encode('utf-8'),
                    file_name='Critical_BRT_Report.csv',
                    mime='text/csv'
                )
        else:
            st.error("❌ Critical Error: The script could not find the 'Tracking URL' or 'Soc Link' columns in this file. Make sure the Looker export contains them.")

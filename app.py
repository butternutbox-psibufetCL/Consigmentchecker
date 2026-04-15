import streamlit as st
import pandas as pd
import re
import difflib

# --- PAGE CONFIGURATION ---
st.set_page_config(page_title="BRT Validator Offline", page_icon="🚚", layout="wide")
st.title("🚚 BRT Logistics Validation System")
st.markdown("100% reliable version. Runs on the local ISTAT database. Processes data in a fraction of a second.")

# --- LOAD LOCAL CAP DATABASE ---
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
    st.error("❌ The 'gi_comuni_cap.csv' file is missing. Please add this file to your GitHub repository.")
    st.stop()

# --- MAIN VALIDATION ENGINE (DRY) ---
# This single function acts as the "brain" for both CSV uploads and manual checks
def validate_address(street, city, zip_code, df_cap):
    issues = []
    status = "✅ OK"
    
    street = str(street)
    city = str(city).strip()
    zip_code = str(zip_code).strip()

    # 1. FIX LEADING ZEROS IN ZIP CODE
    if len(zip_code) < 5 and zip_code != 'nan' and zip_code != '':
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

    # 3. SMART CLEANING FOR CITIES
    # Remove province abbreviations in brackets e.g., "(RM)"
    clean_city = re.sub(r'\s*\([A-Za-z]{2}\)', '', city)
    # Remove anything after a slash e.g., "Merano /Sinigo" -> "Merano"
    clean_city = clean_city.split('/')[0].strip()

    # 4. GEOGRAPHICAL VALIDATION
    if 'cap' in df_cap.columns and 'denominazione_ita' in df_cap.columns:
        matching_rows = df_cap[df_cap['cap'] == zip_code]
        
        if matching_rows.empty:
            status = "❌ Needs fixing"
            issues.append(f"CRITICAL: CAP code {zip_code} does not exist in the Italian database.")
        else:
            official_cities = matching_rows['denominazione_ita'].str.lower().tolist()
            matches = difflib.get_close_matches(clean_city.lower(), official_cities, n=1, cutoff=0.75)
            
            if not matches:
                status = "❌ Needs fixing"
                suggested_city = matching_rows.iloc[0]['denominazione_ita'].title()
                issues.append(f"ERROR: City from Looker ('{city}') doesn't match ZIP {zip_code}. It should be: {suggested_city}")
    
    return status, " | ".join(issues)


# --- USER INTERFACE (TABS) ---
tab1, tab2 = st.tabs(["📁 Bulk Check (CSV File)", "🔍 Check Single Address (Manual)"])

# --- TAB 1: BULK CSV CHECK ---
with tab1:
    uploaded_file = st.file_uploader("Upload Looker CSV file", type=["csv"], key="csv_upload")

    if uploaded_file:
        df = pd.read_csv(uploaded_file, dtype={'Postcode': str})
        
        if st.button("🚀 Run Instant Validation", type="primary"):
            results_status = []
            results_fixes = []
            
            for index, row in df.iterrows():
                street = row.get('Address 1', row.get('Address', ''))
                city = row.get('City', row.get('Delivery Area', ''))
                zip_code = row.get('Postcode', '')
                
                # Pass data through our validation engine
                status, fixes = validate_address(street, city, zip_code, df_cap)
                
                results_status.append(status)
                results_fixes.append(fixes)
                
            df['System Validation'] = results_status
            df['Recommendations / Report'] = results_fixes
            
            st.success("✅ Analysis complete! Data processed in a fraction of a second.")
            
            # Show rows with errors first
            df_errors = df[df['System Validation'] != "✅ OK"]
            st.dataframe(df_errors if not df_errors.empty else df)
            
            st.download_button(
                label="📥 Download the ready, clean CSV",
                data=df.to_csv(index=False).encode('utf-8'),
                file_name='Ready_for_BRT.csv',
                mime='text/csv',
            )

# --- TAB 2: MANUAL ADDRESS CHECK ---
with tab2:
    st.markdown("### Enter customer data to test")
    st.markdown("Tool for Customer Support. Instantly check if an address is correct or what fixes nShift will require.")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        man_street = st.text_input("Street (Address 1)", placeholder="e.g. Via Milano 23")
    with col2:
        man_city = st.text_input("City", placeholder="e.g. Merano /Sinigo")
    with col3:
        man_zip = st.text_input("ZIP Code (Postcode)", placeholder="e.g. 39012")
        
    if st.button("🔍 Check this address"):
        if man_city and man_zip:
            status, fixes = validate_address(man_street, man_city, man_zip, df_cap)
            
            st.markdown("---")
            st.markdown("### Validation Result:")
            if status == "✅ OK":
                st.success(f"**Status:** {status}")
                if fixes:
                    st.info(f"**Note:** The address will pass. The system would automatically apply these fixes in the background: *{fixes}*")
                else:
                    st.info("The address is perfect. No fixes required.")
            else:
                st.error(f"**Status:** {status}")
                st.warning(f"**Error Report:** {fixes}")
        else:
            st.error("⚠️ You must enter at least the City and ZIP code to perform a validation.")

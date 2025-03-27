# Created By: Bryon Tidwell
# Modified On: 3-27-2025

import streamlit as st
import pandas as pd
import requests
import io
import time
import os
import zipfile
import datetime

# --- User Greeting ---
st.set_page_config(page_title="GTIN Validator", layout="centered")
st.title("Welcome To Bryon's GTIN Validator & GS1 Licensee Info Tool")

if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if not st.session_state.user_name:
    name_input = st.text_input("Please enter your name to begin:")
    if not name_input:
        st.stop()
    st.session_state.user_name = name_input.strip()

st.success(f"Hello, {st.session_state.user_name}!")

# --- File Upload ---
uploaded_files = st.file_uploader(
    "Upload one or more Excel or CSV files with a 'GTIN' column",
    type=["xlsx", "csv"],
    accept_multiple_files=True
)

# --- Constants ---
API_URL = "https://api.gs1us.org/product/v7/Products/v7/GetProductsByGTIN"
HEADERS = {
    "Content-Type": "application/json-patch+json",
    "Cache-Control": "no-cache",
    "ApiKey": "4e3546a495a84751ab6ebb822738836d"
}
COLUMNS_OF_INTEREST = ['gtin', 'gs1Licence.licenseeName', 'gs1Licence.licenceKey', 'gs1Licence.licenseeGLN', 'validationErrors']

# --- Utilities ---
def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def post_with_retry(url, headers, data, max_retries=5):
    for attempt in range(max_retries):
        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 503:
                time.sleep(2 ** attempt)
                continue
            return response
        except requests.exceptions.RequestException:
            time.sleep(2 ** attempt)
    return None

def log_usage(user, file_count):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{timestamp},{user},{file_count}\n"
    with open("usage_log.csv", "a") as log:
        log.write(entry)

# --- Main Logic ---
if uploaded_files:
    all_data = []
    individual_results = {}

    total_files = len(uploaded_files)
    file_counter = 0

    for uploaded_file in uploaded_files:
        file_counter += 1
        st.markdown(f"### 🔄 Processing file {file_counter} of {total_files}: `{uploaded_file.name}`")

        filename, ext = os.path.splitext(uploaded_file.name)
        ext = ext.lower()

        try:
            df = pd.read_csv(uploaded_file, dtype=str) if ext == ".csv" else pd.read_excel(uploaded_file, dtype=str)
        except Exception as e:
            st.warning(f"Could not read `{uploaded_file.name}`: {e}")
            continue

        # Normalize column headers
        normalized_cols = {col.lower(): col for col in df.columns}
        if 'gtin' not in normalized_cols:
            st.warning(f"No 'GTIN' column in `{uploaded_file.name}`. Skipping.")
            continue

        gtin_col = normalized_cols['gtin']
        gtins = df[gtin_col].dropna().astype(str).tolist()
        if not gtins:
            st.warning(f"No GTINs found in `{uploaded_file.name}`. Skipping.")
            continue

        progress = st.progress(0)
        status_text = st.empty()
        results_df = []

        for i, chunk in enumerate(chunk_list(gtins, 10)):
            response = post_with_retry(API_URL, HEADERS, list(chunk))
            if response and response.status_code == 200:
                data = response.json()
                if 'products' in data:
                    products_data = pd.json_normalize(data['products'])
                    for col in COLUMNS_OF_INTEREST:
                        if col not in products_data.columns:
                            products_data[col] = pd.NA
                    results_df.append(products_data[COLUMNS_OF_INTEREST])

            percent = ((i + 1) * 10 / len(gtins)) * 100
            progress.progress(min((i + 1) / max(1, len(gtins) / 10), 1.0))
            status_text.text(f"Processed {(i+1)*10} of {len(gtins)} GTINs ({percent:.2f}%)")

        if results_df:
            final_result = pd.concat(results_df, ignore_index=True)
            all_data.append(final_result)
            individual_results[uploaded_file.name] = final_result
        else:
            st.warning(f"No valid results in `{uploaded_file.name}`.")

    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        st.session_state.final_df = combined_df
        st.session_state.individual_results = individual_results
        log_usage(st.session_state.user_name, len(uploaded_files))
        st.success("✅ All files processed. Ready for download.")
    else:
        st.error("❌ No data was processed.")

# --- Download Section ---
if "final_df" in st.session_state and "individual_results" in st.session_state:
    st.subheader("📥 Download Results")

    # Combined
    out_combined = io.BytesIO()
    st.session_state.final_df.to_excel(out_combined, index=False)
    out_combined.seek(0)
    st.download_button(
        label="Download Combined Results",
        data=out_combined,
        file_name="Combined_GTIN_Results.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    # Individuals
    for fname, df in st.session_state.individual_results.items():
        out_indiv = io.BytesIO()
        df.to_excel(out_indiv, index=False)
        out_indiv.seek(0)
        clean_name = os.path.splitext(fname)[0]
        st.download_button(
            label=f"Download {clean_name}_results.xlsx",
            data=out_indiv,
            file_name=f"{clean_name}_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    # ZIP download
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for fname, df in st.session_state.individual_results.items():
            clean_name = os.path.splitext(fname)[0]
            tmp = io.BytesIO()
            df.to_excel(tmp, index=False)
            tmp.seek(0)
            zipf.writestr(f"{clean_name}_results.xlsx", tmp.read())
    zip_buffer.seek(0)

    st.download_button(
        label="Download All Individual Results (ZIP)",
        data=zip_buffer,
        file_name="All_GTIN_Results.zip",
        mime="application/zip"
    )

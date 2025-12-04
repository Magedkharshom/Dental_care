import streamlit as st
import pandas as pd
import plotly.express as px
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from scipy.stats import chi2_contingency

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Dental Analysis Pro", layout="wide")
st.markdown("""
<style>
    .stat-box {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 8px;
        border-left: 5px solid #ff4b4b;
        margin-bottom: 10px;
    }
    .stat-value { font-size: 24px; font-weight: bold; color: #31333F; }
    .stat-label { font-size: 14px; color: #666; }
    .good-p { border-left-color: #2ecc71 !important; } /* Green border for significant */
    .bad-p { border-left-color: #e74c3c !important; } /* Red border for not significant */
</style>
""", unsafe_allow_html=True)

# --- 2. DATA LOADING ---
def load_data():
    try:
        df = pd.read_csv('children_survey_cleaned.csv')
    except:
        st.error("🚨 Critical Error: 'children_survey_cleaned.csv' not found.")
        st.stop()
    
    # Clean Gender
    df['Sesso'] = df['Sesso'].astype(str).str.upper().str.strip()
    
    # Target Setup
    df['Has_Cavity_Numeric'] = df['Ha carie?'].apply(lambda x: 1 if x == 1.0 else 0)
    df['Cavity_Status'] = df['Ha carie?'].map({1.0: 'Has Cavities', 2.0: 'Healthy', 3.0: 'Unknown'})
    
    # Mappings
    simple_map = {1.0: 'Yes', 2.0: 'No', 3.0: 'Other'}
    df['Sweets_Label'] = df['Mangi spesso caramelle\n e cioccolatini?'].map(simple_map).fillna('Other')
    df['Soda_Label'] = df['Bevi spesso bibite?'].map(simple_map).fillna('Other')
    
    # Dentist (2=Visited, 1=Never)
    dentist_map = {1.0: 'Never Visited', 2.0: 'Visited', 3.0: "Don't Remember"}
    df['Dentist_Label'] = df['Sei mai stato/a dal dentista?'].map(dentist_map).fillna("Don't Remember")
    
    return df

df = load_data()

# --- 3. STATISTICAL ENGINE ---
def calculate_stats(data, col_name, group_a, group_b):
    # Filter for head-to-head comparison
    subset = data[data[col_name].isin([group_a, group_b])]
    
    if subset.empty: return 1.0, 0.0, 0.0, 0.0
    
    # P-Value (Chi-Square)
    ct = pd.crosstab(subset[col_name], subset['Ha carie?'])
    try:
        chi2, p, dof, expected = chi2_contingency(ct)
    except:
        p = 1.0
        
    # Relative Risk
    rate_a = subset[subset[col_name] == group_a]['Has_Cavity_Numeric'].mean()
    rate_b = subset[subset[col_name] == group_b]['Has_Cavity_Numeric'].mean()
    
    risk_ratio = rate_a / rate_b if rate_b > 0 else 0
    
    return p, risk_ratio, rate_a, rate_b

# --- 4. SIDEBAR ---
with st.sidebar:
    st.header("🔍 Analysis Filters")
    genders = sorted(df['Sesso'].unique())
    sel_gender = st.multiselect("Gender", genders, default=genders)
    min_a, max_a = int(df['Età'].min()), int(df['Età'].max())
    sel_age = st.slider("Age Range", min_a, max_a, (min_a, max_a))

df_filtered = df[
    (df['Sesso'].isin(sel_gender)) & 
    (df['Età'] >= sel_age[0]) & 
    (df['Età'] <= sel_age[1])
]

# --- 5. DASHBOARD ---
st.title("🦷 Scientific Dental Analysis")
st.markdown("### Evidence-Based Risk Factors")

# Top Metrics
total = len(df_filtered)
rate = df_filtered['Has_Cavity_Numeric'].mean() * 100
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sample Size", total)
c2.metric("Cavity Prevalence", f"{rate:.1f}%")
c3.metric("Dentist Visits", len(df_filtered[df_filtered['Dentist_Label']=='Visited']))
c4.metric("High Sugar Intake", len(df_filtered[df_filtered['Sweets_Label']=='Yes']))

st.divider()

# --- 6. CHART & STATS RENDERER ---
def render_section(title, col_name, group_yes, group_no, valid_cats):
    st.subheader(title)
    
    # Calculate Stats
    p, rr, r1, r2 = calculate_stats(df_filtered, col_name, group_yes, group_no)
    is_sig = p < 0.05
    border_class = "good-p" if is_sig else "bad-p"
    
    col_chart, col_stats = st.columns([2, 1])
    
    with col_chart:
        chart_data = df_filtered[df_filtered[col_name].isin(valid_cats)]
        grouped = chart_data.groupby([col_name, 'Cavity_Status']).size().reset_index(name='Count')
        
        fig = px.bar(
            grouped, x=col_name, y='Count', color='Cavity_Status',
            text='Count',
            color_discrete_map={'Has Cavities': '#d32f2f', 'Healthy': '#388e3c', 'Unknown': '#9e9e9e'},
            category_orders={col_name: valid_cats}
        )
        fig.update_layout(xaxis_title=None, height=350)
        st.plotly_chart(fig, use_container_width=True)

    with col_stats:
        # The Stats Box
        st.markdown(f"""
        <div class="stat-box {border_class}">
            <div class="stat-label">P-Value (Significance)</div>
            <div class="stat-value">{p:.4f}</div>
            <div>{'✅ Significant' if is_sig else '❌ Not Significant'}</div>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown(f"**Comparative Risk:**")
        st.write(f"• **{group_yes}:** {r1*100:.1f}% have cavities")
        st.write(f"• **{group_no}:** {r2*100:.1f}% have cavities")
        
        if is_sig:
            st.info(f"**Interpretation:** Children in the '{group_yes}' group are **{rr:.1f}x** more likely to have cavities. This is a statistically significant finding.")
        else:
            st.warning(f"**Interpretation:** The difference is not statistically significant (P > 0.05). This may be due to the smaller sample size in your current filter.")

# 1. SWEETS
render_section("🍭 Impact of Sweets", "Sweets_Label", "Yes", "No", ['Yes', 'No', 'Other'])
st.divider()

# 2. SODA
render_section("🥤 Impact of Soda", "Soda_Label", "Yes", "No", ['Yes', 'No', 'Other'])
st.divider()

# 3. DENTIST
render_section("🏥 Impact of Dentist Visits", "Dentist_Label", "Visited", "Never Visited", ['Visited', 'Never Visited', "Don't Remember"])
st.caption("🚨 **Paradox Note:** A significant result here usually indicates 'Reactive Care'—children visiting the dentist because they already have pain.")

st.divider()

# --- 7. QUALITATIVE ---
st.subheader("🗣️ Patient Voices (Qualitative)")
complainers = df_filtered.dropna(subset=['Se non ti piacciono, perché?'])

if not complainers.empty:
    n_total = len(complainers)
    n_bad = complainers['Has_Cavity_Numeric'].sum()
    st.write(f"**{n_total} children** gave specific complaints. **{n_bad} ({n_bad/n_total*100:.1f}%)** of them have confirmed cavities.")
    st.dataframe(
        complainers[['Se non ti piacciono, perché?', 'Cavity_Status']].rename(columns={'Se non ti piacciono, perché?': 'Complaint'}),
        use_container_width=True
    )
else:
    st.info("No text responses available.")
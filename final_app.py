import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re
from scipy.stats import chi2_contingency

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Dental Health Report", layout="wide")

# PROFESSIONAL REPORT STYLING
st.markdown("""
<style>
    /* Main Layout */
    .main-header { font-size: 36px; font-weight: 800; color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 20px; margin-bottom: 30px; }
    .section-header { font-size: 26px; font-weight: 700; color: #34495e; margin-top: 40px; margin-bottom: 15px; border-left: 5px solid #e67e22; padding-left: 15px; }
    
    /* Metric Boxes */
    .stat-card { background: #ffffff; padding: 20px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); border-top: 5px solid #bdc3c7; text-align: center; }
    .stat-val { font-size: 32px; font-weight: bold; color: #2c3e50; }
    .stat-lbl { font-size: 14px; color: #7f8c8d; text-transform: uppercase; letter-spacing: 1px; font-weight: 600; }
    
    /* Color coding for metrics */
    .border-red { border-top-color: #e74c3c; }   /* Decay */
    .border-purple { border-top-color: #9b59b6; } /* Roots */
    .border-green { border-top-color: #2ecc71; }  /* Sealants */
    .border-blue { border-top-color: #3498db; }   /* Fillings */
    
    /* Text Boxes */
    .insight-box { background-color: #e8f6f3; border-left: 5px solid #1abc9c; padding: 20px; border-radius: 5px; color: #2c3e50; font-size: 16px; line-height: 1.6; margin-bottom: 20px; }
    .warning-box { background-color: #fdedec; border-left: 5px solid #e74c3c; padding: 20px; border-radius: 5px; color: #c0392b; font-size: 16px; line-height: 1.6; margin-bottom: 20px; }
    .info-text { font-size: 16px; color: #555; line-height: 1.6; margin-bottom: 15px; }
</style>
""", unsafe_allow_html=True)

# --- 2. DATA ENGINE ---
@st.cache_data
def load_data():
    try:
        survey = pd.read_csv('children_survey_cleaned.csv')
        excel_file = 'Schede Metro - Anonime - aggiornato 8.07.25 (1).xlsx'
        xl = pd.ExcelFile(excel_file)
        target_sheet = next((s for s in xl.sheet_names if "Formula" in s), None)
        if not target_sheet: st.stop()
        
        # Header Search
        df_preview = pd.read_excel(excel_file, sheet_name=target_sheet, header=None, nrows=15)
        header_idx = -1
        for idx, row in df_preview.iterrows():
            if 'Età' in row.astype(str).values or 'Codice' in row.astype(str).values:
                header_idx = idx
                break
        if header_idx == -1: st.stop()
            
        clinical = pd.read_excel(excel_file, sheet_name=target_sheet, header=header_idx)
        return survey, clinical
    except Exception as e:
        st.error(f"Error loading files: {e}")
        st.stop()

survey_raw, clinical_raw = load_data()

# --- 3. MEDICAL DICTIONARY ---
# Maps ISO codes to human-readable names for the narrative text
ISO_MAP = {
    '5.5': 'Upper Right 2nd Baby Molar', '6.5': 'Upper Left 2nd Baby Molar',
    '7.5': 'Lower Left 2nd Baby Molar', '8.5': 'Lower Right 2nd Baby Molar',
    '5.4': 'Upper Right 1st Baby Molar', '6.4': 'Upper Left 1st Baby Molar',
    '7.4': 'Lower Left 1st Baby Molar', '8.4': 'Lower Right 1st Baby Molar',
    '1.6': 'Upper Right 1st Perm Molar', '2.6': 'Upper Left 1st Perm Molar',
    '3.6': 'Lower Left 1st Perm Molar', '4.6': 'Lower Right 1st Perm Molar'
}

# --- 4. PARSING LOGIC ---
def process_data(survey_df, clinical_df):
    # Survey Clean
    survey_df['Sesso'] = survey_df['Sesso'].astype(str).str.upper().str.strip()
    survey_df['Has_Cavity'] = survey_df['Ha carie?'].apply(lambda x: 1 if x == 1.0 else 0)
    
    map_yn = {1.0: 'Yes', 2.0: 'No', 3.0: 'Other'}
    map_dent = {1.0: 'Never Visited', 2.0: 'Visited', 3.0: "Don't Remember"}
    
    survey_df['Sweets'] = survey_df['Mangi spesso caramelle\n e cioccolatini?'].map(map_yn).fillna('Other')
    survey_df['Soda'] = survey_df['Bevi spesso bibite?'].map(map_yn).fillna('Other')
    survey_df['Dentist'] = survey_df['Sei mai stato/a dal dentista?'].map(map_dent).fillna("Don't Remember")

    # Column Identification
    try: start = clinical_df.columns.get_loc('Età') + 1
    except: 
        clinical_df.columns = clinical_df.columns.str.strip()
        start = clinical_df.columns.get_loc('Età') + 1
    
    cols = clinical_df.columns.tolist()
    end = len(cols)
    for marker in ['Incompetenza', 'ATM', 'Note']:
        matches = [i for i, c in enumerate(cols) if marker in str(c)]
        if matches: end = matches[0]; break
    tooth_cols = clinical_df.columns[start:end]

    # Parsing Loop
    damage_records = []
    child_summary = []

    for _, row in clinical_df.iterrows():
        codice = row['Codice']
        stats = {
            'Codice': codice, 
            'Total_Decay': 0, 'Total_Roots': 0, 'Total_Filled': 0, 'Total_Sealants': 0, 'Total_White': 0,
            'Baby_Decay': 0, 'Baby_Roots': 0, 'Baby_Filled': 0, 'Baby_Sealants': 0,
            'Adult_Decay': 0, 'Adult_Roots': 0, 'Adult_Filled': 0, 'Adult_Sealants': 0
        }
        
        for col_name in tooth_cols:
            raw_val = str(row[col_name]).upper().strip()
            if raw_val in ['NAN', '-', 'M', 'NONE']: continue
            
            parts = re.split(r'[ +]+', raw_val)
            for part in parts:
                condition = 'Healthy'
                if 'RADICE' in part or 'RAD' in part: condition = 'Root Residue (Severe)'
                elif 'D' in part: condition = 'Active Decay'
                elif 'F' in part: condition = 'Filled'
                elif 'S' in part: condition = 'Sealant'
                elif 'W' in part: condition = 'White Spot'
                
                if condition == 'Healthy': continue 
                
                is_baby = 'L' in part
                is_adult = 'P' in part
                
                tooth_num = col_name
                if '-' in col_name:
                    options = [x.strip() for x in col_name.split('-')]
                    if is_baby: tooth_num = next((x for x in options if x[0] in ['5','6','7','8']), col_name)
                    elif is_adult: tooth_num = next((x for x in options if x[0] in ['1','2','3','4']), col_name)
                
                # Counters
                if condition == 'Root Residue (Severe)': stats['Total_Roots'] += 1
                if condition == 'Active Decay': stats['Total_Decay'] += 1
                if condition == 'Filled': stats['Total_Filled'] += 1
                if condition == 'Sealant': stats['Total_Sealants'] += 1
                if condition == 'White Spot': stats['Total_White'] += 1
                
                if is_baby:
                    if condition == 'Active Decay': stats['Baby_Decay'] += 1
                    if condition == 'Root Residue (Severe)': stats['Baby_Roots'] += 1
                    if condition == 'Filled': stats['Baby_Filled'] += 1
                    if condition == 'Sealant': stats['Baby_Sealants'] += 1
                if is_adult:
                    if condition == 'Active Decay': stats['Adult_Decay'] += 1
                    if condition == 'Root Residue (Severe)': stats['Adult_Roots'] += 1
                    if condition == 'Filled': stats['Adult_Filled'] += 1
                    if condition == 'Sealant': stats['Adult_Sealants'] += 1
                
                damage_records.append({
                    'Codice': codice,
                    'Tooth_Number': tooth_num,
                    'Tooth_Type': 'Baby (Deciduous)' if is_baby else 'Adult (Permanent)',
                    'Condition': condition
                })

        child_summary.append(stats)

    merged_survey = pd.merge(survey_df, pd.DataFrame(child_summary), on='Codice', how='left').fillna(0)
    
    if damage_records:
        merged_detailed = pd.merge(pd.DataFrame(damage_records), survey_df[['Codice', 'Sweets', 'Soda', 'Dentist']], on='Codice', how='left')
    else:
        merged_detailed = pd.DataFrame()
        
    return merged_survey, merged_detailed

df_main, df_teeth = process_data(survey_raw, clinical_raw)

# --- 5. STATS ENGINE ---
def calculate_p_value(df, group_col, target_col='Has_Cavity'):
    try:
        contingency = pd.crosstab(df[group_col], df[target_col])
        _, p, _, _ = chi2_contingency(contingency)
        return p
    except: return 1.0

# --- 6. FILTER SIDEBAR ---
with st.sidebar:
    st.image("https://img.icons8.com/color/96/000000/dental-braces.png", width=80)
    st.title("Study Filters")
    genders = sorted(df_main['Sesso'].unique())
    sel_gender = st.multiselect("Gender", genders, default=genders)
    min_a, max_a = int(df_main['Età'].min()), int(df_main['Età'].max())
    sel_age = st.slider("Age", min_a, max_a, (min_a, max_a))
    
    st.info("ℹ️ **Note:** All charts update instantly based on these filters.")

df_filtered = df_main[
    (df_main['Sesso'].isin(sel_gender)) & 
    (df_main['Età'] >= sel_age[0]) & 
    (df_main['Età'] <= sel_age[1])
]
valid_ids = df_filtered['Codice'].unique()
teeth_filtered = df_teeth[df_teeth['Codice'].isin(valid_ids)]

# --- 7. DASHBOARD START ---
st.markdown("<div class='main-header'>🦷 Pediatric Dental Health Report</div>", unsafe_allow_html=True)

# SECTION 1: EXECUTIVE METRICS
st.markdown("<div class='section-header'>1. Executive Summary</div>", unsafe_allow_html=True)
st.markdown("""
<div class='info-text'>
This dashboard provides a comprehensive analysis of the clinical data. 
The metrics below represent the <b>total burden of disease</b> found in the selected group. 
Pay close attention to "Root Residues" as they represent the most severe form of neglect.
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(f"<div class='stat-card'><div class='stat-val'>{len(df_filtered)}</div><div class='stat-lbl'>Sample Size</div></div>", unsafe_allow_html=True)
c2.markdown(f"<div class='stat-card border-red'><div class='stat-val'>{df_filtered['Total_Decay'].sum():.0f}</div><div class='stat-lbl'>Active Decay</div></div>", unsafe_allow_html=True)
c3.markdown(f"<div class='stat-card border-purple'><div class='stat-val'>{df_filtered['Total_Roots'].sum():.0f}</div><div class='stat-lbl'>Root Residues</div></div>", unsafe_allow_html=True)
c4.markdown(f"<div class='stat-card border-blue'><div class='stat-val'>{df_filtered['Total_Filled'].sum():.0f}</div><div class='stat-lbl'>Past Fillings</div></div>", unsafe_allow_html=True)
c5.markdown(f"<div class='stat-card border-green'><div class='stat-val'>{df_filtered['Total_Sealants'].sum():.0f}</div><div class='stat-lbl'>Sealants (S)</div></div>", unsafe_allow_html=True)

# SECTION 2: BABY VS ADULT ANALYSIS
st.markdown("<div class='section-header'>2. Decay vs. Prevention (Baby vs Adult)</div>", unsafe_allow_html=True)
st.markdown("""
<div class='info-text'>
We separate <b>Baby Teeth (Deciduous)</b> from <b>Adult Teeth (Permanent)</b>. 
While Baby teeth fall out, decay here is a strong predictor of future problems. 
<b>Critical Warning:</b> Any damage in the "Adult Teeth" chart is permanent and irreversible.
</div>
""", unsafe_allow_html=True)
# 

#[Image of deciduous vs permanent dentition]


c_baby, c_adult = st.columns(2)

with c_baby:
    vals = [
        df_filtered['Baby_Decay'].sum() + df_filtered['Baby_Roots'].sum(),
        df_filtered['Baby_Filled'].sum(),
        df_filtered['Baby_Sealants'].sum()
    ]
    labs = ['Decay & Roots (Bad)', 'Fillings (Repaired)', 'Sealants (Prevention)']
    colors = ['#e74c3c', '#3498db', '#2ecc71']
    
    fig = go.Figure(data=[go.Pie(labels=labs, values=vals, hole=.5, marker_colors=colors)])
    fig.update_layout(title_text="<b>Baby Teeth (Deciduous)</b>", height=300, margin=dict(t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)

with c_adult:
    vals_a = [
        df_filtered['Adult_Decay'].sum() + df_filtered['Adult_Roots'].sum(),
        df_filtered['Adult_Filled'].sum(),
        df_filtered['Adult_Sealants'].sum()
    ]
    
    fig = go.Figure(data=[go.Pie(labels=labs, values=vals_a, hole=.5, marker_colors=colors)])
    fig.update_layout(title_text="<b>Adult Teeth (Permanent)</b>", height=300, margin=dict(t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)

# Automated Narrative for Section 2
adult_decay_count = df_filtered['Adult_Decay'].sum() + df_filtered['Adult_Roots'].sum()
sealant_count = df_filtered['Adult_Sealants'].sum()

if adult_decay_count > 0:
    st.markdown(f"""
    <div class='warning-box'>
    <b>⚠️ Clinical Alert:</b> We have detected <b>{adult_decay_count}</b> rotting Permanent (Adult) teeth. 
    In a cohort of this age (Mixed Dentition), the permanent teeth have only recently erupted. 
    Finding active decay this early indicates a high-risk oral environment.
    </div>
    """, unsafe_allow_html=True)

if sealant_count < (len(df_filtered) * 0.5): # Arbitrary threshold for narrative
    st.markdown(f"""
    <div class='insight-box'>
    <b>💡 Prevention Gap:</b> Only <b>{sealant_count}</b> adult teeth have Sealants (Sigillature). 
    Sealants are the #1 way to prevent cavities in the 6-year molars. 
    This suggests a massive opportunity to improve preventative care.
    </div>
    """, unsafe_allow_html=True)


# SECTION 3: HEATMAP
st.markdown("<div class='section-header'>3. Global Tooth Vulnerability Map</div>", unsafe_allow_html=True)
st.markdown("""
<div class='info-text'>
This chart identifies exactly <b>which teeth</b> are failing. We use the ISO 3950 Numbering System.
We are looking for the "6-Year Molars" (1.6, 2.6, 3.6, 4.6). If these bars are Red/Purple, it is a serious issue.
</div>
""", unsafe_allow_html=True)
# 

if not teeth_filtered.empty:
    heatmap_data = teeth_filtered.groupby(['Tooth_Number', 'Condition']).size().reset_index(name='Count')
    # Filter to top 20 most frequent teeth
    total_counts = heatmap_data.groupby('Tooth_Number')['Count'].sum().sort_values(ascending=False).head(20).index
    heatmap_data = heatmap_data[heatmap_data['Tooth_Number'].isin(total_counts)]
    
    fig = px.bar(
        heatmap_data, x='Tooth_Number', y='Count', color='Condition', 
        title="Top 20 Most Affected Teeth (Stacked History)",
        color_discrete_map={
            'Active Decay': '#e74c3c', 
            'Root Residue (Severe)': '#8e44ad',
            'Filled': '#3498db',
            'Sealant': '#2ecc71',
            'White Spot': '#f1c40f'
        },
        category_orders={'Tooth_Number': list(total_counts)}
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # Dynamic Tooth Explanation
    worst_tooth = total_counts[0]
    worst_tooth_name = ISO_MAP.get(worst_tooth, "Unknown Position")
    
    st.markdown(f"""
    <div class='insight-box'>
    <b>🔍 Automated Diagnosis:</b><br>
    The single most affected tooth in this group is <b>#{worst_tooth}</b> ({worst_tooth_name}).<br>
    This tooth has the highest combined total of Decay, Fillings, and Roots. Treatment plans should prioritize protecting this specific molar in younger children.
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("No clinical data available.")

# SECTION 4: RISK FACTORS
def render_risk_factor(col, title, g1, g2):
    st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
    
    # Calculate Logic
    p = calculate_p_value(df_filtered[df_filtered[col].isin([g1, g2])], col)
    sig_txt = "Significant" if p < 0.05 else "Not Significant"
    sig_color = "#27ae60" if p < 0.05 else "#95a5a6"
    
    st.markdown(f"**Statistical Verdict:** <span style='color:{sig_color}; font-weight:bold'>{sig_txt} (P={p:.4f})</span>", unsafe_allow_html=True)
    
    c_left, c_right = st.columns([1, 2])
    
    with c_left:
        # Prevalence Chart
        sub = df_filtered[df_filtered[col].isin([g1, g2])]
        rates = sub.groupby(col)['Has_Cavity'].mean().reset_index()
        rates['Pct'] = rates['Has_Cavity']*100
        fig = px.bar(rates, x=col, y='Pct', text=rates['Pct'].apply(lambda x: f"{x:.1f}%"), title="Cavity Prevalence (%)", color=col)
        fig.update_layout(showlegend=False, height=300)
        st.plotly_chart(fig, use_container_width=True)
        
    with c_right:
        # Full Clinical Breakdown (Including Sealants)
        breakdown = sub.groupby(col)[['Total_Decay', 'Total_Roots', 'Total_Sealants']].sum().reset_index()
        melted = breakdown.melt(id_vars=col, var_name='Type', value_name='Count')
        melted['Type'] = melted['Type'].map({'Total_Decay': 'Decay (Bad)', 'Total_Roots': 'Roots (Severe)', 'Total_Sealants': 'Sealants (Good)'})
        
        fig = px.bar(melted, x=col, y='Count', color='Type', barmode='group', 
                     title="Clinical Condition Count",
                     color_discrete_map={'Decay (Bad)': '#e74c3c', 'Roots (Severe)': '#8e44ad', 'Sealants (Good)': '#2ecc71'})
        fig.update_layout(height=300)
        st.plotly_chart(fig, use_container_width=True)
        
    # Interpretative Text
    if p < 0.05:
        st.markdown(f"""
        <div class='insight-box'>
        <b>Correlation Confirmed:</b> There is a statistically significant difference between these two groups. 
        This suggests that <b>{col}</b> is a genuine driver of dental health outcomes in this population.
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class='info-text'>
        <i>Note: The difference here is not statistically significant. This might be due to sample size or other confounding factors.</i>
        </div>
        """, unsafe_allow_html=True)

render_risk_factor('Sweets', "4. Sweets Consumption Analysis", 'Yes', 'No')
render_risk_factor('Soda', "5. Soft Drinks Analysis", 'Yes', 'No')
render_risk_factor('Dentist', "6. The Dentist Visit Paradox", 'Visited', 'Never Visited')

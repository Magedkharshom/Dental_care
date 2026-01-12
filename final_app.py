import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import re
from scipy.stats import chi2_contingency

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="Dental Clinical Masterpiece", layout="wide")
st.markdown("""
<style>
    .stat-box { background-color: #f8f9fa; padding: 15px; border-radius: 8px; border-left: 5px solid #3498db; }
    h3 { margin-top: 30px; border-bottom: 2px solid #eee; padding-bottom: 10px; }
    .metric-label { font-size: 14px; color: #555; }
    .metric-val { font-size: 26px; font-weight: bold; }
    .sig-green { color: #2ecc71; font-weight: bold; }
    .sig-red { color: #e74c3c; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# --- 2. ADVANCED DATA ENGINE ---
@st.cache_data
def load_data():
    try:
        survey = pd.read_csv('children_survey_cleaned.csv')
        excel_file = 'Schede Metro - Anonime - aggiornato 8.07.25 (1).xlsx'
        xl = pd.ExcelFile(excel_file)
        target_sheet = next((s for s in xl.sheet_names if "Formula" in s), None)
        if not target_sheet: st.stop()
        
        # Find Header
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
        st.error(f"Error: {e}")
        st.stop()

survey_raw, clinical_raw = load_data()

# --- 3. PARSING LOGIC (THE HEAVY LIFTING) ---
def process_full_data(survey_df, clinical_df):
    # A. CLEAN SURVEY
    survey_df['Sesso'] = survey_df['Sesso'].astype(str).str.upper().str.strip()
    survey_df['Has_Cavity'] = survey_df['Ha carie?'].apply(lambda x: 1 if x == 1.0 else 0)
    
    map_yn = {1.0: 'Yes', 2.0: 'No', 3.0: 'Other'}
    map_dent = {1.0: 'Never Visited', 2.0: 'Visited', 3.0: "Don't Remember"}
    
    survey_df['Sweets'] = survey_df['Mangi spesso caramelle\n e cioccolatini?'].map(map_yn).fillna('Other')
    survey_df['Soda'] = survey_df['Bevi spesso bibite?'].map(map_yn).fillna('Other')
    survey_df['Dentist'] = survey_df['Sei mai stato/a dal dentista?'].map(map_dent).fillna("Don't Remember")

    # B. IDENTIFY CLINICAL COLUMNS
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

    # C. DETAILED PARSING (PER TOOTH)
    # We create a "Long Format" dataset where every row is a Damaged Tooth
    damage_records = []
    child_summary = []

    for _, row in clinical_df.iterrows():
        codice = row['Codice']
        stats = {
            'Codice': codice, 
            'Total_Decay': 0, 'Total_Filled': 0, 'Total_White': 0, 'Total_Roots': 0, 'Total_Sealants': 0,
            'Baby_Affected': 0, 'Adult_Affected': 0,
            'Baby_Decay': 0, 'Adult_Decay': 0
        }
        
        for col_name in tooth_cols:
            raw_val = str(row[col_name]).upper().strip()
            if raw_val in ['NAN', '-', 'M', 'NONE']: continue
            
            # SPLIT COMPLEX CODES (e.g. "L/radice + P")
            parts = re.split(r'[ +]+', raw_val)
            
            for part in parts:
                condition = 'Healthy'
                
                # 1. IDENTIFY CONDITION (HIERARCHY)
                if 'RADICE' in part or 'RAD' in part: condition = 'Root Residue (Severe)'
                elif 'D' in part: condition = 'Active Decay'
                elif 'F' in part: condition = 'Filled'
                elif 'W' in part: condition = 'White Spot'
                elif 'S' in part: condition = 'Sealant'
                
                if condition == 'Healthy': continue 
                
                # 2. IDENTIFY TOOTH NUMBER & TYPE
                is_baby = 'L' in part
                is_adult = 'P' in part
                
                # Resolve Column Name to Specific Tooth Number (ISO)
                tooth_num = col_name
                if '-' in col_name:
                    options = [x.strip() for x in col_name.split('-')]
                    if is_baby:
                        tooth_num = next((x for x in options if x[0] in ['5','6','7','8']), col_name)
                    elif is_adult:
                        tooth_num = next((x for x in options if x[0] in ['1','2','3','4']), col_name)
                
                # 3. UPDATE STATS
                if condition == 'Root Residue (Severe)': stats['Total_Roots'] += 1
                if condition == 'Active Decay': stats['Total_Decay'] += 1
                if condition == 'Filled': stats['Total_Filled'] += 1
                if condition == 'White Spot': stats['Total_White'] += 1
                if condition == 'Sealant': stats['Total_Sealants'] += 1
                
                if is_baby: 
                    stats['Baby_Affected'] += 1
                    if condition in ['Active Decay', 'Root Residue (Severe)']: stats['Baby_Decay'] += 1
                if is_adult: 
                    stats['Adult_Affected'] += 1
                    if condition in ['Active Decay', 'Root Residue (Severe)']: stats['Adult_Decay'] += 1
                
                # 4. RECORD DETAILED ENTRY
                damage_records.append({
                    'Codice': codice,
                    'Tooth_Number': tooth_num,
                    'Tooth_Type': 'Baby (Deciduous)' if is_baby else 'Adult (Permanent)',
                    'Condition': condition
                })

        child_summary.append(stats)

    # D. MERGE
    summary_df = pd.DataFrame(child_summary)
    damage_df = pd.DataFrame(damage_records)
    
    merged_survey = pd.merge(survey_df, summary_df, on='Codice', how='left').fillna(0)
    
    if not damage_df.empty:
        merged_detailed = pd.merge(damage_df, survey_df[['Codice', 'Sweets', 'Soda', 'Dentist']], on='Codice', how='left')
    else:
        merged_detailed = pd.DataFrame()
        
    return merged_survey, merged_detailed

df_main, df_teeth = process_full_data(survey_raw, clinical_raw)

# --- 4. STATISTICAL ENGINE (Chi-Square) ---
def calculate_stats(df, group_col, target_col='Has_Cavity'):
    """Calculates P-value and textual interpretation."""
    contingency = pd.crosstab(df[group_col], df[target_col])
    try:
        chi2, p, dof, ex = chi2_contingency(contingency)
        return p
    except:
        return 1.0

# --- 5. SIDEBAR ---
with st.sidebar:
    st.header("🔍 Filters")
    genders = sorted(df_main['Sesso'].unique())
    sel_gender = st.multiselect("Gender", genders, default=genders)
    min_a, max_a = int(df_main['Età'].min()), int(df_main['Età'].max())
    sel_age = st.slider("Age", min_a, max_a, (min_a, max_a))

df_filtered = df_main[
    (df_main['Sesso'].isin(sel_gender)) & 
    (df_main['Età'] >= sel_age[0]) & 
    (df_main['Età'] <= sel_age[1])
]
valid_ids = df_filtered['Codice'].unique()
teeth_filtered = df_teeth[df_teeth['Codice'].isin(valid_ids)]

# --- 6. MAIN PAGE ---
st.title("🦷 Dental Clinical Masterpiece")
st.markdown("### Integrated Risk, Prevalence, and Clinical Pathology")

# GLOBAL METRICS
c1, c2, c3, c4, c5 = st.columns(5)
c1.markdown(f"<div class='stat-box'><div class='metric-val'>{len(df_filtered)}</div><div class='metric-label'>Children</div></div>", unsafe_allow_html=True)
c2.markdown(f"<div class='stat-box'><div class='metric-val' style='color:#e74c3c'>{df_filtered['Total_Decay'].sum():.0f}</div><div class='metric-label'>Active Decay</div></div>", unsafe_allow_html=True)
c3.markdown(f"<div class='stat-box'><div class='metric-val' style='color:#8e44ad'>{df_filtered['Total_Roots'].sum():.0f}</div><div class='metric-label'>Root Residues</div></div>", unsafe_allow_html=True)
c4.markdown(f"<div class='stat-box'><div class='metric-val' style='color:#f1c40f'>{df_filtered['Total_White'].sum():.0f}</div><div class='metric-label'>White Spots</div></div>", unsafe_allow_html=True)
c5.markdown(f"<div class='stat-box'><div class='metric-val' style='color:#2ecc71'>{df_filtered['Total_Sealants'].sum():.0f}</div><div class='metric-label'>Sealants</div></div>", unsafe_allow_html=True)

st.divider()

# --- 7. NEW SECTION: BABY VS ADULT TEETH BATTLE ---
st.subheader("👶 vs 🧑 The Deciduous/Permanent Split")
st.markdown("Comparing the burden of decay between Baby Teeth (Temporary) and Adult Teeth (Permanent).")

c_baby, c_adult = st.columns(2)

with c_baby:
    st.markdown("#### Baby Teeth (L)")
    b_decay = df_filtered['Baby_Decay'].sum()
    b_filled = df_filtered['Baby_Affected'].sum() - b_decay # Approx
    
    fig_b = go.Figure(data=[go.Pie(labels=['Active Decay', 'Other Damage'], values=[b_decay, b_filled], hole=.6, marker_colors=['#e67e22', '#f39c12'])])
    fig_b.update_layout(title_text=f"Total Baby Decay: {b_decay:.0f}", height=300)
    st.plotly_chart(fig_b, use_container_width=True)

with c_adult:
    st.markdown("#### Adult Teeth (P)")
    a_decay = df_filtered['Adult_Decay'].sum()
    a_filled = df_filtered['Adult_Affected'].sum() - a_decay
    
    fig_a = go.Figure(data=[go.Pie(labels=['Active Decay', 'Other Damage'], values=[a_decay, a_filled], hole=.6, marker_colors=['#2980b9', '#3498db'])])
    fig_a.update_layout(title_text=f"Total Adult Decay: {a_decay:.0f}", height=300)
    st.plotly_chart(fig_a, use_container_width=True)

st.info("**Insight:** If the Blue Ring (Adult) has a large 'Active Decay' section, it indicates permanent damage that will affect the child for life.")

st.divider()

# --- 8. GLOBAL TOOTH HEATMAP ---
st.subheader("🔥 Global Vulnerability Map")
st.markdown("Which specific teeth are rotting the most across the entire selected population? (Based on ISO Numbering)")


if not teeth_filtered.empty:
    tooth_counts = teeth_filtered[teeth_filtered['Condition'].isin(['Active Decay', 'Root Residue (Severe)'])]['Tooth_Number'].value_counts().reset_index()
    tooth_counts.columns = ['Tooth', 'Count']
    tooth_counts = tooth_counts.sort_values('Count', ascending=False).head(15)
    
    fig = px.bar(
        tooth_counts, x='Tooth', y='Count', color='Count',
        color_continuous_scale='Reds', text='Count',
        title="Top 15 Most Damaged Teeth (ISO Codes)"
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No damage data found for current filter.")

st.divider()

# --- 9. DEEP DIVE ENGINE (THE "HEAVY" PART) ---
def render_heavy_analysis(question_col, title, group_a, group_b):
    st.subheader(title)
    
    # Run Stats
    p_val = calculate_stats(df_filtered[df_filtered[question_col].isin([group_a, group_b])], question_col)
    sig_text = "Statistically Significant (P < 0.05)" if p_val < 0.05 else "Not Significant (P > 0.05)"
    sig_class = "sig-green" if p_val < 0.05 else "sig-red"
    
    st.markdown(f"**Statistical Verdict:** <span class='{sig_class}'>{sig_text}</span> (P={p_val:.4f})", unsafe_allow_html=True)
    
    col_left, col_right = st.columns([1, 2])
    
    # --- LEFT: PREVALENCE (The Percentage) ---
    with col_left:
        st.markdown("**1. Prevalence (%)**")
        subset = df_filtered[df_filtered[question_col].isin([group_a, group_b])]
        stats = subset.groupby(question_col)['Has_Cavity'].mean().reset_index()
        stats['Rate'] = stats['Has_Cavity'] * 100
        
        fig_prev = px.bar(
            stats, x=question_col, y='Rate', text=stats['Rate'].apply(lambda x: f"{x:.1f}%"),
            title="Cavity Rate", color=question_col,
            category_orders={question_col: [group_a, group_b]}
        )
        fig_prev.update_layout(showlegend=False, yaxis_range=[0,100], height=300)
        st.plotly_chart(fig_prev, use_container_width=True)

    # --- RIGHT: CLINICAL REALITY (Stacked Conditions) ---
    with col_right:
        st.markdown("**2. Clinical Reality (Total Count by Condition)**")
        # Sum specific columns
        cond_stats = subset.groupby(question_col)[['Total_Decay', 'Total_Roots', 'Total_Filled', 'Total_White', 'Total_Sealants']].sum().reset_index()
        melted = cond_stats.melt(id_vars=question_col, var_name='Condition', value_name='Count')
        
        melted['Condition'] = melted['Condition'].map({
            'Total_Decay': 'Active Decay (D)',
            'Total_Roots': 'Root Residue (Severe)',
            'Total_Filled': 'Filled (Past)',
            'Total_White': 'White Spot (Early)',
            'Total_Sealants': 'Sealants (Good)'
        })
        
        fig_clin = px.bar(
            melted, x=question_col, y='Count', color='Condition',
            title="Total Pathology Burden",
            barmode='stack', text='Count',
            color_discrete_map={
                'Active Decay (D)': '#e74c3c',       # Red
                'Root Residue (Severe)': '#8e44ad',  # Purple
                'Filled (Past)': '#3498db',          # Blue
                'White Spot (Early)': '#f1c40f',     # Yellow
                'Sealants (Good)': '#2ecc71'         # Green
            },
            category_orders={question_col: [group_a, group_b]}
        )
        fig_clin.update_layout(height=300)
        st.plotly_chart(fig_clin, use_container_width=True)

    # --- BOTTOM: TOOTH SPECIFICS (Heatmap Comparison) ---
    st.markdown("**3. Tooth Vulnerability (Which teeth are hitting them?)**")
    c_a, c_b = st.columns(2)
    
    def plot_tooth_dist(group_name, color):
        data = teeth_filtered[
            (teeth_filtered[question_col] == group_name) & 
            (teeth_filtered['Condition'].isin(['Active Decay', 'Root Residue (Severe)']))
        ]
        if data.empty: return None
        
        counts = data['Tooth_Number'].value_counts().reset_index().head(8)
        counts.columns = ['Tooth', 'Count']
        
        fig = px.bar(
            counts, x='Tooth', y='Count', title=f"Top Rotting Teeth in '{group_name}'",
            text='Count', color_discrete_sequence=[color]
        )
        fig.update_layout(height=250)
        return fig

    with c_a:
        fig = plot_tooth_dist(group_a, '#e74c3c') # Red for Yes
        if fig: st.plotly_chart(fig, use_container_width=True)
        else: st.caption("No data")
        
    with c_b:
        fig = plot_tooth_dist(group_b, '#2980b9') # Blue for No
        if fig: st.plotly_chart(fig, use_container_width=True)
        else: st.caption("No data")

    st.divider()

# --- RENDER SECTIONS ---
render_heavy_analysis('Sweets', "🍭 Analysis: Sweets Consumption", 'Yes', 'No')
render_heavy_analysis('Soda', "🥤 Analysis: Soda Consumption", 'Yes', 'No')
render_heavy_analysis('Dentist', "🏥 Analysis: Dentist History", 'Visited', 'Never Visited')

# --- 10. RAW DATA INSPECTOR ---
with st.expander("🕵️ Clinical Data Inspector"):
    st.dataframe(df_teeth.sort_values(['Codice', 'Condition']))

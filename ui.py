import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests

# -------------------------------------------------------------------
# CONFIG
# -------------------------------------------------------------------
API_URL = "http://127.0.0.1:8000/calculate"   # backend FastAPI

st.set_page_config(page_title="DIY Battery Designer", layout="wide")

if "df" not in st.session_state:
    st.session_state.df = None
if "highlight_index" not in st.session_state:
    st.session_state.highlight_index = None
if "raw_dara" not in st.session_state:
    st.session_state.raw_data = None

st.title("🔋 DIY Battery Designer – Streamlit UI")
st.write("Interface Python completa para gerar configurações de bateria usando o teu backend FastAPI.")

st.sidebar.header("📥 Inputs")

# -------------------------------------------------------------------
# SIDEBAR INPUTS
# -------------------------------------------------------------------
min_voltage = st.sidebar.number_input("Min Voltage (V)", value=397.0)
max_voltage = st.sidebar.number_input("Max Voltage (V)", value=403.0)
min_power = st.sidebar.number_input(
    "Min Continuous Power (W)", value=1000000.0)
min_energy = st.sidebar.number_input("Min Energy (Wh)", value=1000000.0)
max_weight = st.sidebar.number_input("Max Weight (kg)", value=6000000.0)
max_price = st.sidebar.number_input("Max Price (€)", value=1500000000.0)
max_width = st.sidebar.number_input("Max Width (mm)", value=300.0)
max_length = st.sidebar.number_input("Max Length (mm)", value=800.0)
max_height = st.sidebar.number_input("Max Height (mm)", value=250.0)
target_price = st.sidebar.number_input("Target Price (€)", value=0.0)
ambient_temp = st.sidebar.number_input("Ambient Temp (°C)", value=25)
debug = st.sidebar.checkbox("Debug mode", value=False)


def reset_highlight():
    st.session_state.highlight_index = None


generate = st.sidebar.button("🚀 Generate Design")


clear_cache = st.sidebar.button("🧹 Clear Cached Data")

if clear_cache:
    st.session_state.df = None
    st.session_state.highlight_index = None
    st.session_state.raw_data = None
# -------------------------------------------------------------------
# WHEN USER CLICKS GENERATE
# -------------------------------------------------------------------
if generate:
    st.subheader("⏳ Running calculation...")

    payload = {
        "min_voltage": min_voltage,
        "max_voltage": max_voltage,
        "min_continuous_power": min_power,
        "min_energy": min_energy,
        "max_weight": max_weight,
        "max_price": max_price,
        "max_width": max_width,
        "max_length": max_length,
        "max_height": max_height,
        "target_price": target_price,
        "ambient_temp": ambient_temp,
        "debug": debug,
    }

    try:
        r = requests.post(API_URL, json=payload)

        if r.status_code != 200:
            st.error(f"❌ Backend returned an error: {r.status_code}")
            st.code(r.text)
            st.stop()

        data = r.json()
        st.session_state.raw_data = data.get("results", [])

    except Exception as e:
        st.error("❌ Could not connect to backend.")
        st.exception(e)
        st.stop()

    results = data["results"]
    total = data["total"]

    # Criar DataFrame Base
    df = pd.DataFrame(data["plotResults"])

    # --- FEATURE ENGINEERING E LIMPEZA DE DADOS ---
    if not df.empty:

        # 1. Extrair Percentagens de Divisão (MultiChemistry)
        if "multiChemistry" in df.columns:
            def get_split_energy(x):
                try:
                    return x[0][1] * 100
                except:
                    return 0

            def get_split_power(x):
                try:
                    return x[0][2] * 100
                except:
                    return 0

            df["Split Energy (%)"] = df["multiChemistry"].apply(
                get_split_energy)
            df["Split Power (%)"] = df["multiChemistry"].apply(get_split_power)

            # Guardamos o multiChemistry como string para o hover do gráfico
            df["_multiChemStr"] = df["multiChemistry"].astype(str)

        # 2. Expandir Subpacks (APENAS OS CAMPOS QUE PEDISTE)
        if "subpacks" in df.columns:
            expanded_rows = []

            for _, row in df.iterrows():
                subpacks_list = row["subpacks"]
                row_data = {}

                if isinstance(subpacks_list, list):
                    for i, sp in enumerate(subpacks_list):
                        # Prefixo P1, P2 para Pack 1, Pack 2
                        prefix = f"P{i+1}"

                        # Extração Limpa: Apenas Modelo, Série e Paralelo
                        cell_data = sp.get("cell", {})
                        cell_model = cell_data.get(
                            "CellModelNo", "Unknown")  # <-- CellModelNo
                        # <-- Series
                        s_count = sp.get("series_cells", 0)
                        # <-- Parallel
                        p_count = sp.get("parallel_cells", 0)

                        price = sp.get("total_price", 0)

                        row_data[f"{prefix} Model"] = cell_model
                        row_data[f"{prefix} Series"] = s_count
                        row_data[f"{prefix} Parallel"] = p_count
                        row_data[f"{prefix} Price (€)"] = round(price, 2)

                expanded_rows.append(row_data)
            # Juntar as novas colunas ao DataFrame principal
            subpacks_df = pd.DataFrame(expanded_rows)
            df = pd.concat([df, subpacks_df], axis=1)

        # --- FEATURE ENGINEERING FINANCE ---
        if "financial_KPIs" in df.columns:
            expanded_financial = []

            for _, row in df.iterrows():
                fa = row["financial_KPIs"]
                if isinstance(fa, dict):
                    expanded_financial.append({
                        "CapEx (€)": fa.get("capex", 0),
                        "Opex Annual (€)": fa.get("opex_annual", 0),
                        "Cycles per Year": fa.get("cycles_per_year", 0),
                        "Revenue First Year (€)": fa.get("revenue_first_year", 0),
                        "Payback Years": fa.get("payback_years", 0),
                        "NPV (€)": fa.get("npv", 0),
                        "IRR (%)": fa.get("irr", 0) * 100 if fa.get("irr") is not None else None,
                        "Total Profit (€)": fa.get("total_profit_over_lifetime", 0)
                    })
                else:
                    expanded_financial.append({
                        "CapEx (€)": 0,
                        "Opex Annual (€)": 0,
                        "Cycles per Year": 0,
                        "Revenue First Year (€)": 0,
                        "Payback Years": 0,
                        "NPV (€)": 0,
                        "IRR (%)": 0,
                        "Total Profit (€)": 0
                    })

            # Remover colunas financeiras antigas se existirem
            # financial_cols = ["CapEx (€)", "Opex Annual (€)", "Cycles per Year",
            #                  "Revenue First Year (€)", "Payback Years", "NPV (€)", "IRR (%)", "Total Profit (€)"]
            # df = df.drop(
            #    columns=[c for c in financial_cols if c in df.columns])

            # financial_df = pd.DataFrame(expanded_financial)
            # d  f = pd.concat([df, financial_df], axis=1)

        # 3. Remover colunas complexas originais
        cols_to_drop = ["multiChemistry", "subpacks"]
        df = df.drop(columns=[c for c in cols_to_drop if c in df.columns])

        # 4. Reordenar Colunas (Prioridade ao que interessa)
        priority_cols = [
            "Split Energy (%)", "Split Power (%)", "total_price", "battery_energy", "continuous_power",
            "safety_score", "financial_analysis"
        ]
        # Agrupar colunas dos Packs (P1..., P2...)
        sp_cols = sorted([c for c in df.columns if c.startswith("P") and (
            c.endswith("Model") or c.endswith("Series") or c.endswith("Parallel") or c.endswith("Price (€)"))])

        # Resto das colunas
        other_cols = [
            c for c in df.columns if c not in priority_cols and c not in sp_cols and c != "_multiChemStr"]

        financial_cols = ["CapEx (€)", "Opex Annual (€)", "Cycles per Year",
                          "Revenue First Year (€)", "Payback Years", "NPV (€)", "IRR (%)", "Total Profit (€)"]

        final_order = sp_cols + [
            c for c in priority_cols if c in df.columns] + other_cols
        # Garante que só usamos colunas existentes e preenchemos zeros caso faltem
        final_order_existing = [c for c in final_order if c in df.columns]
        missing_cols = [c for c in final_order if c not in df.columns]
        for c in missing_cols:
            df[c] = 0  # ou np.nan se preferires

        df = df[final_order]  # agora todas as colunas existem

    st.session_state.df = df
    st.success(f"Encontradas **{total} configurações**")


# -------------------------------------------------------------------
# DASHBOARD
# -------------------------------------------------------------------

df = st.session_state.df

if df is None:
    st.warning("Clique em 'Generate Design' para criar resultados.")
    st.stop()

if df.empty:
    st.warning("⚠️ Nenhuma configuração encontrada para estes requisitos.")
    st.stop()

# Ratios
if "energy_density" not in df.columns:
    df["energy_density"] = df["battery_energy"] / df["battery_weight"]
if "price_per_kWh" not in df.columns:
    df["price_per_kWh"] = (
        df["total_price"] / (df["battery_energy"] * 1e-3*0.8*(df["durability_score"])*0.9)).round(3)

st.header("🏆 Best Configurations")

best = {
    "💰 Lowest Price": df.loc[df["total_price"].idxmin()],
    "🔋 Highest Energy": df.loc[df["battery_energy"].idxmax()],
    "⚡ Highest Energy Density": df.loc[df["energy_density"].idxmax()],
    "🏅 Best Value (€/Wh)": df.loc[df["price_per_kWh"].idxmin()],
    "🏋️ Lightest": df.loc[df["battery_weight"].idxmin()],
}

cols = st.columns(2)
for i, (title, row) in enumerate(best.items()):
    with cols[i % 2]:
        with st.expander(title, expanded=False):
            # Limpar dicionário para visualização JSON
            clean_row = {k: v for k, v in row.to_dict().items()
                         if k != "_multiChemStr"}
            st.json(clean_row)

# -------------------------------------------------------------------
# SCATTER PLOT EXPLORER
# -------------------------------------------------------------------
st.header("📈 Scatter Plot Explorer")

available_numeric_cols = [
    "battery_energy",
    "battery_weight",
    "energy_density",
    "total_price",
    "continuous_power",
    "price_per_kWh",
    "safety_score",
    "durability_score",
    "Split Energy (%)",
    "Split Power (%)"
]

valid_cols = [c for c in available_numeric_cols if c in df.columns]

c1, c2, c3, c4 = st.columns(4)

with c1:
    x_axis = st.selectbox("X Axis", valid_cols, index=0)

with c2:
    default_y = 2 if len(valid_cols) > 2 else 0
    if "total_price" in valid_cols:
        default_y = valid_cols.index("total_price")
    y_axis = st.selectbox("Y Axis", valid_cols, index=default_y)

with c3:
    color_options = ["durability_score", "total_price", "safety_score",
                     "Split Energy (%)", "energy_density", "price_per_kWh"]
    valid_color_options = [c for c in color_options if c in df.columns]

    color_col = st.selectbox(
        "Color Grade (Blue Scale)",
        valid_color_options,
        index=0,
        help="Quanto menor o valor, azul mais claro. Quanto maior, azul mais escuro."
    )

with c4:
    if st.button("✨ Highlight Best/First Config"):
        if not df.empty:
            # Índice 0 é a solução de custo mínimo da otimização
            st.session_state.highlight_index = df.index[0]
        else:
            st.session_state.highlight_index = None

highlight_single = st.checkbox(
    "Highlight One Chemistry Configurations (Red)",
    value=False,
    help="Destaca a vermelho as configurações Single Chemistry (100% Energia/Potência na mesma célula)."
)

if not df.empty:

    # Hover Info
    hover_cols = {
        "P1 Model": True,
        "P2 Model": True,
        "Split Energy (%)": True,
        "Split Power (%)": True,
        "battery_energy": True,
        "total_price": True,
        "energy_density": True,
        "continuous_power": True,
    }

    fig = px.scatter(
        df,
        x=x_axis,
        y=y_axis,
        color=color_col,
        # Escala Azul (Claro -> Escuro)
        color_continuous_scale=["#90CAF9", "#0D47A1"],
        hover_data=hover_cols,
        title=f"{y_axis} vs {x_axis}"
    )

    fig.update_traces(marker=dict(size=8, opacity=0.8))

    if st.session_state.highlight_index is not None and st.session_state.highlight_index in df.index:
        highlight_row = df.loc[[st.session_state.highlight_index]]

        show_legend = True
        if highlight_single:
            is_single_chem = (highlight_row["Split Energy (%)"].iloc[0] >= 99.9) or (
                highlight_row["Split Energy (%)"].iloc[0] <= 0.1)
            if is_single_chem:
                show_legend = False

        fig.add_trace(
            go.Scatter(
                x=highlight_row[x_axis],
                y=highlight_row[y_axis],
                mode='markers',
                marker=dict(
                    color='orange',  # Cor de destaque
                    size=14,  # Tamanho maior
                    symbol='star',  # Símbolo de estrela
                    line=dict(width=3, color='DarkOrange')
                ),
                name='Best/First Configuration (Otimizada)',
                showlegend=show_legend
            )
        )

    if highlight_single and "Split Energy (%)" in df.columns:
        mask = (df["Split Energy (%)"] >= 99.9) & (
            df["Split Power (%)"] >= 99.9) | (df["Split Energy (%)"] <= 0.1) & (
            df["Split Power (%)"] <= 0.1)
        highlight_df = df[mask]

        if not highlight_df.empty:
            fig.add_trace(
                go.Scatter(
                    x=highlight_df[x_axis],
                    y=highlight_df[y_axis],
                    mode='markers',
                    marker=dict(
                        color='red',
                        size=10,
                        symbol='circle',
                        line=dict(width=2, color='DarkRed')
                    ),
                    name='Single Chemistry (100%)',
                    text=highlight_df["_multiChemStr"] if "_multiChemStr" in highlight_df.columns else None
                )
            )

    st.plotly_chart(fig, use_container_width=True)
    df = df.drop(columns=['_index'], errors='ignore')

# -------------------------------------------------------------------
# FULL TABLE
# -------------------------------------------------------------------
st.header("📋 All Configurations")

# Remove a coluna auxiliar do gráfico para a tabela ficar limpa
display_df = df.drop(columns=["_multiChemStr"], errors="ignore")
st.dataframe(display_df)

# -------------------------------------------------------------------
# EXPORT DATA
# -------------------------------------------------------------------
st.divider()
st.header("💾 Export Data")

csv_data = display_df.to_csv(index=False).encode('utf-8')

st.download_button(
    label="⬇️ Download Results as CSV",
    data=csv_data,
    file_name='battery_configurations.csv',
    mime='text/csv',
)


# -------------------------------------------------------------------
# DEBUG: RAW DATA SECTION (NOVA SECÇÃO ADICIONADA)
# -------------------------------------------------------------------
st.divider()
st.header("🔍 Debug: Raw Data (Optimized Configuration)")
st.write("Esta secção mostra exatamente como a primeira configuração (normalmente a otimizada) foi recebida do backend.")

if st.session_state.raw_data and len(st.session_state.raw_data) > 0:
    st.json(st.session_state.raw_data[0])
else:
    st.info("⚠️ Nenhuma informação disponível. Gera um design primeiro.")

import json
import os
from typing import Union
import pandas as pd


def _resolve_path(path: str) -> str:
    """
    Resolve a file path with sensible fallbacks:
    1) If it's absolute and exists, return it.
    2) If it exists relative to current working directory, return it.
    3) Otherwise, try relative to this module's directory.
    4) If still not found and input is a basename, try module_dir/basename.
    Raises FileNotFoundError with hints if not found.
    """
    # Absolute path case
    if os.path.isabs(path) and os.path.exists(path):
        return path

    # Exists relative to CWD
    if os.path.exists(path):
        return path

    module_dir = os.path.dirname(__file__)
    candidate = os.path.join(module_dir, path)
    if os.path.exists(candidate):
        return candidate

    # Try basename in module directory
    base = os.path.basename(path)
    candidate2 = os.path.join(module_dir, base)
    if os.path.exists(candidate2):
        return candidate2

    raise FileNotFoundError(
        f"File not found: '{path}'. Tried CWD '{os.getcwd()}', module dir '{module_dir}'."
    )


def _interval_from_cumulative(series: pd.Series) -> pd.Series:
    """
    Compute interval energy from a cumulative series.
    - Returns NaN outside valid runs (where source is NaN)
    - Sets first value of each valid run to 0
    - Negative diffs (counter resets/glitches) are set to NaN
    - Extremely large positive diffs are treated as outliers and set to NaN
    """
    s = pd.to_numeric(series, errors="coerce")
    mask = s.notna()
    diff = s.diff()
    # mark start of each valid run; avoid FutureWarning by using fill_value
    start_mask = mask & ~mask.shift(1, fill_value=False)
    diff.loc[start_mask] = 0
    # keep only where source is valid
    diff = diff.where(mask)
    # remove negative intervals (counter reset or bad data)
    diff = diff.where(diff >= 0)
    # remove extreme outliers (e.g., last spike) using high quantile threshold
    pos = diff.dropna()
    if not pos.empty:
        q = pos.quantile(0.999)
        if pd.notna(q) and q > 0:
            diff = diff.where(diff <= q)
    return diff


def load_energy_data_household(csv_path: str) -> pd.DataFrame:
    """
    Load energy data from a CSV file.

    Parameters:
        csv_path (str): Path to the CSV file.

    Returns:
        pd.DataFrame: DataFrame containing processed energy data.
    """
    csv_path = _resolve_path(csv_path)
    df = pd.read_csv(csv_path)

    # Ensure timestamps are parsed and set CET/CEST as index
    if "utc_timestamp" in df.columns:
        df["utc_timestamp"] = pd.to_datetime(df["utc_timestamp"], utc=True)  # type: ignore[assignment]
        df["cet_cest_timestamp"] = df["utc_timestamp"].dt.tz_convert("Europe/Berlin")
    elif "cet_cest_timestamp" in df.columns:
        ts = pd.to_datetime(df["cet_cest_timestamp"], errors="coerce")
        # Localize if naive
        if getattr(ts.dtype, "tz", None) is None:
            ts = ts.dt.tz_localize("Europe/Berlin")
        df["cet_cest_timestamp"] = ts  # type: ignore[assignment]

    # Drop rows with missing timestamps, sort, and set index
    if "cet_cest_timestamp" in df.columns:
        df = df.dropna(subset=["cet_cest_timestamp"]).sort_values("cet_cest_timestamp")
        # Keep the column while also using it as index for convenient plotting
        df = df.set_index("cet_cest_timestamp", drop=False)
        # Remove duplicate indices (keep first occurrence)
        df = df[~df.index.duplicated(keep="first")]

    # Coerce expected numeric columns (remove non-numeric like ",,,")
    numeric_cols = [
        "DE_KN_industrial2_pv",
        "DE_KN_industrial2_grid_import",
        "DE_KN_industrial2_storage_charge",
        "DE_KN_industrial2_storage_decharge",
    ]
    existing_numeric = [c for c in numeric_cols if c in df.columns]
    for c in existing_numeric:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    # Drop rows where all key numeric columns are NaN
    if existing_numeric:
        df = df.dropna(subset=existing_numeric, how="all")

    # Differences yield interval energies (kWh per sampling period) with resets/outliers handled
    if "DE_KN_industrial2_pv" in df.columns:
        df["E_pv_interval_kwh"] = _interval_from_cumulative(df["DE_KN_industrial2_pv"])
    if "DE_KN_industrial2_grid_import" in df.columns:
        df["E_grid_interval_kwh"] = _interval_from_cumulative(df["DE_KN_industrial2_grid_import"])
    if "DE_KN_industrial2_storage_charge" in df.columns:
        df["E_batt_charge_kwh"] = _interval_from_cumulative(df["DE_KN_industrial2_storage_charge"])
    if "DE_KN_industrial2_storage_decharge" in df.columns:
        df["E_batt_discharge_kwh"] = _interval_from_cumulative(df["DE_KN_industrial2_storage_decharge"])

    df["E_load_interval_kwh"] = (
        df["E_batt_discharge_kwh"].fillna(0)
        + df["E_grid_interval_kwh"].fillna(0)
        + df["E_pv_interval_kwh"].fillna(0)
        - df["E_batt_charge_kwh"].fillna(0)
    )

    return df


def load_energy_data_fast_regulation(csv_path: str) -> pd.DataFrame:
    """
    Load energy data from a CSV file.

    Parameters:
        csv_path (str): Path to the CSV file.

    Returns:
        pd.DataFrame: DataFrame containing processed energy data.
    """
    csv_path = _resolve_path(csv_path)
    df = pd.read_csv(csv_path)

    # O CSV não tem cabeçalho, então define nomes manualmente
    df.columns = ["seconds", "c_rate_normalize"]
    df["seconds"] = pd.to_numeric(df["seconds"], errors="coerce")
    df["c_rate_normalize"] = pd.to_numeric(df["c_rate_normalize"], errors="coerce")
    # Remove linhas com valores ausentes nessas colunas
    df = df.dropna(subset=["seconds", "c_rate_normalize"])

    # Acrescenta segundos com 0 de c_rate_normalize, se necessário
    # Ou seja, assume que nos segundos não carregados o c_rate_normalize é 0
    all_seconds = pd.Series(range(int(df["seconds"].min()), int(df["seconds"].max()) + 1))
    df = df.set_index("seconds").reindex(all_seconds, fill_value=0).reset_index()
    df = df.rename(columns={"index": "seconds"})
    
    # Ordena por tempo, se necessário
    #df = df.sort_values("seconds")
    #df = df.set_index("seconds", drop=False)

    return df


def load_cell_data(json_path: str) -> pd.DataFrame:
    """
    Load cell data from JSON and compute derived parameters.

    Parameters:
        json_path (str): Path to the JSON file with cell specs.

    Returns:
        pd.DataFrame: DataFrame of cells with derived columns.
    """
    json_path = _resolve_path(json_path)
    with open(json_path, "r") as f:
        data = json.load(f)

    cells_df = pd.DataFrame(data)

    # Derived metrics
    cells_df["Capacity_Ah"] = cells_df["Capacity"] / 1000
    cells_df["E_cell_Wh"] = cells_df["Capacity_Ah"] * cells_df["NominalVoltage"]
    cells_df["I_dis_max"] = (
        cells_df["Capacity_Ah"] * cells_df["PeakDischargeRate"]
    )
    cells_df["I_ch_max"] = cells_df["Capacity_Ah"] * cells_df["PeakDischargeRate"]
    cells_df["P_dis_cell_max"] = cells_df["NominalVoltage"] * cells_df["I_dis_max"]
    cells_df["P_ch_cell_max"] = cells_df["NominalVoltage"] * cells_df["I_ch_max"]

    return cells_df


__all__ = ["load_energy_data", "load_cell_data"]

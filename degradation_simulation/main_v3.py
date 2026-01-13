import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

def get_battery_parameters(n_cells: dict, cells_df: pd.DataFrame) -> pd.DataFrame:
    # Copiar para não alterar o DataFrame original
    bat_df = cells_df.copy()

    # Inicializar colunas
    bat_df["n_cells"] = 0
    bat_df["P_dis_max"] = 0.0
    bat_df["P_ch_max"] = 0.0
    bat_df["E_total_Wh"] = 0.0

    for idx, row in bat_df.iterrows():
        chem = row["Composition"]
        n = n_cells.get(chem, 0)
        
        bat_df.at[idx, "n_cells"] = n
        bat_df.at[idx, "P_dis_max"] = row["P_dis_cell_max"] * n
        bat_df.at[idx, "P_ch_max"] = row["P_ch_cell_max"] * n
        bat_df.at[idx, "E_total_Wh"] = row["E_cell_Wh"] * n

    return bat_df


def dispatch_battery(df, bat_df, dt, eff=0.9):
    """
    Dispatch battery with round-trip efficiency (eff).
    eff: charging/discharging efficiency (0 < eff <= 1), default 0.9 (90%)
    Optimized for cases where P_load_inst_kW and P_pv_inst_kW are often zero.
    """
    n = len(df)
    P_batt = {row["Composition"]: np.zeros(n) for _, row in bat_df.iterrows()}
    SOC_hist = {row["Composition"]: np.zeros(n) for _, row in bat_df.iterrows()}
    SOC = {
        row["Composition"]: 0.75 * row["E_total_Wh"] / 1000
        for _, row in bat_df.iterrows()
    }
    P_grid = np.zeros(n)

    # Pre-extract arrays for speed
    P_pv = df["P_pv_inst_kW"].values
    P_load = df["P_load_inst_kW"].values

    for t in range(n):
        # Skip if both are zero (no action needed)
        if P_pv[t] == 0 and P_load[t] == 0:
            for chem in SOC_hist:
                SOC_hist[chem][t] = SOC[chem]
                P_batt[chem][t] = 0.0
            P_grid[t] = 0.0
            continue

        surplus = P_pv[t] - P_load[t]

        for _, row in bat_df.iterrows():
            chem = row["Composition"]
            if row["n_cells"] == 0:
                continue

            P_ch_max = row["P_ch_max"] / 1000     # kW
            P_dis_max = row["P_dis_max"] / 1000   # kW
            E_tot = row["E_total_Wh"] / 1000      # kWh

            if surplus > 0:
                # Charging: account for efficiency loss (need more input to store 1 kWh)
                P = min(surplus, P_ch_max, (E_tot - SOC[chem]) / (dt * eff))
                SOC[chem] += P * dt * eff
            else:
                # Discharging: only a fraction of battery energy is delivered to load
                P = max(surplus, -P_dis_max, -SOC[chem] * eff / dt)
                SOC[chem] += P * dt / eff if eff > 0 else 0

            SOC_hist[chem][t] = SOC[chem]
            P_batt[chem][t] = P
            surplus -= P

        P_grid[t] = surplus

    for chem, soc in SOC_hist.items():
        if bat_df.loc[bat_df["Composition"] == chem, "n_cells"].values[0] > 0:
            max_soc = np.max(soc) / (bat_df.loc[bat_df["Composition"] == chem, "E_total_Wh"].values[0] / 1000) * 100
            min_soc = np.min(soc) / (bat_df.loc[bat_df["Composition"] == chem, "E_total_Wh"].values[0] / 1000) * 100
            print(f"{chem}: MAX SOC(%) = {max_soc:.2f}%, MIN SOC(%) = {min_soc:.2f}%")

    P_batt_all = np.sum(list(P_batt.values()), axis=0)
    return P_batt, P_grid, P_batt_all, SOC_hist


def block_E1_DoD_Crate(SoC, P_batt, dt, E_nom_Wh):
    """
    Implementa o Block E1 do artigo (Motapon et al.)
    input:
    SoC      : array de SoC [0–1]
    IBatt    : array de corrente da bateria [A]
    T        : passo de tempo [s]
    C_nom_Ah : capacidade nominal [Ah]
    output:
    DoD      : array de DoD dos ciclos identificados [0–1]  
    Idis_ave : array de C-rate médio de descarga dos ciclos identificados [1/h]
    Ich_ave  : array de C-rate médio de carga dos ciclos identificados [1/h]
    """


    DoD = []
    C_rate_dis = []
    C_rate_ch = []
    Init_Cycle = []
    End_Cycle = []

    # Inicialização (Step 1)
    a = 0

    DoD.append(1 - SoC[0])
    # delta soc entre SOC
    dsoc = SoC[1] - SoC[0]
    C0 = abs(P_batt[0] * 1000) / E_nom_Wh  # C-rate inicial [1/h]
    if dsoc < 0:  # descarga
        C_rate_dis.append(C0)
        C_rate_ch.append(0.0)
    else:              # carga
        C_rate_ch.append(C0)
        C_rate_dis.append(0.0)

    Init_Cycle.append(0)
    End_Cycle.append(0)

    dsoc_prev = dsoc
    change_detected = False

    for k in range(0, len(SoC)-1):
        dsoc = SoC[k] - SoC[k + 1]

        if dsoc == 0:
            continue

        # Detecta transição (charge ↔ discharge), guarda ate aqui
        if np.sign(dsoc) != np.sign(dsoc_prev):
            change_detected = True

        # Detecta transição (charge ↔ discharge), guarda ate aqui
        if np.sign(dsoc) == np.sign(dsoc_prev) and dsoc_prev != -1 and change_detected or k == len(SoC)-1:
            change_detected = False

            b = k 

            # DoD do ciclo
            soc_segment = SoC[a:b+1]
            DoD_cycle = np.max(soc_segment) - np.min(soc_segment)
            DoD.append(DoD_cycle)

            # C-rate médio do ciclo
            P_batt_segment = P_batt[a:b+1]
            C_rate_mean_ch = np.mean(np.abs(P_batt_segment[P_batt_segment > 0]) * 1000 / E_nom_Wh)
            C_rate_mean_dis = np.mean(np.abs(P_batt_segment[P_batt_segment < 0]) * 1000 / E_nom_Wh)

            if np.sum(np.abs(P_batt[a+1:b+1])>6) > 0:
                print(f"Debug: Cycle from {a} to {b}, P_batt: Max: {np.max(P_batt[a+1:b+1])} Min: {np.min(P_batt[a+1:b+1])}, C_rate_mean_ch: {C_rate_mean_ch}, C_rate_mean_dis: {C_rate_mean_dis}, Cycle: {len(DoD)-1}")

           
            C_rate_ch.append(C_rate_mean_ch)
            C_rate_dis.append(C_rate_mean_dis)
           
            Init_Cycle.append(a)
            End_Cycle.append(b)

            a = b 

            dsoc_prev = dsoc



    print(f"Total cycles identified: {len(DoD)}")
    print(f"DoD samples: Min = {np.min(DoD):.10f}, Max = {np.max(DoD):.4f}, Mean = {np.mean(DoD):.4f}")
    print(f"DoD=0 indexes: {[i for i, x in enumerate(DoD) if x < 0.001]}")

    return np.array(DoD), np.array(C_rate_dis), np.array(C_rate_ch), np.array(Init_Cycle), np.array(End_Cycle)


def block_E2_max_cycles(DoD, C_rate_dis, C_rate_ch, Ta, bat_df, params):
    """
    Implementa o Block E2 – Maximum Number of Cycles (Motapon et al.)

    DoD       : array de DoD por ciclo [0–1]
    Idis_ave  : C-rate médio de descarga por ciclo
    Ich_ave   : C-rate médio de carga por ciclo
    Ta        : temperatura ambiente por ciclo [K]

    params : dicionário com parâmetros do modelo
    """

    # Parâmetros
    DoD_ref  = bat_df["DoD_cycles"]
    C_rate_dis_ref = bat_df["MaxContinuousDischargeRate"]
    C_rate_ch_ref  = bat_df["MaxContinuousChargeRate"]
    T_ref    = 298.15  # 25 °C em Kelvin
    Nc_ref   = bat_df["Cycles"]

    xi    = params["xi"]
    gamma1 = params["gamma1"]
    gamma2 = params["gamma2"]
    psi    = params["psi"]

    Nc = []
    theta_all = []

    for n in range(len(DoD)):

        # Evita valores inválidos
        if DoD[n] < 0:
            Nc.append(np.inf)
            theta_all.append(0.0)
            print(f"Warning: DoD < 0 at cycle {n}, setting Nc to infinity.")
            continue
        elif DoD[n] == 0:
            Nc.append(np.inf)
            theta_all.append(0.0)
            print(f"Warning: DoD = 0 at cycle {n}, C_rate_dis = {C_rate_dis[n]}, C_rate_ch = {C_rate_ch[n]}, setting Nc to infinity.")
            continue

        # Stress factors
        theta_DoD = (DoD[n] / DoD_ref) ** (1.0 / xi)

        theta_C_rate_dis = (
            (C_rate_dis[n] / C_rate_dis_ref) ** (1.0 / gamma1)
            if C_rate_dis[n] > 0 else 1.0
        )

        theta_C_rate_ch = (
            (C_rate_ch[n] / C_rate_ch_ref) ** (1.0 / gamma2)
            if C_rate_ch[n] > 0 else 1.0
        )

        theta_T = np.exp(
            -psi * (1.0 / Ta[n] - 1.0 / T_ref)
        )

        # Stress combinado
        theta = theta_DoD * theta_C_rate_dis * theta_C_rate_ch * theta_T
        theta_all.append(theta)

        # Número máximo de ciclos
        Nc.append(Nc_ref / theta)

    return np.array(Nc), np.array(theta_all)



def compute_damage_paper(P_batt, bat_df, dt, SOC_P_hist, df):
    NC = {chem: 0.0 for chem in P_batt.keys()}
    NC_total = {}

    # Parâmetros do modelo para cada química
    params = {
        "LFP": {
            "xi": 0.8, # stress exponent for the DoD
            "gamma1": 0.8, # stress exponent for the discharge C-rate
            "gamma2": 2.34, # stress exponent for the charge C-rate
            "psi": 3700 # Arrhenius temperature factor [K]
        },
        "NMC": {
            "xi": 0.59,
            "gamma1": 0.62,
            "gamma2": 1.09,
            "psi": 3660
        },
        "LTO": {
            "xi": 1,
            "gamma1": 1,
            "gamma2": 1,
            "psi": 5000
        },
        "Sodium": {
            "xi": 3.0,
            "gamma1": 1,
            "gamma2": 1.2,
            "psi": 3500
        }
    }

    for idx, row in bat_df.iterrows():
        chem = row["Composition"]

        if row["n_cells"] == 0:
            NC[chem] = np.nan
            NC_total[chem] = np.nan
            continue

        print(f"Calculating damage for chemistry: {chem}, len of P_batt: {len(P_batt[chem])}, len of SOC_P_hist: {len(SOC_P_hist[chem])}")

        DoD, C_rate_dis, C_rate_ch, Init_Cycle, End_Cycle = block_E1_DoD_Crate(
            (SOC_P_hist[chem] / 100),
            P_batt[chem],
            dt * 3600,
            row["E_total_Wh"]
        )
 
        """  n_cycle = 120
        print(f"Init_Cycle: {Init_Cycle[n_cycle]}, End_Cycle: {End_Cycle[n_cycle]}")  # Exemplo de impressão dos valores de Init_Cycle e End_Cycle
        print(f'Init_Cycle Date: {df["cet_cest_timestamp"].iloc[Init_Cycle[n_cycle]]}, End_Cycle Date: {df["cet_cest_timestamp"].iloc[End_Cycle[n_cycle]]}')  # Datas correspondentes
        print(f"DoD[{n_cycle}]: {DoD[n_cycle]}, C_rate_dis[{n_cycle}]: {C_rate_dis[n_cycle]}, C_rate_ch[{n_cycle}]: {C_rate_ch[n_cycle]}")  # Valores correspondentes
        print(f"SoC at Init_Cycle[{n_cycle}]: {SOC_P_hist[chem][Init_Cycle[n_cycle]]}, SoC at End_Cycle[{n_cycle}]: {SOC_P_hist[chem][End_Cycle[n_cycle]]}")  # Valores de SoC correspondentes  """ 

        # Add 10 clycles with ref values at the end to validate against reference
        for _ in range(10):
            DoD = np.append(DoD, row["DoD_cycles"])
            C_rate_dis = np.append(C_rate_dis, row["MaxContinuousDischargeRate"])
            C_rate_ch = np.append(C_rate_ch, row["MaxContinuousChargeRate"])

        
        Nc_chem, theta_all = block_E2_max_cycles(
            DoD,
            C_rate_dis,
            C_rate_ch,
            np.full(len(DoD), 298.15),  # Temperatura constante
            row,
            params[chem]
        )

        fig, axs = plt.subplots(2, 1, figsize=(10, 5), sharex=True)
        axs[0].plot(Nc_chem, label=f"Nc por ciclo - {chem}")
        axs[0].set_ylabel("Nc")
        axs[0].set_title(f"Número máximo de ciclos (Nc) por ciclo - {chem}")
        axs[0].legend()
        axs[0].set_yscale('log')
        axs[1].plot(DoD, label=f"DoD por ciclo - {chem}")
        axs[1].plot(C_rate_dis, label=f"C-rate descarga por ciclo - {chem}")
        axs[1].plot(C_rate_ch, label=f"C-rate carga por ciclo - {chem}")
        axs[1].set_xlabel("Cycle index")
        axs[1].set_ylabel("Value")
        axs[1].set_title(f"DoD e C-rates por ciclo - {chem}")
        axs[1].legend()
        plt.tight_layout()
        plt.show()

        NC[chem] = Nc_chem
        NC_total[chem] = np.sum(1.0 / Nc_chem)

    return NC, NC_total
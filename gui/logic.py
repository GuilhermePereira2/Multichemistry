import numpy as np
import math
from scipy.optimize import linprog
# Removemos o lru_cache para evitar erros de "unhashable type: dict"
from typing import List, Dict, Optional, Tuple, Any
from models import Requirements, CellData, Fuse, Relay, Cable, Bms, Shunt, Configuration, Dimensions, SafetyAssessment

# --- CONSTANTES DE SEGURANÇA E FÍSICA ---
HEIGHT_MARGIN_MM = 30.0
SPACING_THICKNESS_MM = 0.2
SPACING_WIDTH_MM = 0.2
CABLE_TEMP_MAX = 100
RHO_E_COPPER = 1.68e-8
DEFAULT_CABLE_LENGTH_M = 2
THERMAL_RESISTANCE = 0.5
MIN_DELTA_T = 1.0
FUSE_CURRENT_FACTOR = 1.5
RELAY_VOLTAGE_FACTOR = 1.1
RELAY_CURRENT_FACTOR = 2.0
PRICE_BUY = 0.12
PRICE_SELL = 0.25
CYCLES_PER_YEAR = 300
ROUND_TRIP_EFF = 0.85
YEARS = 15
INTEREST_RATE = 0.06
OPEX_RATE = 0.02
DEGRADATION_PER_YEAR = 0.02
EPSILON = 0.8
LAMBDA1 = 0.8
LAMBDA2 = 2.34
PHI = 3.7e3

# --- FUNÇÕES AUXILIARES ---


def get_integer_factors(n: int) -> List[Tuple[int, int]]:
    """Retorna pares de fatores (x, y) tal que x * y = n. Otimizado."""
    factors = []
    for i in range(1, int(math.isqrt(n)) + 1):
        if n % i == 0:
            factors.append((i, n // i))
    return factors

# Helper para converter objetos Pydantic em Dicionários


def to_dict(item):
    if hasattr(item, 'model_dump'):
        return item.model_dump()  # Pydantic v2
    if hasattr(item, 'dict'):
        return item.dict()  # Pydantic v1
    return item  # Já é dict

# Removemos @lru_cache aqui pois dicts não são "hashable"


def select_component_fast(components_list: List[dict], voltage_req: float, current_req: float) -> Optional[dict]:
    """Seleciona o primeiro componente compatível (assumindo lista ordenada por preço)."""
    for c in components_list:
        # Garante que lemos como dict
        vdc = c.get('vdc_max', 0)
        a_max = c.get('a_max', 0)

        if vdc >= voltage_req and a_max >= current_req:
            return c
    return None


def select_bms_fast(bms_list: List[dict], series_cells: int, max_current: float) -> Optional[dict]:
    """Lógica específica para BMS."""
    for b in bms_list:
        max_cells = b.get('max_cells', 0)
        a_max = b.get('a_max', 0)

        if max_cells >= series_cells and a_max >= max_current:
            return b
    return None


def select_cable_fast(cables_list: List[dict], i_peak: float, v_max: float, t_amb: float) -> Optional[dict]:
    """Cálculo térmico de cabos."""
    delta_T = CABLE_TEMP_MAX - t_amb
    if delta_T <= 0:
        delta_T = MIN_DELTA_T

    A_m2 = (pow(i_peak, 2) * RHO_E_COPPER *
            pow(DEFAULT_CABLE_LENGTH_M, 2) * THERMAL_RESISTANCE) / delta_T
    A_mm2_calc = A_m2 * 1e6

    for c in cables_list:
        section = c.get('section', 0)
        vdc = c.get('vdc_max', 0)
        a_max = c.get('a_max', 0)

        # section >= A_mm2_calc and vdc >= v_max and
        if a_max >= i_peak:
            # Retorna uma cópia modificada com o preço calculado
            return {
                "brand": c.get('brand', ''),
                "model": f"{c.get('model', '')} {c.get('model_suffix', '')}".strip(),
                "section": section,
                "vdc_max": vdc,
                "a_max": a_max,
                "temp_min": c.get('temp_min', 0),
                "temp_max": c.get('temp_max', 0),
                # Preço por 2 metros
                "price": c.get('price', 0) * DEFAULT_CABLE_LENGTH_M * 2,
                "link": c.get('link', '')
            }
    return None


def config_geometry_validation_fast(cell: CellData, series: int, parallel: int, max_x: float, max_y: float) -> bool:
    """Validação geométrica rápida usando fatorização."""
    total_cells = series * parallel
    e_cell_spacing = cell.Cell_Thickness + SPACING_THICKNESS_MM
    l_cell_spacing = cell.Cell_Width + SPACING_WIDTH_MM

    factors = get_integer_factors(total_cells)
    dim_ops = [(e_cell_spacing, l_cell_spacing),
               (l_cell_spacing, e_cell_spacing)]

    for dim_x, dim_y in dim_ops:
        for nx, ny in factors:
            if (nx * dim_x <= max_x) and (ny * dim_y <= max_y):
                return (nx, ny)
            if (ny * dim_x <= max_x) and (nx * dim_y <= max_y):
                return (ny, nx)
    return False


def assess_safety(req: Requirements, cell: CellData, config_values: dict) -> SafetyAssessment:
    warnings = []
    recs = []
    score = 100
    is_safe = True

    req_current = config_values['continuous_current']

    # Capacidade total do pack em Ah
    pack_capacity_ah = (cell.Capacity / 1000) * config_values['parallel_cells']

    # C-rate efetivo
    actual_c_rate = req_current / pack_capacity_ah if pack_capacity_ah > 0 else 999
    limit_continuous = cell.MaxContinuousDischargeRate

    # 1. Verificação de Corrente
    if actual_c_rate > limit_continuous:
        warnings.append("DANGER: Current exceeds cell limits. Fire risk.")
        score = 0
        is_safe = False
    elif actual_c_rate > (limit_continuous * 0.8):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C). Cells need cooling.")
        score -= 50
        recs.append("Add spacing (min 2mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.7):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C). Cells need cooling.")
        score -= 40
        recs.append("Add spacing (min 2mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.6):
        warnings.append(
            f"Warning: High Load ({actual_c_rate:.2f}C).")
        score -= 20
        recs.append("Add spacing (min 1mm) between cells.")
    elif actual_c_rate > (limit_continuous * 0.5):
        score -= 10
        recs.append("Add spacing (min 0.5mm) between cells.")

    # 2. Verificação de Tensão
    if config_values['voltage'] > 90:
        score -= 40
        warnings.append("Very High Voltage (>90V): Severe shock risk.")
        recs.append("Use isolated connectors and protective casing.")
    elif config_values['voltage'] > 60:
        score -= 20
        warnings.append("High Voltage (>60V): Lethal shock risk.")
        recs.append("Use isolated connectors.")

    if score < 0:
        score = 0

    return SafetyAssessment(
        is_safe=is_safe,
        safety_score=score,
        warnings=warnings,
        recommendations=recs
    )


def compute_single_chemistry(req, cell, stats):

    configs = []
    min_series = math.ceil(req.min_voltage / (cell.NominalVoltage))
    max_series = math.floor(req.max_voltage / (cell.NominalVoltage))
    max_series = min_series

    if min_series > max_series:
        return None  # Nenhuma configuração possível

    for series in range(min_series, max_series + 1):
        bat_voltage = series * cell.NominalVoltage
        max_voltage = series * cell.ChargeVoltage

        # Estimativa de Parallel
        cell_power = (cell.Capacity * 1e-3 *
                      cell.MaxContinuousDischargeRate) * cell.NominalVoltage
        min_p_power = math.ceil(
            req.min_continuous_power / (series * cell_power)) if cell_power > 0 else 1

        cell_energy = (cell.Capacity * 1e-3 * cell.NominalVoltage)
        min_p_energy = math.ceil(
            req.min_energy / (series * cell_energy)) if cell_energy > 0 else 1

        parallel = max(min_p_power, min_p_energy)

        stats["totalAttempts"] += 1

        # --- SAFETY CHECK ---
        cont_current = req.min_continuous_power / bat_voltage
        cont_current_pack = max(cont_current, cell.Capacity * 1e-3 *
                                cell.MaxContinuousDischargeRate*parallel)

        safety = assess_safety(req, cell, {
            'continuous_current': cont_current,
            'parallel_cells': parallel,
            'voltage': bat_voltage
        })

        # if not safety.is_safe:
        #    continue
        # --------------------

        total_cells = series * parallel
        bat_weight = (cell.Weight * 1e-3) * total_cells

        # if bat_weight > (req.max_weight*0.7):
        #    continue

        # layout = config_geometry_validation_fast(
        #    cell, series, parallel, req.max_width, req.max_length)
        # if not layout:
        #    continue

        # Componentes
        peak_current = (cell.Capacity * 1e-3 *
                        cell.PeakDischargeRate) * parallel

        bat_capacity = (cell.Capacity * 1e-3) * parallel

        # Preço
        cells_cost = cell.Price * bat_voltage*bat_capacity * 1e-3
        total_price = cells_cost / (2/3)

        # if total_price > req.max_price:
        #    continue

        # Instanciar Configuration (Validando com **dict)
        config = Configuration(
            cell=cell,
            series_cells=series,
            parallel_cells=parallel,
            battery_voltage=round(bat_voltage, 1),
            battery_capacity=round(bat_capacity, 1),
            battery_energy=round(bat_voltage * bat_capacity),
            battery_weight=round(bat_weight, 1),
            battery_impedance=round(
                ((cell.Impedance * 1e-3) * series) / parallel, 3) if parallel > 0 else 0,
            continuous_power=round(bat_voltage * cont_current_pack),
            peak_power=round(bat_voltage * peak_current),
            cell_price=round(cells_cost, 2),
            total_price=round(total_price, 2),
            # dimensions=Dimensions(
            #    length=round((cell.Cell_Width + SPACING_WIDTH_MM)
            #                 * math.ceil(math.sqrt(total_cells)), 1),
            #    width=round((cell.Cell_Thickness + SPACING_THICKNESS_MM)
            #                * math.ceil(math.sqrt(total_cells)), 1),
            #    height=round(cell.Cell_Height, 1)
            # ),
            safety=safety,
            # layout=layout,
            # affiliate_link=""
        )
        configs.append(config)

    # No final devolves "config" mas como dict:
    return config.model_dump()


def durability_assessment(req, cell, series_cells, parallel_cells):
    """
    Replica o modelo de durabilidade do MATLAB:

    Real_N_Cycle = N_cycles *
                    SoC_Val *
                    Discharge_Val *
                    Charge_Val *
                    Temp_Val
    """
    # ------------------------------
    # 2) Valores que vêm do req (médias de corrente e SoC)
    # ------------------------------
    # Tens estes no teu código? Se não, adicionamos ao Requirements.
    SoC_diff = 0.6          # amplitude da variação SoC
    SoC_ref = ROUND_TRIP_EFF           # swing de referência
    positive_av = req.min_continuous_power / \
        (series_cells * cell.NominalVoltage)
    negative_av = req.min_continuous_power / \
        (series_cells * cell.NominalVoltage)
    T_amb = req.ambient_temp

    # ------------------------------
    # 3) Dados provenientes da célula
    # ------------------------------
    N_cycles = cell.Cycles   # vida útil nominal da célula (ex: 3000 ciclos)
    C_Ah = (cell.Capacity * 1e-3) * parallel_cells

    max_discharge_current = cell.MaxContinuousDischargeRate * C_Ah
    max_charge_current = cell.MaxContinuousChargeRate * C_Ah

    # ------------------------------
    # 4) Converter fielmente fórmulas MATLAB
    # ------------------------------

    # SoC stress term
    # SoC_Val = ((SoC_Diff) ./ SoC_Ref).^(-1/epsilon)
    SoC_Val = ((SoC_diff) / SoC_ref) ** (-1 / EPSILON)

    # Discharge term
    # Discharge_Val = (positive_av / (MaxDischargeRate*C_Ah)).^(-1/lambda1)
    Discharge_Val = (positive_av / max_discharge_current) ** (-1 / LAMBDA1)

    # Charge term (é média 50/50 tal como no MATLAB)
    # Charge_Val = ((neg_av/(maxC*C) * 0.5 + charging_current/(maxC*C) * 0.5))^(-1/lambda2)
    Charge_Val = 0.5 * (negative_av / max_charge_current) ** (-1 / LAMBDA2)

    # Temperature term
    # Temp_Val = exp(-(phi)*(1/(T+273.15) - 1/(25+273.15)))
    Temp_Val = math.exp(-(PHI) * (1 / (T_amb + 273.15) - 1 / (25 + 273.15)))

    # ------------------------------
    # 5) Real cycle life — igual ao MATLAB
    # ------------------------------
    Real_N_Cycle = N_cycles * SoC_Val * Discharge_Val * Charge_Val * Temp_Val

    return Real_N_Cycle


def financial_analysis(
    battery_cost: float,
    battery_energy_kWh: float,
    cycle_life: int,
    price_buy: float,
    price_sell: float,
    cycles_per_year: int,
    years: int = 15
) -> dict:
    """
    Calcula retorno financeiro total de uma bateria:
    - cash flow anual
    - payback
    - NPV
    - IRR
    - receita e lucro

    Adequado para:
    • arbitragem energia
    • peak-shaving
    • autoconsumo
    • microgrid
    • utility-scale
    """

    # ------------------------------
    # PRODUÇÃO DE RECEITA ANUAL
    # ------------------------------
    # Energia útil por ciclo (com degradação integrada depois)
    usable_energy_kWh = battery_energy_kWh * ROUND_TRIP_EFF

    # Receita bruta anual (diferença compra vs venda)
    revenue_per_cycle = usable_energy_kWh * (price_sell - price_buy)
    base_annual_revenue = revenue_per_cycle * cycles_per_year

    # ------------------------------
    # OPEX ANUAL
    # ------------------------------
    annual_opex = battery_cost * OPEX_RATE

    # ------------------------------
    # CASH FLOW ANUAL POR ANO (inclui degradação)
    # ------------------------------
    cashflows = []
    capacities = []

    current_capacity = battery_energy_kWh

    for year in range(1, years + 1):
        # degrada capacidade
        current_capacity *= (1 - DEGRADATION_PER_YEAR)
        capacities.append(current_capacity)

        usable_energy_y = current_capacity * ROUND_TRIP_EFF

        annual_revenue_y = (
            usable_energy_y * (price_sell - price_buy)) * cycles_per_year

        annual_profit = annual_revenue_y - annual_opex
        cashflows.append(annual_profit)

    # ------------------------------
    # PAYBACK
    # ------------------------------
    cumulative = 0
    payback_year = None
    for y, cf in enumerate(cashflows, start=1):
        cumulative += cf
        if cumulative >= battery_cost:
            payback_year = y
            break

    # ------------------------------
    # NPV
    # ------------------------------
    npv = -battery_cost
    for y, cf in enumerate(cashflows, start=1):
        npv += cf / ((1 + INTEREST_RATE) ** y)

    # ------------------------------
    # IRR
    # ------------------------------
    def try_irr():
        # Tenta IRR via pesquisa simples
        low, high = -0.9, 1.0
        for _ in range(200):
            mid = (low + high) / 2
            npv_test = -battery_cost + sum(
                cf / ((1 + mid) ** (i + 1)) for i, cf in enumerate(cashflows)
            )
            if npv_test > 0:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    irr = try_irr()

    # ------------------------------
    # OUTPUT FINAL
    # ------------------------------
    return {
        "capex": battery_cost,
        "opex_annual": annual_opex,
        "cycles_per_year": cycles_per_year,
        "revenue_first_year": base_annual_revenue,
        "cashflows": cashflows,
        "payback_years": payback_year,
        "npv": npv,
        "irr": irr,
        "capacity_vs_year": capacities,
        "total_profit_over_lifetime": sum(cashflows) - battery_cost
    }


def solve_multichemistry_optimization(req: Requirements, cell_catalogue: List[CellData]) -> Optional[Dict[str, Any]]:
    """
    Otimiza a combinação de TODAS as químicas disponíveis para satisfazer os requisitos
    ao menor custo possível.

    Variáveis de decisão: P_i (Número de células em paralelo para a química i)
    Restrições:
      1. Tensão: S_i (Série) é fixo por química -> V_req / V_nom_i
      2. Energia: Sum(P_i * S_i * Energia_celula_i) >= Energia_Req
      3. Potência: Sum(P_i * S_i * Potencia_celula_i) >= Potencia_Req
      4. Inteiros: P_i >= 0 e inteiro.

    Objetivo: Minimizar Sum(P_i * S_i * Preço_celula_i)
    """

    if not cell_catalogue:
        return None

    # 1. Preparar Vetores para o Solver Linear (scipy.optimize.linprog)
    # c: coeficientes da função objetivo (Custo por string paralela)
    # A_ub: matriz das desigualdades (Energia, Potência) - Usamos negativo pois linprog é <=
    # b_ub: limites das desigualdades

    c = []          # Custo por string
    A_ub = [[], []]  # [0]: Energia, [1]: Potência

    series_counts = []  # Guarda o valor de S calculado para cada química
    valid_indices = []  # Mapeia índice do solver para índice no catálogo original

    for idx, cell in enumerate(cell_catalogue):
        # Constraint de Tensão: S = multiplo necessário para atingir tensão mínima
        if cell.NominalVoltage <= 0:
            continue

        s_cells = math.ceil(req.min_voltage / cell.NominalVoltage)
        series_counts.append(s_cells)
        valid_indices.append(idx)

        # Custo de uma string desta química (S * Preço_unitário)
        cost_string = s_cells * \
            (cell.Price * (cell.Capacity * 1e-6 * cell.NominalVoltage))
        c.append(cost_string)

        # Energia de uma string (S * Wh_cell)
        energy_string = s_cells * (cell.Capacity * 1e-3 * cell.NominalVoltage)
        # Negativo para converter >= Req em <= -Req
        A_ub[0].append(-energy_string)

        # Potência de uma string (S * W_cell_cont)
        power_string = s_cells * \
            (cell.Capacity * 1e-3 * cell.MaxContinuousDischargeRate * cell.NominalVoltage)
        A_ub[1].append(-power_string)

    b_ub = [-req.min_energy, -req.min_continuous_power]

    c = np.array(c, dtype=float)
    A_ub = np.array(A_ub, dtype=float)
    b_ub = np.array(b_ub, dtype=float)

    # 2. Executar Otimização (MILP - Mixed Integer Linear Programming)
    # O método 'highs' suporta restrição de integridade (integrality=1)
    try:
        res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=(
            0, None), integrality=1, method='highs')
    except Exception as e:
        print(f"Erro na otimização MILP: {e}. Tentando relaxamento linear.")
        # Fallback para versões antigas do scipy: resolve linear e arredonda para cima
        res = linprog(c, A_ub=A_ub, b_ub=b_ub,
                      bounds=(0, None), method='highs')
        if res.success:
            # Arredondar para cima garante cumprimento dos requisitos
            res.x = np.ceil(res.x)

    if not res.success:
        return None  # Não foi possível encontrar solução ótima

    # 3. Construir o Resultado
    parallel_counts = np.round(res.x).astype(int)

    subpacks = []
    total_energy = 0
    total_power = 0
    total_cost = 0
    total_weight = 0
    weighted_safety = 0
    weighted_durability = 0
    total_durability = float('inf')
    total_cells_all = 0

    # Primeiro passo: calcular totais para ponderação
    temp_results = []
    for solver_idx, p_count in enumerate(parallel_counts):
        if p_count <= 0:
            continue

        original_idx = valid_indices[solver_idx]
        cell = cell_catalogue[original_idx]
        s_count = series_counts[solver_idx]

        # Calcular propriedades deste subpack
        n_cells = s_count * p_count
        sub_voltage = s_count * cell.NominalVoltage
        sub_energy = n_cells * (cell.Capacity * 1e-3 * cell.NominalVoltage)
        sub_power = n_cells * \
            (cell.Capacity * 1e-3 * cell.MaxContinuousDischargeRate * cell.NominalVoltage)
        sub_cost = n_cells * \
            (cell.Price * (cell.Capacity * 1e-6 * cell.NominalVoltage))
        sub_weight = n_cells * (cell.Weight * 1e-3)

        sub_capacity_ah = p_count * (cell.Capacity * 1e-3)

        # Impedância do Pack: (S * Impedância_célula_mOhm / 1000) / P
        if p_count > 0:
            sub_impedance = (
                (cell.Impedance * 1e-3) * s_count) / p_count
        else:
            sub_impedance = 0

        # Corrente de pico do pack: C-rate pico * Ah_pack
        peak_current = cell.PeakDischargeRate * sub_capacity_ah

        # Potência de pico
        sub_peak_power = sub_voltage * peak_current

        # Durabilidade e Segurança
        durability = durability_assessment(req, cell, s_count, p_count)

        safety = assess_safety(req, cell, {
            # Simplificação para safety score
            'continuous_current': req.min_continuous_power / sub_voltage,
            'parallel_cells': p_count,
            'voltage': sub_voltage
        })

        temp_results.append({
            "cell": cell,
            "s": s_count,
            "p": p_count,
            "n": n_cells,
            "energy": sub_energy,
            "power": sub_power,
            "cost": sub_cost,
            "weight": sub_weight,
            "durability": durability,
            "safety": safety
        })

        total_energy += sub_energy
        total_power += sub_power
        total_cost += sub_cost
        total_weight += sub_weight
        total_cells_all += n_cells
        total_durability = min(total_durability, durability)

    if total_cells_all == 0:
        return None

    total_cost = total_cost/(2/3)  # Ajuste de margem

    # Segundo passo: Montar objeto final e médias ponderadas
    multi_chem_list = []

    for item in temp_results:
        fraction = item['n'] / total_cells_all
        weighted_safety += item['safety'].safety_score * fraction
        weighted_durability += item['cell'].Cycles * \
            fraction  # Durabilidade nominal ponderada

        sub_voltage = item['s'] * item['cell'].NominalVoltage
        sub_capacity_ah = item['p'] * (item['cell'].Capacity * 1e-3)

        # Impedância do Pack: (S * Impedância_célula_mOhm / 1000) / P
        if item['p'] > 0:
            sub_impedance = (
                (item['cell'].Impedance * 1e-3) * item['s']) / item['p']
        else:
            sub_impedance = 0

        # Corrente de pico do pack: C-rate pico * Ah_pack
        peak_current = item['cell'].PeakDischargeRate * sub_capacity_ah

        # Potência de pico
        sub_peak_power = sub_voltage * peak_current

        # Estrutura similar ao compute_single_chemistry
        sp_dict = {
            "cell": item['cell'].model_dump(),
            "series_cells": item['s'],
            "parallel_cells": item['p'],
            "cell_count": item['n'],
            "battery_voltage": round(sub_voltage, 1),
            "battery_capacity": round(sub_capacity_ah, 1),
            "battery_impedance": round(sub_impedance, 3),
            "peak_power": round(sub_peak_power, 0),
            "cell_price": round(item['cost'], 2),
            "battery_energy": item['energy'],
            "continuous_power": item['power'],
            "total_price": item['cost'],
            "battery_weight": item['weight'],
            "Cycles": item['durability'],
            "safety": item['safety']
        }
        subpacks.append(sp_dict)

        # Percentagem de contribuição para energia e potência (aproximada)
        pE = item['energy'] / total_energy if total_energy > 0 else 0
        pP = item['power'] / total_power if total_power > 0 else 0
        multi_chem_list.append((item['cell'].CellModelNo, pE, pP))

    # Análise Financeira Global
    analysis = financial_analysis(
        battery_cost=total_cost,
        battery_energy_kWh=total_energy / 1000,
        cycle_life=weighted_durability,
        price_buy=PRICE_BUY,
        price_sell=PRICE_SELL,
        cycles_per_year=CYCLES_PER_YEAR,
        years=YEARS
    )

    final_config = {
        "description": "Optimal Multi-Chemistry Mix (Solver)",
        "multiChemistry": multi_chem_list,
        "battery_energy": total_energy,
        "continuous_power": total_power,
        "total_price": total_cost,
        "battery_weight": total_weight,
        "safety_score": weighted_safety,
        "durability_score": total_durability,
        "subpacks": subpacks,
        "financial_KPIs": analysis
    }

    return final_config


def compute_cell_configurations(req: Any, cell_catalogue: List[CellData], component_db: Dict[str, List[Any]]) -> Dict[str, Any]:

    configs = []
    stats = {"totalAttempts": 0, "validConfigurations": 0}

    # -----------------------------------
    # 1) Construir combinações independentes de energia e potência
    # -----------------------------------

    percent_steps = [0, 0.25, 0.5, 0.75, 1]

    combinations = []   # (cellA, pE, pP), (cellB, 1-pE, 1-pP)

    for i in range(len(cell_catalogue)):
        for j in range(i+1, len(cell_catalogue)):

            for pE in percent_steps:       # divisões de energia
                for pP in percent_steps:   # para cada energia → divisões independentes de potência

                    combinations.append([
                        (cell_catalogue[i], pE, pP),              # química A
                        (cell_catalogue[j], 1 - pE, 1 - pP)       # química B
                    ])

    # -----------------------------------
    # 2) Avaliar cada combinação multiquímica
    # -----------------------------------
    for combo in combinations:

        total_energy = 0
        total_power = 0
        total_cost = 0
        total_weight = 0
        weighted_safety = 0
        weighted_durability = 0
        total_durability = float('inf')

        valid_combo = True
        subpacks = []

        for cell, pE, pP in combo:

            energy_req = req.min_energy * pE
            power_req = req.min_continuous_power * pP

            # criar uma cópia local dos requisitos
            local_req = Requirements(**req.model_dump())
            local_req.min_energy = energy_req
            local_req.min_continuous_power = power_req

            # computação de 1 química
            single_result = compute_single_chemistry(local_req, cell, stats)

            if single_result is None:
                valid_combo = False
                break

            # número de células usadas no subpack
            subpack_cells = single_result["series_cells"] * \
                single_result["parallel_cells"]

            durability = float('inf')
            if subpack_cells > 0:
                durability = durability_assessment(
                    req,
                    cell,
                    single_result["series_cells"],
                    single_result["parallel_cells"]
                )

            # guardar para calcular o total no final
            subpacks.append(
                {**single_result, "cell_count": subpack_cells, "Cycles": durability})

            total_energy += single_result['battery_energy']
            total_power += single_result['continuous_power']
            total_cost += single_result['total_price']
            total_weight += single_result['battery_weight']
            total_durability = min(durability, total_durability)

        if not valid_combo:
            continue

        # calcular total de células do pack multi-química
        total_cells = sum(sp["cell_count"] for sp in subpacks)

        weighted_safety = 0
        weighted_durability = 0

        for sp, (cell, _pE, _pP) in zip(subpacks, combo):

            cell_fraction = sp["cell_count"] / \
                total_cells  # percentagem real de células

            weighted_safety += sp["safety"]["safety_score"] * cell_fraction
            weighted_durability += cell.Cycles * cell_fraction

        analysis = financial_analysis(
            battery_cost=total_cost,
            battery_energy_kWh=total_energy / 1000,
            cycle_life=weighted_durability,   # ou outra métrica
            price_buy=PRICE_BUY,
            price_sell=PRICE_SELL,
            cycles_per_year=CYCLES_PER_YEAR,
            years=YEARS
        )

        final_config = {
            "multiChemistry": [(c.CellModelNo, pE, pP) for c, pE, pP in combo],
            "battery_energy": total_energy,
            "continuous_power": total_power,
            "total_price": total_cost,
            "battery_weight": total_weight,
            "safety_score": weighted_safety,
            "durability_score": total_durability,
            "subpacks": subpacks,
            "financial_KPIs": analysis
        }

        configs.append(final_config)

    # -----------------------------------
    # 3) Fazer otimização de combinação multiquímica
    # -----------------------------------
    optimal_mix = solve_multichemistry_optimization(req, cell_catalogue)

    if optimal_mix:
        # Adiciona o resultado da otimização global à lista de configurações
        configs.insert(0, optimal_mix)  # Coloca no topo como destaque
        stats['validConfigurations'] += 1

    # ordenar por €/kWh
    # configs.sort(key=lambda x: x["total_price"] / x["battery_energy"])

    return {
        "results": configs,
        "plotResults": configs,
        "total": len(configs),
        "stats": stats
    }

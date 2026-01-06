import pandas as pd
import matplotlib.pyplot as plt

# 1. Ler o ficheiro CSV
nome_do_ficheiro = 'data/household_data_15min_singleindex_filtered.csv'
df = pd.read_csv(nome_do_ficheiro, parse_dates=['utc_timestamp'])

# 2. Preparar os dados
df.set_index('utc_timestamp', inplace=True)

colunas_para_plot = [
    'DE_KN_industrial2_grid_import'
    # 'DE_KN_industrial2_pv',
    # 'DE_KN_industrial2_storage_charge',
    # 'DE_KN_industrial2_storage_decharge'
]

# 3. Calcular a diferença (Energia do intervalo)
df_diff = df[colunas_para_plot].diff()

# 4. Converter para Potência Média
df_power = df_diff * 4

# 5. REMOVER O ÚLTIMO VALOR
df_power = df_power.iloc[:-1]

# 6. FILTRAR PICOS (Ignorar valores > 500)
# Mantemos apenas os valores que sejam menores ou iguais a 500
df_power = df_power[df_power <= 500]

# 7. Gerar o gráfico
plt.figure(figsize=(15, 7))

for coluna in colunas_para_plot:
    if coluna in df_power.columns:
        # dropna() é usado aqui para não plotar falhas se o filtro criou NaNs
        serie_filtrada = df_power[coluna].dropna()
        plt.plot(serie_filtrada.index, serie_filtrada,
                 label=coluna, linewidth=1, alpha=0.7)

plt.title('Potência Calculada (Filtro: <= 500)')
plt.xlabel('Data')
plt.ylabel('Potência (ex: kW)')
plt.legend(loc='upper right')
plt.grid(True, alpha=0.3)
plt.tight_layout()

# 8. Guardar e mostrar
plt.savefig('grafico_potencia_filtrado.png')
print("Gráfico guardado como 'grafico_potencia_filtrado.png'")
plt.show()

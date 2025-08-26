import pandas as pd
from collections import defaultdict
from pandas.tseries.offsets import MonthEnd
import re

def _parse_vencimento_flex(venc_str):
    """
    Função auxiliar para converter datas de vencimento nos formatos
    'MM/YYYY' ou 'MM/YY' para um objeto datetime padronizado.
    """
    if not isinstance(venc_str, str):
        return pd.NaT # Retorna NaT se não for uma string

    # Tenta encontrar o formato MM/YYYY
    match_full = re.match(r'^\s*(\d{2})/(\d{4})\s*$', venc_str)
    if match_full:
        mes, ano = match_full.groups()
        return pd.to_datetime(f'{ano}-{mes}-01')

    # Tenta encontrar o formato MM/YY
    match_short = re.match(r'^\s*(\d{2})/(\d{2})\s*$', venc_str)
    if match_short:
        mes, ano_short = match_short.groups()
        # Assume que anos de 00 a 50 são de 20xx
        ano_full = f'20{ano_short}'
        return pd.to_datetime(f'{ano_full}-{mes}-01')

    # Se não encontrar nenhum dos formatos, tenta a conversão direta do pandas
    return pd.to_datetime(venc_str, errors='coerce')


def _processar_opcoes(df_opcoes: pd.DataFrame, data_apuracao: pd.Timestamp):
    # (Esta função auxiliar não precisa de mudanças)
    eventos_opcoes = []
    if df_opcoes.empty:
        return eventos_opcoes
    df_opcoes['Vencimento'] = df_opcoes['Vencimento'] + MonthEnd(0)
    opcoes_agrupadas = df_opcoes.groupby(['Ativo', 'Vencimento', 'Categoria'])
    for (ativo, vencimento, categoria), group in opcoes_agrupadas:
        vendas = group[group['Operacao'] == 'V']
        compras = group[group['Operacao'] == 'C']
        total_vendido = vendas['Valor'].sum()
        qtd_vendida = vendas['Quantidade'].sum()
        total_comprado = compras['Valor'].sum()
        qtd_comprada = compras['Quantidade'].sum()
        data_ultima_op = group['Data Pregao'].max()
        if qtd_comprada == qtd_vendida:
            lucro_bruto = total_vendido - total_comprado
            eventos_opcoes.append({'Ano-Mês': data_ultima_op.to_period('M').strftime('%Y-%m'), 'Categoria': categoria, 'Vendas Totais': total_vendido, 'Lucro Bruto': lucro_bruto})
        elif vencimento.to_period('M') < data_apuracao.to_period('M'):
            lucro_bruto = total_vendido - total_comprado
            eventos_opcoes.append({'Ano-Mês': vencimento.to_period('M').strftime('%Y-%m'), 'Categoria': categoria, 'Vendas Totais': total_vendido, 'Lucro Bruto': lucro_bruto})
    return eventos_opcoes

def _processar_outros_ativos(df_outros: pd.DataFrame):
    # (Esta função auxiliar não precisa de mudanças)
    eventos_outros = []
    if df_outros.empty:
        return eventos_outros
    custodia = defaultdict(lambda: {'long': {'qtd': 0, 'custo': 0.0}, 'short': {'qtd': 0, 'receita': 0.0}})
    for _, row in df_outros.iterrows():
        ativo, categoria, op, qtd, valor, data = \
            row['Ativo'], row['Categoria'], row['Operacao'], row['Quantidade'], row['Valor'], row['Data Pregao']
        key = (ativo, categoria)
        if op == 'C':
            posicao_short = custodia[key]['short']
            if posicao_short['qtd'] > 0:
                qtd_a_fechar = min(qtd, posicao_short['qtd'])
                receita_media_venda = posicao_short['receita'] / posicao_short['qtd'] if posicao_short['qtd'] > 0 else 0
                custo_da_compra_p_fechar = (valor / qtd) * qtd_a_fechar if qtd > 0 else 0
                lucro_bruto = (receita_media_venda * qtd_a_fechar) - custo_da_compra_p_fechar
                eventos_outros.append({'Ano-Mês': data.to_period('M').strftime('%Y-%m'), 'Categoria': categoria, 'Vendas Totais': 0, 'Lucro Bruto': lucro_bruto})
                posicao_short['qtd'] -= qtd_a_fechar
                posicao_short['receita'] -= (receita_media_venda * qtd_a_fechar)
                qtd_restante = qtd - qtd_a_fechar
                if qtd_restante > 0:
                    custodia[key]['long']['qtd'] += qtd_restante
                    custodia[key]['long']['custo'] += (valor / qtd) * qtd_restante if qtd > 0 else 0
            else:
                custodia[key]['long']['qtd'] += qtd
                custodia[key]['long']['custo'] += valor
        elif op == 'V':
            posicao_long = custodia[key]['long']
            if posicao_long['qtd'] > 0:
                qtd_a_vender = min(qtd, posicao_long['qtd'])
                custo_medio = posicao_long['custo'] / posicao_long['qtd'] if posicao_long['qtd'] > 0 else 0
                custo_da_venda = custo_medio * qtd_a_vender
                valor_da_venda = (valor / qtd) * qtd_a_vender if qtd > 0 else 0
                lucro_bruto = valor_da_venda - custo_da_venda
                eventos_outros.append({'Ano-Mês': data.to_period('M').strftime('%Y-%m'), 'Categoria': categoria, 'Vendas Totais': valor_da_venda, 'Lucro Bruto': lucro_bruto})
                posicao_long['qtd'] -= qtd_a_vender
                posicao_long['custo'] -= custo_da_venda
                qtd_restante = qtd - qtd_a_vender
                if qtd_restante > 0:
                    custodia[key]['short']['qtd'] += qtd_restante
                    custodia[key]['short']['receita'] += (valor / qtd) * qtd_restante if qtd > 0 else 0
            else:
                custodia[key]['short']['qtd'] += qtd
                custodia[key]['short']['receita'] += valor
    return eventos_outros

def calcular_ir(df_operacoes: pd.DataFrame, data_apuracao=None) -> pd.DataFrame:
    if df_operacoes.empty:
        return pd.DataFrame()

    df = df_operacoes.copy()

    # --- 1. PREPARAÇÃO DOS DADOS ---
    if 'Ativo' not in df.columns:
        df.rename(columns={'Titulo': 'Ativo'}, inplace=True)

    df['Data Pregao'] = pd.to_datetime(df['Data Pregao'], format='%d/%m/%Y', errors='coerce')
    
    # --- MUDANÇA PRINCIPAL AQUI ---
    if 'Vencimento' in df.columns:
        # Usa a nova função flexível para tratar as datas
        df['Vencimento'] = df['Vencimento'].apply(_parse_vencimento_flex)
    else:
        df['Vencimento'] = pd.NaT

    if 'CompraVenda' in df.columns and not df['CompraVenda'].isnull().all():
        df['Operacao'] = df['CompraVenda']
    else:
        df['Operacao'] = df['D/C'].map({'D': 'C', 'C': 'V'})

    df['Valor'] = pd.to_numeric(df['Valor'], errors='coerce')
    df['Quantidade'] = pd.to_numeric(df['Quantidade'], errors='coerce')
    df.dropna(subset=['Valor', 'Quantidade', 'Operacao', 'Data Pregao'], inplace=True)
    
    # --- 2. CLASSIFICAÇÃO DA CATEGORIA (sem mudanças) ---
    def classificar_categoria(row):
        tipo_mercado = str(row.get('Tipo Mercado', '')).upper()
        ativo = str(row['Ativo']).upper()
        operacoes_no_dia = df[(df['Ativo'] == row['Ativo']) & (df['Data Pregao'].dt.date == row['Data Pregao'].date)]
        has_compra = 'C' in operacoes_no_dia['Operacao'].values
        has_venda = 'V' in operacoes_no_dia['Operacao'].values
        if has_compra and has_venda: return 'Day Trade'
        if 'OPCAO' in tipo_mercado: return 'Opções Swing'
        if 'FII' in ativo or 'FUNDO IMOB' in tipo_mercado: return 'Fundos Imobiliários'
        return 'Ações Swing'
    df['Categoria'] = df.apply(classificar_categoria, axis=1)

    # --- 3. SEPARAÇÃO E PROCESSAMENTO (sem mudanças) ---
    data_apuracao_ts = pd.to_datetime(data_apuracao) if data_apuracao else df['Data Pregao'].max()
    df_opcoes = df[df['Categoria'].str.contains("Opções")].copy()
    df_outros = df[~df['Categoria'].str.contains("Opções")].copy()
    eventos_opcoes = _processar_opcoes(df_opcoes, data_apuracao_ts)
    eventos_outros = _processar_outros_ativos(df_outros)
    eventos = eventos_opcoes + eventos_outros

    # --- 4. CÁLCULO E AGRUPAMENTO FINAL DO IR (sem mudanças) ---
    if not eventos:
        return pd.DataFrame()
    df_eventos = pd.DataFrame(eventos)
    df_resumo = df_eventos.groupby(['Ano-Mês', 'Categoria'], as_index=False).sum()
    df_resumo = df_resumo.sort_values('Ano-Mês').reset_index(drop=True)
    df_resumo['Prejuízo Acumulado'] = 0.0
    df_resumo['Lucro Líquido'] = 0.0
    df_resumo['IR a Pagar'] = 0.0
    df_resumo['DARF Acumulada'] = 0.0
    prejuizo_acumulado = defaultdict(float)
    darf_acumulada = defaultdict(float)
    for idx, row in df_resumo.iterrows():
        cat = row['Categoria']
        lucro_bruto_mes = row['Lucro Bruto']
        lucro_com_prejuizo_abatido = lucro_bruto_mes - prejuizo_acumulado[cat]
        prejuizo_acumulado[cat] = 0
        lucro_liquido_mes = 0.0
        if lucro_com_prejuizo_abatido < 0:
            prejuizo_acumulado[cat] = abs(lucro_com_prejuizo_abatido)
        else:
            lucro_liquido_mes = lucro_com_prejuizo_abatido
        df_resumo.at[idx, 'Lucro Líquido'] = lucro_liquido_mes
        df_resumo.at[idx, 'Prejuízo Acumulado'] = -prejuizo_acumulado[cat]
        ir = 0.0
        if lucro_liquido_mes > 0:
            if cat == 'Ações Swing':
                vendas_mes_acoes = df_eventos[(df_eventos['Ano-Mês'] == row['Ano-Mês']) & (df_eventos['Categoria'] == 'Ações Swing')]['Vendas Totais'].sum()
                if vendas_mes_acoes > 20000:
                    ir = round(lucro_liquido_mes * 0.15, 2)
            elif cat == 'Day Trade':
                ir = round(lucro_liquido_mes * 0.20, 2)
            elif cat == 'Opções Swing':
                ir = round(lucro_liquido_mes * 0.15, 2)
            elif cat == 'Fundos Imobiliários':
                ir = round(lucro_liquido_mes * 0.20, 2)
        darf_acumulada[cat] += ir
        ir_pagar = 0.0
        if darf_acumulada[cat] >= 10.0:
            ir_pagar = round(darf_acumulada[cat], 2)
            darf_acumulada[cat] = 0.0
        df_resumo.at[idx, 'IR a Pagar'] = ir_pagar
        df_resumo.at[idx, 'DARF Acumulada'] = round(darf_acumulada[cat], 2)

    return df_resumo
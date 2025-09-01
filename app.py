import streamlit as st
import pdfplumber
import pandas as pd
from io import BytesIO
import traceback
import re
import locale
import datetime
from collections import defaultdict

# --- Imports dos Módulos do Projeto ---
from parsers.factory import get_parser_for_text
from utils import carregar_dados_corretoras, separar_notas
from database import salvar_em_banco, nota_existe, carregar_dados_do_banco
import ir_calculator
import io

# --- Função de Cache para Carregamento de Dados (ESSENCIAL) ---
@st.cache_data(ttl=3600) # Cache expira a cada 1 hora para buscar novos dados
def load_cached_data(table_name):
    """
    Função intermediária para carregar dados do banco com cache,
    evitando chamadas repetidas ao Firebase/banco de dados.
    """
    st.info(f"Buscando dados da tabela '{table_name}' no banco... (Esta mensagem deve aparecer raramente)")
    return carregar_dados_do_banco(table_name)

# --- Configuração de Localidade ---
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252')
    except locale.Error:
        st.warning("Não foi possível configurar o locale para português do Brasil.")

# --- Configuração da Página ---
st.set_page_config(page_title="Gerenciador de Notas de Corretagem", layout="wide")
st.title("📈 Gerenciador de Notas de Corretagem")

# --- Carregamento de Dados Iniciais (cache) ---
@st.cache_data
def carregar_corretoras_cached():
    return carregar_dados_corretoras("corretoras_cnpj.csv")

corretoras_df = carregar_corretoras_cached()
if corretoras_df.empty:
    st.warning("O arquivo 'corretoras_cnpj.csv' não foi encontrado ou está vazio.")

# --- Funções Auxiliares ---
CAMPOS_RESUMO_NEGOCIOS = [
    "Debêntures", "Vendas à vista", "Compras à vista", "Opções - compras",
    "Opções - vendas", "Operações à termo", "Valor das oper. c/ títulos públ. (v. nom.)",
    "Valor das operações"
]

CAMPOS_RESUMO_FINANCEIRO = [
    "Valor líquido das operações", "Taxa de liquidação", "Taxa de registro",
    "Total CBLC", "Taxa de termo/opções", "Taxa ANA", "Emolumentos",
    "Total Bovespa / Soma", "Clearing", "Execução", "Execução Casa",
    "ISS (São Paulo)", "I.R.R.R.F. s/ operações, base", "Outras",
    "Total Corretagem / Despesas", "Líquido para"
]

def converter_valor_monetario(valor_str):
    if pd.isna(valor_str):
        return None
    if not isinstance(valor_str, str):
        valor_str = str(valor_str)
    if ',' in valor_str:
        valor_str = valor_str.replace('.', '').replace(',', '.')
    return pd.to_numeric(valor_str, errors='coerce')

def extrair_campos_por_nome(texto, campos):
    resultado = {}
    linhas = texto.split('\n')
    for campo in campos:
        encontrado = False
        for linha in linhas:
            if campo.lower() in linha.lower():
                match = None
                if "líquido para" in campo.lower():
                    match = re.search(r"([\d.,]+)\s*([DC])\s*$", linha)
                else:
                    match = re.search(rf"{re.escape(campo)}.*?([\d.,]+)\s*([DC])?", linha, re.IGNORECASE)
                if match:
                    valor = match.group(1).strip()
                    dc = match.group(2).strip() if match.group(2) else ""
                    resultado[campo] = {"valor": valor, "dc": dc}
                    encontrado = True
                    break
        if not encontrado:
            resultado[campo] = {"valor": "0,00", "dc": ""}
    return resultado

# --- Função de Cálculo de Posição (colocada aqui por dependência de dados) ---
@st.cache_data # Adicionando cache aqui também para otimizar
def calcular_posicao_atual(df_operacoes: pd.DataFrame) -> pd.DataFrame:
    if df_operacoes.empty:
        return pd.DataFrame()
    df = df_operacoes.copy()
    if 'Ativo' not in df.columns:
        df.rename(columns={'Titulo': 'Ativo'}, inplace=True)
    if 'Vencimento' not in df.columns:
        df['Vencimento'] = ""
    df['Data Pregao'] = pd.to_datetime(df['Data Pregao'], format='%d/%m/%Y', errors='coerce')
    if 'CompraVenda' in df.columns and not df['CompraVenda'].isnull().all():
        df['Operacao'] = df['CompraVenda']
    else:
        df['Operacao'] = df['D/C'].map({'D': 'C', 'C': 'V'})
    df['Valor'] = pd.to_numeric(df['Valor'], errors='coerce')
    df['Quantidade'] = pd.to_numeric(df['Quantidade'], errors='coerce')
    df.dropna(subset=['Valor', 'Quantidade', 'Operacao', 'Ativo'], inplace=True)

    posicoes = defaultdict(lambda: {
        'long': {'qtd': 0, 'custo': 0.0}, 'short': {'qtd': 0, 'receita': 0.0},
        'last_date': pd.NaT, 'corretora': '', 'tipo_mercado': '', 'vencimento': ''
    })
    df = df.sort_values(by='Data Pregao')

    for _, row in df.iterrows():
        key = row['Ativo']
        op, qtd, valor, data = row['Operacao'], row['Quantidade'], row['Valor'], row['Data Pregao']
        if posicoes[key]['corretora'] == '':
            posicoes[key].update({
                'corretora': row.get('Corretora', 'N/A'),
                'tipo_mercado': row.get('Tipo Mercado', 'N/A'),
                'vencimento': row.get('Vencimento', '')
            })
        if op == 'C':
            if posicoes[key]['short']['qtd'] > 0:
                qtd_a_fechar = min(qtd, posicoes[key]['short']['qtd'])
                receita_media = posicoes[key]['short']['receita'] / posicoes[key]['short']['qtd']
                posicoes[key]['short']['qtd'] -= qtd_a_fechar
                posicoes[key]['short']['receita'] -= (receita_media * qtd_a_fechar)
                qtd_restante = qtd - qtd_a_fechar
                if qtd_restante > 0:
                    posicoes[key]['long']['qtd'] += qtd_restante
                    posicoes[key]['long']['custo'] += (valor / qtd) * qtd_restante if qtd > 0 else 0
            else:
                posicoes[key]['long']['qtd'] += qtd
                posicoes[key]['long']['custo'] += valor
        elif op == 'V':
            if posicoes[key]['long']['qtd'] > 0:
                qtd_a_vender = min(qtd, posicoes[key]['long']['qtd'])
                custo_medio = posicoes[key]['long']['custo'] / posicoes[key]['long']['qtd'] if posicoes[key]['long']['qtd'] > 0 else 0
                posicoes[key]['long']['qtd'] -= qtd_a_vender
                posicoes[key]['long']['custo'] -= (custo_medio * qtd_a_vender)
                qtd_restante = qtd - qtd_a_vender
                if qtd_restante > 0:
                    posicoes[key]['short']['qtd'] += qtd_restante
                    posicoes[key]['short']['receita'] += (valor / qtd) * qtd_restante if qtd > 0 else 0
            else:
                posicoes[key]['short']['qtd'] += qtd
                posicoes[key]['short']['receita'] += valor
        posicoes[key]['last_date'] = data

    lista_posicao_final = []
    for ativo, data in posicoes.items():
        posicao_long = data['long']
        if posicao_long['qtd'] > 0.0001:
            preco_medio = posicao_long['custo'] / posicao_long['qtd'] if posicao_long['qtd'] > 0 else 0
            venc_dt = pd.to_datetime(data['vencimento'], errors='coerce')
            venc_str = venc_dt.strftime('%d/%m/%Y') if pd.notna(venc_dt) else 'N/A'
            lista_posicao_final.append({
                'Corretora': data['corretora'], 'Ativo': ativo, 'Tipo Mercado': data['tipo_mercado'],
                'Vencimento': venc_str, 'Quantidade Custódia': int(round(posicao_long['qtd'])),
                'Preço Médio Compra': round(preco_medio, 4), 'Custo Total': round(posicao_long['custo'], 2),
                'Última Data Pregão': data['last_date'].strftime('%d/%m/%Y')
            })

    if not lista_posicao_final:
        return pd.DataFrame()
    df_posicao = pd.DataFrame(lista_posicao_final)
    return df_posicao.sort_values(by=['Corretora', 'Ativo', 'Vencimento'])

# --- Definição das Abas ---
tab1, tab2, tab3, tab4 = st.tabs(["📤 Upload PDF", "📊 Dashboard", "💰 Cálculo de IR", "💼 Meus Ativos"])

with tab1:
    st.header("Upload e Processamento de Notas Fiscais")
    uploaded_file = st.file_uploader("📎 Envie o PDF da nota de corretagem", type=["pdf"])
    if uploaded_file:
        try:
            st.success("📄 Arquivo carregado com sucesso!")
            with pdfplumber.open(BytesIO(uploaded_file.read())) as pdf:
                texto_completo = "\n".join([page.extract_text(layout=True) or "" for page in pdf.pages])
            if not texto_completo.strip():
                st.error("Não foi possível extrair texto do PDF. O arquivo pode ser uma imagem.")
            else:
                blocos_de_notas = separar_notas(texto_completo)
                if not blocos_de_notas:
                    st.warning("Nenhuma nota de corretagem válida encontrada no PDF.")
                else:
                    st.success(f"🎉 Encontradas {len(blocos_de_notas)} nota(s) de corretagem no PDF!")
                    # ... (resto da lógica de processamento do PDF, que não precisa de cache de leitura)
                    # A lógica de salvar no banco está correta.
        except Exception as e:
            st.error(f"Ocorreu um erro inesperado ao processar o PDF: {e}")
            st.error(traceback.format_exc())

with tab2:
    st.header("Dashboard de Acompanhamento")
    
    st.subheader("Informações de Cabeçalho das Notas")
    # CORREÇÃO: Usando a função com cache
    df_cabecalho = load_cached_data("notas_cabecalho")
    if not df_cabecalho.empty:
        st.dataframe(df_cabecalho, use_container_width=True)
        # ... (lógica de filtros que usa o df_cabecalho já carregado)
    else:
        st.info("Nenhuma informação de cabeçalho de nota encontrada.")

    st.markdown("---")
    st.subheader("Detalhes das Operações")
    # CORREÇÃO: Usando a função com cache
    df_operacoes = load_cached_data("operacoes")
    if not df_operacoes.empty:
        df_operacoes_formatted = df_operacoes.copy()
        df_operacoes_formatted['Preço'] = df_operacoes_formatted['Preço'].apply(converter_valor_monetario)
        df_operacoes_formatted['Valor'] = df_operacoes_formatted['Valor'].apply(converter_valor_monetario)
        st.dataframe(
            df_operacoes_formatted.style.format({'Preço': "R$ {:,.4f}", 'Valor': "R$ {:,.2f}"}),
            use_container_width=True
        )
    else:
        st.info("Nenhum dado de operações encontrado.")

    st.markdown("---")
    st.subheader("Resumo dos Negócios")
    # CORREÇÃO: Usando a função com cache
    df_resumos_negocios = load_cached_data("resumos_negocios")
    if not df_resumos_negocios.empty:
        st.dataframe(df_resumos_negocios, use_container_width=True)
    else:
        st.info("Nenhum dado de resumo de negócios encontrado.")

    st.markdown("---")
    st.subheader("Resumo Financeiro")
    # CORREÇÃO: Usando a função com cache
    df_resumos_financeiros = load_cached_data("resumos_financeiros")
    if not df_resumos_financeiros.empty:
        st.dataframe(df_resumos_financeiros, use_container_width=True)
    else:
        st.info("Nenhum dado de resumo financeiro encontrado.")

with tab3:
    st.header("💰 Cálculo de Imposto de Renda (IR)")
    # CORREÇÃO: Usando a função com cache
    df_operacoes = load_cached_data("operacoes")

    if not df_operacoes.empty:
        st.subheader("Selecione a Data de Apuração")
        df_operacoes['Data Pregao'] = pd.to_datetime(df_operacoes['Data Pregao'], format='%d/%m/%Y', errors='coerce').dropna()
        
        # Lógica de data padrão
        max_date_in_data = df_operacoes['Data Pregao'].max().date() if not df_operacoes.empty else datetime.date.today()
        default_date = max(max_date_in_data, datetime.date.today())

        data_apuracao = st.date_input(
            "Calcular IR e expirar opções até a data:",
            value=default_date,
            format="DD/MM/YYYY"
        )
        
        # MELHORIA: Adicionando spinner para feedback visual
        with st.spinner("Analisando operações e calculando IR..."):
            df_ir = ir_calculator.calcular_ir(df_operacoes, data_apuracao=data_apuracao)

        if not df_ir.empty:
            st.subheader("📊 Resumo Mensal por Categoria")
            # ... (resto da sua lógica de exibição de IR)
        else:
            st.info("Nenhum evento de IR gerado (sem vendas ou vencimentos).")
    else:
        st.info("Nenhuma operação encontrada para cálculo de IR.")

with tab4:
    st.header("💼 Meus Ativos por Corretora")
    # CORREÇÃO: Usando a função com cache
    df_operacoes = load_cached_data("operacoes")
    
    if not df_operacoes.empty:
        # MELHORIA: Adicionando spinner para feedback visual
        with st.spinner("Calculando posição atual dos ativos..."):
            df_posicao_atual = calcular_posicao_atual(df_operacoes)

        if not df_posicao_atual.empty:
            st.subheader("Custódia Atual por Ativo e Corretora")
            st.dataframe(
                df_posicao_atual.style.format({'Preço Médio Compra': "R$ {:,.4f}", 'Custo Total': "R$ {:,.2f}"}),
                use_container_width=True
            )
            # ... (resto da sua lógica de exibição dos ativos)
        else:
            st.info("Nenhum ativo em custódia encontrado.")
    else:
        st.info("Nenhuma operação encontrada para exibir os ativos.")

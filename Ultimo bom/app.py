import streamlit as st
import pdfplumber
import pandas as pd
from io import BytesIO
import traceback
import re 
import locale # Importe a biblioteca locale

# --- Configuração de Localidade (para formatação numérica em BR) ---
try:
    locale.setlocale(locale.LC_ALL, 'pt_BR.UTF-8')
except locale.Error:
    try:
        # Fallback para sistemas Windows
        locale.setlocale(locale.LC_ALL, 'Portuguese_Brazil.1252')
    except locale.Error:
        st.warning("Não foi possível configurar o locale para português do Brasil. A formatação de números pode não ser a esperada.")

# Importa os módulos que criamos
from parsers.factory import get_parser_for_text
from utils import carregar_dados_corretoras, separar_notas
from database import salvar_em_banco, nota_existe, carregar_dados_do_banco # Importe as novas funções

st.set_page_config(page_title="Gerenciador de Notas de Corretagem", layout="wide")
st.title("📈 Gerenciador de Notas de Corretagem")

# --- Carregamento de Dados Iniciais (cache) ---
@st.cache_data
def carregar_corretoras_cached():
    return carregar_dados_corretoras("corretoras_cnpj.csv")

corretoras_df = carregar_corretoras_cached()
if corretoras_df.empty:
    st.warning("O arquivo 'corretoras_cnpj.csv' não foi encontrado ou está vazio. A identificação da corretora pode falhar.")

# --- Funções Auxiliares (manter aqui ou mover para um novo arquivo 'helpers.py') ---
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

# --- Função para Calcular Posição Atual de Ativos ---
def calcular_posicao_atual(df_operacoes: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula a posição atual de cada ativo (quantidade em custódia) e o preço médio,
    considerando todas as compras e vendas.
    Assumes que 'df_operacoes' contém as colunas:
    'Tipo Mercado', 'Especificação do título'/'Titulo', 'Quantidade', 'Preço', 'D/C', 'Corretora'
    """
    if df_operacoes.empty:
        return pd.DataFrame(columns=[
            'Corretora', 'Ativo', 'Quantidade Custódia', 'Preço Médio Compra', 'Custo Total'
        ])

    # Padronizar nomes de colunas do ativo
    if 'Especificação do título' in df_operacoes.columns:
        df_operacoes['Ativo'] = df_operacoes['Especificação do título']
    elif 'Titulo' in df_operacoes.columns:
        df_operacoes['Ativo'] = df_operacoes['Titulo']
    else:
        st.error("Coluna 'Especificação do título' ou 'Titulo' não encontrada no DataFrame de operações. Não é possível calcular a posição.")
        return pd.DataFrame()

    # Converter 'Quantidade' e 'Valor' para numérico de forma robusta
    df_operacoes['Quantidade'] = pd.to_numeric(df_operacoes['Quantidade'], errors='coerce')
    
    df_operacoes['Valor'] = pd.to_numeric(
        df_operacoes['Valor'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
        errors='coerce'
    )
    
    # Filtrar apenas operações de Compra (C) e Venda (V)
    df_custodia = df_operacoes[df_operacoes['D/C'].isin(['C', 'V'])].copy()
    
    # Remover linhas com valores NaN após a conversão, pois causariam problemas nos cálculos
    df_custodia.dropna(subset=['Quantidade', 'Valor'], inplace=True)

    # Ordenar por data para garantir que o preço médio seja calculado sequencialmente
    df_custodia['Data Pregao'] = pd.to_datetime(df_custodia['Data Pregao'], format='%d/%m/%Y', errors='coerce')
    df_custodia.sort_values(by='Data Pregao', inplace=True)
    
    # Dicionário para armazenar a posição por (Corretora, Ativo)
    posicoes_por_corretora_ativo = {} # key: (corretora, ativo), value: {'qtd': int, 'custo_total': float}

    for index, row in df_custodia.iterrows():
        corretora = row['Corretora']
        ativo = row['Ativo']
        quantidade = row['Quantidade']
        valor_operacao = row['Valor']

        key = (corretora, ativo)

        if key not in posicoes_por_corretora_ativo:
            posicoes_por_corretora_ativo[key] = {'qtd': 0, 'custo_total': 0.0}

        if row['D/C'] == 'C': # Compra
            posicoes_por_corretora_ativo[key]['qtd'] += quantidade
            posicoes_por_corretora_ativo[key]['custo_total'] += valor_operacao
        elif row['D/C'] == 'V': # Venda
            if posicoes_por_corretora_ativo[key]['qtd'] > 0:
                custo_unitario_medio = posicoes_por_corretora_ativo[key]['custo_total'] / posicoes_por_corretora_ativo[key]['qtd']
                
                posicoes_por_corretora_ativo[key]['qtd'] -= quantidade
                posicoes_por_corretora_ativo[key]['custo_total'] -= (custo_unitario_medio * quantidade)
                
                if posicoes_por_corretora_ativo[key]['qtd'] < 0:
                    posicoes_por_corretora_ativo[key]['qtd'] = 0
                    posicoes_por_corretora_ativo[key]['custo_total'] = 0.0
            else:
                posicoes_por_corretora_ativo[key]['qtd'] = 0
                posicoes_por_corretora_ativo[key]['custo_total'] = 0.0


    # Construir o DataFrame de resultados finais
    lista_posicao = []
    for (corretora, ativo), data in posicoes_por_corretora_ativo.items():
        if data['qtd'] > 0: # Apenas ativos com quantidade positiva em custódia
            preco_medio = data['custo_total'] / data['qtd'] if data['qtd'] > 0 else 0
            lista_posicao.append({
                'Corretora': corretora,
                'Ativo': ativo,
                'Quantidade Custódia': int(data['qtd']),
                'Preço Médio Compra': round(preco_medio, 4),
                'Custo Total': round(data['custo_total'], 2),
            })
    
    df_posicao = pd.DataFrame(lista_posicao)
    
    # Garante a ordem das colunas para exibição
    final_columns = ['Corretora', 'Ativo', 'Quantidade Custódia', 'Preço Médio Compra', 'Custo Total']
    if not df_posicao.empty:
        df_posicao = df_posicao[final_columns]

    return df_posicao


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
                    st.warning("Nenhuma nota de corretagem válida encontrada no PDF. Verifique o formato.")
                else:
                    st.success(f"🎉 Encontradas {len(blocos_de_notas)} nota(s) de corretagem no PDF!")

                    todas_info_cabecalho = []
                    todas_operacoes = []
                    todos_resumos_especificos = []
                    todos_resumos_geral_negocios = []
                    todos_resumos_geral_financeiro = []

                    for i, bloco_nota in enumerate(blocos_de_notas):
                        st.markdown(f"---")
                        st.subheader(f"Processando Nota {i+1}")
                        
                        parser = get_parser_for_text(bloco_nota, corretoras_df)
                        
                        st.info(f"Usando o parser: **{parser.NOME_CORRETORA}**")

                        info_cabecalho = parser.extrair_info_cabecalho()
                        operacoes = parser.extrair_operacoes()
                        resumo_parser_especifico = parser.extrair_resumo()

                        # --- Lógica de Deduplicação (reforçando aqui) ---
                        num_nota = info_cabecalho.get('numero_nota')
                        data_preg = info_cabecalho.get('data_pregao')
                        cnpj_corr = info_cabecalho.get('cnpj')

                        if num_nota and data_preg and cnpj_corr and nota_existe(num_nota, data_preg, cnpj_corr):
                            st.warning(f"Nota {num_nota} da {info_cabecalho.get('corretora', 'N/A')} na data {data_preg} já existe no banco de dados. Pulando esta nota.")
                            continue # Pula para a próxima nota no loop
                        elif not (num_nota and data_preg and cnpj_corr):
                            st.warning(f"Informações incompletas para verificar duplicidade da Nota {i+1}. Processando mesmo assim.")
                        # --- Fim da Lógica de Deduplicação ---

                        todas_info_cabecalho.append(info_cabecalho)
                        
                        if not operacoes.empty:
                            # Adicionar o DataFrame original (não formatado) à lista para salvamento no DB
                            todas_operacoes.append(operacoes) 

                            # Formata uma CÓPIA do DataFrame para exibição
                            operacoes_formatted = operacoes.copy()
                            operacoes_formatted['Preço'] = pd.to_numeric(operacoes_formatted['Preço'], errors='coerce')
                            operacoes_formatted['Valor'] = pd.to_numeric(
                                operacoes_formatted['Valor'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
                                errors='coerce'
                            )
                            st.subheader(f"📊 Operações de Compra/Venda da Nota {i+1}")
                            st.dataframe(
                                operacoes_formatted.style.format({
                                    'Preço': "R$ {:,.4f}".format, # Usando a função format nativa
                                    'Valor': "R$ {:,.2f}".format # Usando a função format nativa
                                }).set_properties(**{'text-align': 'right'}), # Opcional: Alinha à direita para números
                                use_container_width=True
                            )
                            st.success("💾 Operações extraídas com sucesso!")
                        else:
                            st.info(f"Nenhuma operação de compra/venda encontrada na Nota {i+1} no formato esperado.")

                        if not resumo_parser_especifico.empty:
                            todos_resumos_especificos.append(resumo_parser_especifico)

                        with st.expander(f"🧾 Mostrar texto bruto extraído da Nota {i+1}"):
                            st.text(bloco_nota)

                        st.subheader(f"🏢 Informações da Nota {i+1}")
                        if info_cabecalho:
                            col1, col2, col3, col4 = st.columns(4)
                            col1.metric("Corretora", info_cabecalho.get("corretora", "N/A"))
                            col2.metric("Nº da Nota", info_cabecalho.get("numero_nota", "N/A"))
                            col3.metric("Data do Pregão", info_cabecalho.get("data_pregao", "N/A"))
                            col4.metric("CNPJ", info_cabecalho.get("cnpj", "N/A"))
                        else:
                            st.warning(f"Não foi possível extrair as informações do cabeçalho da Nota {i+1}.")

                        st.markdown("---")
                        st.subheader(f"Resumos Complementares da Nota {i+1} (Estilo app_streamlit4)")

                        resumo_negocios_dados = extrair_campos_por_nome(bloco_nota, CAMPOS_RESUMO_NEGOCIOS) 
                        resumo_financeiro_dados = extrair_campos_por_nome(bloco_nota, CAMPOS_RESUMO_FINANCEIRO) 

                        todos_resumos_geral_negocios.append(pd.DataFrame([
                            {"Campo": k, "Valor": v["valor"], "Numero Nota": info_cabecalho.get('numero_nota'), "Data Pregao": info_cabecalho.get('data_pregao')}
                            for k, v in resumo_negocios_dados.items()
                        ]))
                        todos_resumos_geral_financeiro.append(pd.DataFrame([
                            {"Campo": k, "Valor": v["valor"], "D/C": v["dc"], "Numero Nota": info_cabecalho.get('numero_nota'), "Data Pregao": info_cabecalho.get('data_pregao')}
                            for k, v in resumo_financeiro_dados.items()
                        ]))

                        col1_resumo, col2_resumo = st.columns(2) 

                        with col1_resumo: 
                            st.subheader("Resumo dos Negócios") 
                            df_negocios = pd.DataFrame([
                                {"Campo": k, "Valor": v["valor"]}
                                for k, v in resumo_negocios_dados.items()
                            ]) 
                            st.dataframe(df_negocios, hide_index=True, use_container_width=True) 

                        with col2_resumo: 
                            st.subheader("Resumo Financeiro") 
                            df_financeiro = pd.DataFrame([
                                {"Campo": k, "Valor": v["valor"], "D/C": v["dc"]}
                                for k, v in resumo_financeiro_dados.items()
                            ]) 
                            st.dataframe(df_financeiro, hide_index=True, use_container_width=True) 
                        
                        if not resumo_parser_especifico.empty:
                            st.subheader(f"🧾 Resumo dos Negócios (Parser Específico) da Nota {i+1}")
                            st.dataframe(resumo_parser_especifico, use_container_width=True)
                            st.success("💾 Resumo dos negócios extraído com sucesso pelo parser específico!")

                    # --- Salvamento dos resultados consolidados ---
                    st.markdown("## ✨ Resumos Consolidados de Todas as Notas Processadas")

                    if todas_info_cabecalho:
                        df_todas_info_cabecalho = pd.DataFrame(todas_info_cabecalho)
                        st.subheader("Informações de Cabeçalho Consolidadas")
                        st.dataframe(df_todas_info_cabecalho, use_container_width=True)
                        salvar_em_banco(df_todas_info_cabecalho, "notas_cabecalho")
                    else:
                        st.info("Nenhuma nova informação de cabeçalho encontrada para salvar.")

                    if todas_operacoes:
                        df_todas_operacoes = pd.concat(todas_operacoes, ignore_index=True)
                        st.subheader("Todas as Operações")
                        
                        # Formata o DataFrame consolidado para exibição
                        df_todas_operacoes_formatted = df_todas_operacoes.copy()
                        df_todas_operacoes_formatted['Preço'] = pd.to_numeric(df_todas_operacoes_formatted['Preço'], errors='coerce')
                        df_todas_operacoes_formatted['Valor'] = pd.to_numeric(
                            df_todas_operacoes_formatted['Valor'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
                            errors='coerce'
                        )

                        st.dataframe(
                            df_todas_operacoes_formatted.style.format({
                                'Preço': "R$ {:,.4f}".format,
                                'Valor': "R$ {:,.2f}".format
                            }).set_properties(**{'text-align': 'right'}),
                            use_container_width=True
                        )
                        salvar_em_banco(df_todas_operacoes, "operacoes") 
                    else:
                        st.info("Nenhuma nova operação encontrada para salvar.")

                    if todos_resumos_especificos:
                        df_todos_resumos_especificos = pd.concat(todos_resumos_especificos, ignore_index=True)
                        st.subheader("Todos os Resumos (Parser Específico)")
                        st.dataframe(df_todos_resumos_especificos, use_container_width=True)
                        salvar_em_banco(df_todos_resumos_especificos, "resumos_especificos") 
                    else:
                        st.info("Nenhum novo resumo específico encontrado para salvar.")

                    if todos_resumos_geral_negocios:
                        df_todos_resumos_geral_negocios = pd.concat(todos_resumos_geral_negocios, ignore_index=True)
                        salvar_em_banco(df_todos_resumos_geral_negocios, "resumos_negocios") 

                    if todos_resumos_geral_financeiro:
                        df_todos_resumos_geral_financeiro = pd.concat(todos_resumos_geral_financeiro, ignore_index=True)
                        salvar_em_banco(df_todos_resumos_geral_financeiro, "resumos_financeiros") 
        except Exception as e: # Este 'except' fecha o 'try' que inicia no 'if uploaded_file:'
            st.error(f"Ocorreu um erro inesperado ao processar o PDF: {e}")
            st.error(traceback.format_exc())

with tab2:
    st.header("Dashboard de Acompanhamento")
    # --- Carregar e Exibir Dados do Cabeçalho ---
    st.subheader("Informações de Cabeçalho das Notas")
    df_cabecalho = carregar_dados_do_banco("notas_cabecalho")
    if not df_cabecalho.empty:
        st.dataframe(df_cabecalho, use_container_width=True)

        # Filtros e Agrupamentos (Exemplos)
        st.markdown("---")
        st.subheader("Análise de Notas")

        col1_dash, col2_dash = st.columns(2)
        with col1_dash:
            corretoras_unicas = df_cabecalho['corretora'].unique()
            corretora_selecionada = st.selectbox("Filtrar por Corretora", ["Todas"] + list(corretoras_unicas), key="dash_corretora_select")
            
            if corretora_selecionada != "Todas":
                df_filtrado = df_cabecalho[df_cabecalho['corretora'] == corretora_selecionada]
                st.write(f"Notas da {corretora_selecionada}:")
                st.dataframe(df_filtrado, hide_index=True)
            else:
                df_filtrado = df_cabecalho

        with col2_dash:
            st.write("Contagem de Notas por Corretora:")
            contagem_corretoras = df_filtrado['corretora'].value_counts().reset_index()
            contagem_corretoras.columns = ['Corretora', 'Quantidade de Notas']
            st.dataframe(contagem_corretoras, hide_index=True)

    else:
        st.info("Nenhuma informação de cabeçalho de nota encontrada para exibir. Faça o upload de um PDF na aba 'Upload PDF'.")


    # --- Carregar e Exibir Dados de Operações ---
    st.markdown("---")
    st.subheader("Detalhes das Operações")
    df_operacoes = carregar_dados_do_banco("operacoes")
    if not df_operacoes.empty:
        # Formata uma CÓPIA do DataFrame para exibição
        df_operacoes_formatted = df_operacoes.copy()
        df_operacoes_formatted['Preço'] = pd.to_numeric(df_operacoes_formatted['Preço'], errors='coerce')
        df_operacoes_formatted['Valor'] = pd.to_numeric(
            df_operacoes_formatted['Valor'].astype(str).str.replace('.', '', regex=False).str.replace(',', '.', regex=False),
            errors='coerce'
        )

        st.dataframe(
            df_operacoes_formatted.style.format({
                'Preço': "R$ {:,.4f}".format,
                'Valor': "R$ {:,.2f}".format
            }).set_properties(**{'text-align': 'right'}),
            use_container_width=True
        )

        # Exemplo de Análise de Operações: Valor total por Tipo Mercado
        st.markdown("##### Resumo de Valores por Tipo de Mercado")
        if 'Tipo Mercado' in df_operacoes_formatted.columns and 'Valor' in df_operacoes_formatted.columns:
            resumo_valor_mercado = df_operacoes_formatted.groupby('Tipo Mercado')['Valor'].sum().reset_index()
            st.dataframe(
                resumo_valor_mercado.style.format({
                    'Valor': "R$ {:,.2f}".format
                }).set_properties(**{'text-align': 'right'}),
                hide_index=True
            )
        else:
            st.info("Colunas 'Tipo Mercado' ou 'Valor' não encontradas no DataFrame de operações.")
    else:
        st.info("Nenhum dado de operações encontrado para exibir.")


    # --- Carregar e Exibir Dados do Resumo de Negócios ---
    st.markdown("---")
    st.subheader("Resumo dos Negócios")
    df_resumos_negocios = carregar_dados_do_banco("resumos_negocios")
    if not df_resumos_negocios.empty:
        st.dataframe(df_resumos_negocios, use_container_width=True)
    else:
        st.info("Nenhum dado de resumo de negócios encontrado para exibir.")

    # --- Carregar e Exibir Dados do Resumo Financeiro ---
    st.markdown("---")
    st.subheader("Resumo Financeiro")
    df_resumos_financeiros = carregar_dados_do_banco("resumos_financeiros")
    if not df_resumos_financeiros.empty:
        st.dataframe(df_resumos_financeiros, use_container_width=True)
    else:
        st.info("Nenhum dado de resumo financeiro encontrado para exibir.")


with tab3:
    st.header("Cálculo de Imposto de Renda (IR)")
    st.info("Esta seção será desenvolvida para calcular o IR sobre operações de bolsa.")
    df_operacoes = carregar_dados_do_banco("operacoes")
    if not df_operacoes.empty:
        # Exemplo de como você chamaria as funções
        # df_operacoes['Data Pregao'] = pd.to_datetime(df_operacoes['Data Pregao'], format='%d/%m/%Y')
        # ... lógica de cálculo de IR aqui, usando as funções do ir_calculator.py
        st.write("Funcionalidade de cálculo de IR em desenvolvimento.")
    else:
        st.info("Nenhuma operação encontrada para cálculo de IR.")

with tab4:
    st.header("Meus Ativos por Corretora")
    
    df_operacoes = carregar_dados_do_banco("operacoes")
    
    if not df_operacoes.empty:
        df_posicao_atual = calcular_posicao_atual(df_operacoes)

        if not df_posicao_atual.empty:
            st.subheader("Custódia Atual por Ativo e Corretora")
            st.dataframe(
                df_posicao_atual.style.format({
                    'Preço Médio Compra': "R$ {:,.4f}".format,
                    'Custo Total': "R$ {:,.2f}".format
                }).set_properties(**{'text-align': 'right'}),
                use_container_width=True
            )

            # Agrupar por Corretora
            st.markdown("---")
            st.subheader("Ativos Agrupados por Corretora")
            corretoras = df_posicao_atual['Corretora'].unique()
            for corretora in corretoras:
                st.write(f"### {corretora}")
                df_corretora = df_posicao_atual[df_posicao_atual['Corretora'] == corretora].drop(columns=['Corretora'])
                st.dataframe(
                    df_corretora.style.format({
                        'Preço Médio Compra': "R$ {:,.4f}".format,
                        'Custo Total': "R$ {:,.2f}".format
                    }).set_properties(**{'text-align': 'right'}),
                    hide_index=True,
                    use_container_width=True
                )
            
            # --- Funcionalidade de "Vender" ou "Ajustar Posição" ---
            st.markdown("---")
            st.subheader("Ajustar Posição de Ativos (Venda/Outros Ajustes)")
            st.warning("Esta seção permite ajustar manualmente a custódia. Operações de venda de fato devem ser processadas via upload da nota de corretagem.")
            
            ativos_disponiveis = df_posicao_atual['Ativo'].unique()
            if len(ativos_disponiveis) > 0:
                col_ajuste1, col_ajuste2, col_ajuste3 = st.columns(3)
                with col_ajuste1:
                    ativo_para_ajuste = st.selectbox("Selecione o Ativo para Ajustar", [""] + list(ativos_disponiveis), key="ativo_ajuste")
                
                if ativo_para_ajuste:
                    df_ativo_selecionado = df_posicao_atual[df_posicao_atual['Ativo'] == ativo_para_ajuste]
                    
                    with col_ajuste2:
                        current_qty = df_ativo_selecionado['Quantidade Custódia'].sum()
                        st.metric(f"Quantidade Atual de {ativo_para_ajuste}", current_qty)
                        
                        ajuste_quantidade = st.number_input(f"Quantidade a Ajustar (negativo para venda)", value=0, step=10, key="ajuste_qty")
                    
                    with col_ajuste3:
                        st.markdown("### Ação")
                        if st.button("Aplicar Ajuste", key="aplicar_ajuste_btn"):
                            if abs(ajuste_quantidade) > current_qty and ajuste_quantidade < 0:
                                st.error(f"Não é possível vender mais de {current_qty} unidades de {ativo_para_ajuste}.")
                            else:
                                new_qty = current_qty + ajuste_quantidade
                                st.success(f"Quantidade de {ativo_para_ajuste} ajustada para: {new_qty}")
                                st.info("Para persistir vendas, o ideal é processar a nota de corretagem ou criar uma funcionalidade de registro de venda manual no banco de dados.")
                        
            else:
                st.info("Nenhum ativo em custódia para ajustar.")

        else:
            st.info("Nenhum ativo em custódia encontrado.")
    else:
        st.info("Nenhuma operação encontrada para exibir os ativos. Faça o upload de um PDF na aba 'Upload PDF'.")
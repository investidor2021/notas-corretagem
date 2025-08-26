# dashboard.py
import streamlit as st
import pandas as pd
import sqlite3

st.set_page_config(page_title="Dashboard de Notas de Corretagem", layout="wide")
st.title("📊 Dashboard de Acompanhamento de Notas de Corretagem")

# Função para carregar dados do banco de dados
def carregar_dados_do_banco(nome_tabela: str) -> pd.DataFrame:
    conn = sqlite3.connect("notas_corretagem.db")
    try:
        df = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
    except pd.io.sql.DatabaseError as e:
        st.warning(f"Tabela '{nome_tabela}' não encontrada ou vazia no banco de dados.")
        df = pd.DataFrame() # Retorna um DataFrame vazio se a tabela não existir
    finally:
        conn.close()
    return df

# --- Carregar e Exibir Dados do Cabeçalho ---
st.subheader("Informações de Cabeçalho das Notas")
df_cabecalho = carregar_dados_do_banco("notas_cabecalho")
if not df_cabecalho.empty:
    st.dataframe(df_cabecalho, use_container_width=True)

    # Filtros e Agrupamentos (Exemplos)
    st.markdown("---")
    st.subheader("Análise de Notas")

    col1, col2 = st.columns(2)
    with col1:
        corretoras_unicas = df_cabecalho['corretora'].unique()
        corretora_selecionada = st.selectbox("Filtrar por Corretora", ["Todas"] + list(corretoras_unicas))
        
        if corretora_selecionada != "Todas":
            df_filtrado = df_cabecalho[df_cabecalho['corretora'] == corretora_selecionada]
            st.write(f"Notas da {corretora_selecionada}:")
            st.dataframe(df_filtrado, hide_index=True)
        else:
            df_filtrado = df_cabecalho

    with col2:
        st.write("Contagem de Notas por Corretora:")
        contagem_corretoras = df_filtrado['corretora'].value_counts().reset_index()
        contagem_corretoras.columns = ['Corretora', 'Quantidade de Notas']
        st.dataframe(contagem_corretoras, hide_index=True)

else:
    st.info("Nenhuma informação de cabeçalho de nota encontrada para exibir.")


# --- Carregar e Exibir Dados de Operações ---
st.markdown("---")
st.subheader("Detalhes das Operações")
df_operacoes = carregar_dados_do_banco("operacoes")
if not df_operacoes.empty:
    st.dataframe(df_operacoes, use_container_width=True)

    # Exemplo de Análise de Operações: Valor total por Tipo Mercado
    st.markdown("##### Resumo de Valores por Tipo de Mercado")
    if 'Tipo Mercado' in df_operacoes.columns and 'Valor' in df_operacoes.columns:
        # Converter 'Valor' para numérico
        df_operacoes['Valor'] = pd.to_numeric(df_operacoes['Valor'], errors='coerce')
        # Remover NaNs que podem surgir da conversão
        df_operacoes.dropna(subset=['Valor'], inplace=True)

        resumo_valor_mercado = df_operacoes.groupby('Tipo Mercado')['Valor'].sum().reset_index()
        st.dataframe(resumo_valor_mercado, hide_index=True)
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

# --- Exibir Resumos Específicos (se existirem e você quiser mantê-los) ---
# st.markdown("---")
# st.subheader("Resumos Específicos dos Parsers")
# df_resumos_especificos = carregar_dados_do_banco("resumos_especificos")
# if not df_resumos_especificos.empty:
#     st.dataframe(df_resumos_especificos, use_container_width=True)
# else:
#     st.info("Nenhum resumo específico de parser encontrado para exibir.")
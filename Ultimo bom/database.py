# database.py
import sqlite3
import pandas as pd
import streamlit as st

DATABASE_NAME = "notas_corretagem.db"

def salvar_em_banco(df: pd.DataFrame, table_name: str):
    """
    Salva um DataFrame em uma tabela SQLite.
    Cria a tabela se não existir.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    try:
        # Use if_exists='append' para adicionar novas linhas
        # O replace='True' recriaria a tabela e apagaria os dados existentes
        df.to_sql(table_name, conn, if_exists='append', index=False)
        st.success(f"Dados salvos com sucesso na tabela '{table_name}'.")
    except Exception as e:
        st.error(f"Erro ao salvar no banco de dados na tabela '{table_name}': {e}")
    finally:
        conn.close()

def nota_existe(numero_nota: str, data_pregao: str, cnpj_corretora: str) -> bool:
    """
    Verifica se uma nota de corretagem com o mesmo número, data e CNPJ já existe.
    """
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    try:
        # Garante que a tabela 'notas_cabecalho' exista antes de tentar consultar
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notas_cabecalho (
                numero_nota TEXT,
                folha TEXT,
                data_pregao TEXT,
                corretora TEXT,
                cnpj TEXT
            )
        """)
        conn.commit() # Salva a criação da tabela se ela não existia

        query = """
            SELECT COUNT(*) FROM notas_cabecalho
            WHERE numero_nota = ? AND data_pregao = ? AND cnpj = ?
        """
        cursor.execute(query, (numero_nota, data_pregao, cnpj_corretora))
        count = cursor.fetchone()[0]
        return count > 0
    except Exception as e:
        st.error(f"Erro ao verificar duplicidade da nota: {e}")
        return False # Assume que não existe para evitar bloqueio
    finally:
        conn.close()

# Função para carregar dados do banco de dados (útil para o dashboard)
def carregar_dados_do_banco(nome_tabela: str) -> pd.DataFrame:
    conn = sqlite3.connect(DATABASE_NAME)
    try:
        df = pd.read_sql_query(f"SELECT * FROM {nome_tabela}", conn)
    except pd.io.sql.DatabaseError as e:
        # st.warning(f"Tabela '{nome_tabela}' não encontrada ou vazia no banco de dados.")
        df = pd.DataFrame() # Retorna um DataFrame vazio se a tabela não existir
    finally:
        conn.close()
    return df
# database.py (Versão ajustada para Google Firestore)

import pandas as pd
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from google.api_core import exceptions

# --- 1. INICIALIZAÇÃO E CONEXÃO COM O FIREBASE ---
# Esta função garante que a conexão seja feita apenas uma vez.

def inicializar_firebase():
    """
    Inicializa a conexão com o Firebase usando as credenciais armazenadas
    nos Secrets do Streamlit. Retorna a instância do cliente do Firestore.
    """
    if not firebase_admin._apps:
        try:
            # Carrega as credenciais a partir dos "Secrets" do Streamlit
            creds_dict = {
              "type": st.secrets["firebase"]["type"],
              "project_id": st.secrets["firebase"]["project_id"],
              "private_key_id": st.secrets["firebase"]["private_key_id"],
              # A chave privada precisa ter as quebras de linha restauradas
              "private_key": st.secrets["firebase"]["private_key"].replace('\\n', '\n'),
              "client_email": st.secrets["firebase"]["client_email"],
              "client_id": st.secrets["firebase"]["client_id"],
              "auth_uri": st.secrets["firebase"]["auth_uri"],
              "token_uri": st.secrets["firebase"]["token_uri"],
              "auth_provider_x509_cert_url": st.secrets["firebase"]["auth_provider_x509_cert_url"],
              "client_x509_cert_url": st.secrets["firebase"]["client_x509_cert_url"]
            }
            creds = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(creds)
        except Exception as e:
            st.error(f"Falha ao inicializar o Firebase. Verifique seus Secrets: {e}")
            return None
            
    return firestore.client()

# Inicializa o cliente do Firestore
db = inicializar_firebase()


# --- 2. FUNÇÃO 'salvar_em_banco' ---
# Lógica: Itera sobre o DataFrame e salva cada linha como um "documento" no Firestore.

def salvar_em_banco(df: pd.DataFrame, collection_name: str):
    """
    Salva cada linha de um DataFrame como um documento em uma coleção do Firestore.
    """
    if db is None or df.empty:
        st.warning(f"Conexão com o banco de dados falhou ou não há dados para salvar em '{collection_name}'.")
        return

    records = df.to_dict('records')
    
    for record in records:
        try:
            # Converte tipos de dados que não são nativos do JSON (ex: Timestamps do Pandas)
            for key, value in record.items():
                if pd.isna(value):
                    record[key] = None # Converte NaT/NaN para None
                elif isinstance(value, pd.Timestamp):
                    record[key] = value.to_pydatetime()
            
            # Adiciona o documento à coleção (o Firestore gerará um ID único)
            db.collection(collection_name).add(record)
        except Exception as e:
            st.error(f"Erro ao salvar registro na coleção '{collection_name}': {e}")
            st.json(record) # Mostra o registro que causou o erro para depuração
            
    st.success(f"Dados salvos com sucesso na coleção '{collection_name}'.")


# --- 3. FUNÇÃO 'nota_existe' ---
# Lógica: Faz uma consulta na coleção 'notas_cabecalho' buscando por documentos
# que correspondam aos três campos-chave.

def nota_existe(numero_nota: str, data_pregao: str, cnpj_corretora: str) -> bool:
    """
    Verifica se uma nota de corretagem com o mesmo número, data e CNPJ já existe no Firestore.
    """
    if db is None:
        st.error("Conexão com o banco de dados indisponível para verificar duplicidade.")
        return False

    try:
        collection_ref = db.collection("notas_cabecalho")
        query = collection_ref.where('numero_nota', '==', numero_nota)\
                              .where('data_pregao', '==', data_pregao)\
                              .where('cnpj', '==', cnpj_corretora)\
                              .limit(1) # Basta encontrar 1 para saber que existe
        
        # Se a consulta retornar qualquer documento, a nota já existe
        docs = list(query.stream())
        return len(docs) > 0
    except exceptions.NotFound:
        # A coleção ainda não existe, então a nota definitivamente não existe.
        return False
    except Exception as e:
        st.error(f"Erro ao verificar duplicidade da nota no Firestore: {e}")
        return False # Assume que não existe para não bloquear o upload


# --- 4. FUNÇÃO 'carregar_dados_do_banco' ---
# Lógica: Busca todos os "documentos" de uma "coleção" e os transforma em um DataFrame.

def carregar_dados_do_banco(nome_tabela: str) -> pd.DataFrame:
    """
    Carrega todos os documentos de uma coleção do Firestore e retorna como um DataFrame.
    (O parâmetro foi mantido como 'nome_tabela' para compatibilidade com o resto do app).
    """
    if db is None:
        return pd.DataFrame()

    try:
        docs_ref = db.collection(nome_tabela).stream()
        docs_list = [doc.to_dict() for doc in docs_ref]
        
        if not docs_list:
            return pd.DataFrame() # Retorna DataFrame vazio se a coleção estiver vazia
            
        return pd.DataFrame(docs_list)
    except exceptions.NotFound:
        # A coleção não existe, o que é normal na primeira execução
        return pd.DataFrame()
    except Exception as e:
        st.error(f"Erro ao carregar dados da coleção '{nome_tabela}': {e}")
        return pd.DataFrame()
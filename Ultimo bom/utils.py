# utils.py
import pandas as pd
import os
import streamlit as st
import re # Adicione este import

def carregar_dados_corretoras(filename="corretoras_cnpj.csv"):
    """
    Carrega os dados das corretoras a partir de um arquivo CSV de forma robusta,
    tentando detectar automaticamente o separador (vírgula ou ponto e vírgula).
    Retorna um DataFrame vazio com as colunas corretas se o arquivo não existir ou estiver mal formatado.
    """
    # Define a estrutura esperada do DataFrame para usar como fallback.
    df_fallback = pd.DataFrame(columns=["Nome", "CNPJ"])

    if not os.path.exists(filename):
        st.warning(f"Arquivo '{filename}' não encontrado. A identificação da corretora pode falhar.")
        return df_fallback

    # Verifica se o arquivo está vazio para evitar erros de leitura do pandas
    if os.path.getsize(filename) == 0:
        st.warning(f"Arquivo '{filename}' está vazio. Nenhuma corretora será carregada.")
        return df_fallback

    try:
        # Tenta ler primeiro com vírgula, que é o padrão mais comum
        df = pd.read_csv(filename, sep=',', encoding='utf-8')
        
        # Se as colunas não forem encontradas, tenta ler com ponto e vírgula
        if "Nome" not in df.columns or "CNPJ" not in df.columns:
            df = pd.read_csv(filename, sep=';', encoding='utf-8')

        # Validação final: Verifica se as colunas esperadas existem após as tentativas
        if "Nome" not in df.columns or "CNPJ" not in df.columns:
            st.error(
                f"O arquivo '{filename}' não tem as colunas esperadas ('Nome', 'CNPJ'). "
                f"Verifique se a primeira linha do arquivo é 'Nome,CNPJ' ou 'Nome;CNPJ' e se o conteúdo está correto."
            )
            return df_fallback
            
        return df

    except Exception as e:
        st.error(f"Ocorreu um erro ao processar o arquivo CSV '{filename}': {e}")
        st.info("Por favor, verifique se o arquivo está salvo no formato CSV com codificação UTF-8.")
        return df_fallback

def separar_notas(texto):
    """Divide o texto do PDF em blocos, um para cada nota."""
    # Usamos uma regex para encontrar "NOTA DE CORRETAGEM" ou "NOTA DE NEGOCIACAO"
    # ou "Recibo de Projeção" ou "Demonstrativo de Custos"
    # Ajustei para capturar múltiplos tipos de cabeçalho que indicam uma nova nota/documento
    regex_inicio_nota = re.compile(r"(?=NOTA DE CORRETAGEM|NOTA DE NEGOCIACAO|RECIBO DE PROJECAO|DEMONSTRATIVO DE CUSTOS)")
    posicoes = [m.start() for m in regex_inicio_nota.finditer(texto)]

    if not posicoes:
        # Se não encontrar nenhum cabeçalho de nota, assume que o texto inteiro é uma única nota
        return [texto]

    blocos = []
    for i in range(len(posicoes)):
        inicio = posicoes[i]
        fim = posicoes[i + 1] if i + 1 < len(posicoes) else len(texto)
        bloco = texto[inicio:fim].strip()
        if bloco: # Garante que blocos vazios não sejam adicionados
            blocos.append(bloco)

    return blocos
# cm_capital_parser.py
import re
import pandas as pd
from .base_parser import BaseParser

class CMCapitalParser(BaseParser):
    NOME_CORRETORA = "CM Capital"

    def extrair_info_cabecalho(self) -> dict:
        # self.texto JÁ É o texto de uma única nota agora
        return self._parse_cabecalho_de_nota(self.texto)

    def _parse_cabecalho_de_nota(self, texto_nota: str) -> dict:
        info = {
            "numero_nota": "N/A", "folha": "N/A", "data_pregao": "N/A",
            "corretora": self.NOME_CORRETORA, "cnpj": "Não encontrado",
        }

        match = re.search(r"Nr\.\s+nota\s+Folha\s+Data\s+pregão\s*\n\s*([\d\.]+)\s+([\d\s/]+)\s+([\d/]+)", texto_nota)
        if match:
            info["numero_nota"], info["folha"], info["data_pregao"] = match.group(1).replace(".", ""), match.group(2).strip(), match.group(3).strip()

        match_cnpj_corretora = re.search(r'Corretora\s+C\.N\.P\.J\.\s+([\d./-]+)', texto_nota, re.DOTALL)
        if not match_cnpj_corretora: # Fallback
             match_cnpj_corretora = re.search(r'C\.N\.P\.J\.\s+([\d./-]+)', texto_nota)
        if match_cnpj_corretora:
            info["cnpj"] = match_cnpj_corretora.group(1).strip()
        
        return info

    def _parse_operacoes_de_nota(self, texto_nota: str, info_cabecalho: dict) -> list:
        negociacoes_da_nota = []
        
        # AQUI, estamos buscando dentro do bloco de UMA NOTA
        operacoes_block_match = re.search(r"Vlr\.\s+de\s+Operação\s+/\s+AjusteD/C\s*\n(.*?)(?=Resumo dos Negócios|Total da Nota)", texto_nota, re.DOTALL | re.IGNORECASE) # Adicionado "Total da Nota" como delimitador
        if not operacoes_block_match:
            return []

        for linha in operacoes_block_match.group(1).strip().split('\n'):
            linha_limpa = linha.strip()
            if not linha_limpa or len(linha_limpa.split()) < 4: continue

            match = re.search(r'^(.*?)\s+(\d[\d\.]*)\s+([\d,]+)\s+([\d,]+[CD])$', linha_limpa)
            if match:
                try:
                    especificacao_completa, qtd_str, preco_str, valor_dc_str = match.groups()
                    especificacao_completa = especificacao_completa.strip()

                    tipo_mercado_str, negociacao_str, titulo_str, vencimento_str, obs_str = "VISTA", "", especificacao_completa, "", ""
                    
                    mercado_pattern = r'\s(VISTA|OPCAO DE COMPRA|OPCAO DE VENDA)\s'
                    mercado_match = re.search(mercado_pattern, especificacao_completa)
                    
                    if mercado_match:
                        tipo_mercado_str = mercado_match.group(1)
                        parts = re.split(mercado_pattern, especificacao_completa, 1)
                        negociacao_str = parts[0].strip()
                        resto = parts[2].strip()

                        if "OPCAO" in tipo_mercado_str:
                            opcao_match = re.search(r'^(\d{2}/\d{2})\s+(.*?)\s+([\d,]+\s+.*)$', resto)
                            if opcao_match:
                                vencimento_raw, titulo_str, obs_str = opcao_match.groups()
                                mes, ano = vencimento_raw.split('/')
                                vencimento_str = f"{mes}/20{ano}" 
                            else:
                                titulo_str = resto 
                        else:
                            titulo_str = resto
                    
                    negociacoes_da_nota.append({
                        "Numero Nota": info_cabecalho.get('numero_nota'),
                        "Data Pregao": info_cabecalho.get('data_pregao'),
                        "Corretora": info_cabecalho.get('corretora'), 
                        "CNPJ": info_cabecalho.get('cnpj'), 
                        "Negociacao": negociacao_str,
                        "Tipo Mercado": tipo_mercado_str,
                        "Vencimento": vencimento_str,
                        "Titulo": titulo_str,
                        "Obs": obs_str,
                        "Quantidade": int(qtd_str.replace('.', '')),
                        "Preço": float(preco_str.replace(".", "").replace(",", ".")),
                        "Valor": float(valor_dc_str[:-1].replace(".", "").replace(",", ".")),
                        "D/C": valor_dc_str[-1],
                    })
                except (ValueError, IndexError) as e:
                    print(f"Linha ignorada no parser de operações: {linha_limpa} | Erro: {e}")
                    continue
        return negociacoes_da_nota

    def extrair_operacoes(self) -> pd.DataFrame:
        # A lógica de iterar sobre blocos é feita em app.py
        # self.texto já é o texto de uma única nota.
        info_cabecalho = self.extrair_info_cabecalho()
        operacoes_da_nota = self._parse_operacoes_de_nota(self.texto, info_cabecalho)
        return pd.DataFrame(operacoes_da_nota)

    def extrair_resumo(self) -> pd.DataFrame:
        # TODO: Implementar a extração do resumo para o formato de colunas fixas para CM Capital.
        return pd.DataFrame()
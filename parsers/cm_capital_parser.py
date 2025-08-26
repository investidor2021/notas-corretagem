import re
import pandas as pd
from .base_parser import BaseParser
from utils import parse_br_float # Importe a nova função

class CMCapitalParser(BaseParser):
    NOME_CORRETORA = "CM Capital"

    def extrair_info_cabecalho(self) -> dict:
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
        if not match_cnpj_corretora:
             match_cnpj_corretora = re.search(r'C\.N\.P\.J\.\s+([\d./-]+)', texto_nota)
        if match_cnpj_corretora:
            info["cnpj"] = match_cnpj_corretora.group(1).strip()
        
        return info

    def _parse_operacoes_de_nota(self, texto_nota: str, info_cabecalho: dict) -> list:
        negociacoes_da_nota = []
        
        operacoes_block_match = re.search(r"Vlr\.\s+de\s+Operação\s+/\s+AjusteD/C\s*\n(.*?)(?=Resumo dos Negócios|Total da Nota)", texto_nota, re.DOTALL | re.IGNORECASE)
        if not operacoes_block_match:
            return []

        for linha in operacoes_block_match.group(1).strip().split('\n'):
            linha_limpa = ' '.join(linha.strip().split())
            if not linha_limpa or len(linha_limpa.split()) < 4: continue

            match = re.search(r'^(.*?)\s+([\d\.]+)\s+([\d.,:]+)\s+([\d.,:]+)\s*([CD])$', linha_limpa)
            if match:
                try:
                    especificacao_completa, qtd_str, preco_str, valor_str, tipo_dc_str = match.groups()
                    especificacao_completa = especificacao_completa.strip()

                    # USANDO NOVA FUNÇÃO
                    qtd = int(parse_br_float(qtd_str))
                    preco = parse_br_float(preco_str)
                    valor = parse_br_float(valor_str)
                    
                    # --- Lógica de Fragmentação ---
                    tipo_mercado_str, negociacao_str, titulo_str, vencimento_str, obs_str = "VISTA", "", especificacao_completa, "", ""
                    
                    mercado_pattern = r'\s(VISTA|OPCAO DE COMPRA|OPCAO DE VENDA)\s'
                    mercado_match = re.search(mercado_pattern, especificacao_completa, re.IGNORECASE)
                    
                    if mercado_match:
                        tipo_mercado_str = mercado_match.group(1).upper()
                        parts = re.split(mercado_pattern, especificacao_completa, 1, re.IGNORECASE)
                        negociacao_str = parts[0].strip()
                        resto = parts[2].strip()

                        if "OPCAO" in tipo_mercado_str:
                            opcao_match = re.search(r'^(\d{2}/\d{2})\s+(.*?)(?:\s+([\d,.:]+\s+.*))?$', resto)
                            if opcao_match:
                                vencimento_raw, titulo_str, obs_raw = opcao_match.groups()
                                obs_str = obs_raw.strip() if obs_raw else ""
                                mes, ano = vencimento_raw.split('/')
                                vencimento_str = f"{mes}/20{ano}"
                            else:
                                titulo_str = resto
                        else:
                            titulo_str = resto
                    else:
                         titulo_str = especificacao_completa
                         
                    # --- Fim da Fragmentação ---

                    negociacoes_da_nota.append({
                        "Numero Nota": info_cabecalho.get('numero_nota'),
                        "Data Pregao": info_cabecalho.get('data_pregao'),
                        "Corretora": info_cabecalho.get('corretora'),
                        "CNPJ": info_cabecalho.get('cnpj'),
                        "Negociacao": negociacao_str,
                        "Tipo Mercado": tipo_mercado_str,
                        "Vencimento": vencimento_str,
                        "Titulo": titulo_str, # Usar 'Titulo' consistentemente
                        "Obs": obs_str,
                        "Quantidade": qtd,
                        "Preço": preco,
                        "Valor": valor,
                        "D/C": tipo_dc_str,
                    })
                except (ValueError, IndexError) as e:
                    # print(f"Linha ignorada no parser de operações CM Capital: {linha_limpa} | Erro: {e}")
                    continue
        return negociacoes_da_nota

    def extrair_operacoes(self) -> pd.DataFrame:
        info_cabecalho = self.extrair_info_cabecalho()
        operacoes_da_nota = self._parse_operacoes_de_nota(self.texto, info_cabecalho)
        return pd.DataFrame(operacoes_da_nota)

    def extrair_resumo(self) -> pd.DataFrame:
        return pd.DataFrame()
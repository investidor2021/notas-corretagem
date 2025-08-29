import re
import pandas as pd
from .base_parser import BaseParser
from utils import parse_br_float

class ToroParser(BaseParser):
    NOME_CORRETORA = "Toro"

    def extrair_info_cabecalho(self) -> dict:
        return self._parse_cabecalho_de_nota(self.texto)

    def _parse_cabecalho_de_nota(self, texto_nota: str) -> dict:
        info = {
            "numero_nota": "N/A", "folha": "N/A", "data_pregao": "N/A",
            "corretora": self.NOME_CORRETORA, "cnpj": "Não encontrado",
        }

        match = re.search(r"Nr\.?\s*Nota\s+Folha\s+Data\s+pregão\s*\n\s*(\d+)\s+(\d+)\s+([\d/]+)", texto_nota, re.IGNORECASE)
        if match:
            info["numero_nota"], info["folha"], info["data_pregao"] = match.groups()

        match_cnpj_corretora = re.search(r'C\.N\.P\.J\.:\s*([\d./-]+)', texto_nota)
        if match_cnpj_corretora:
            info["cnpj"] = match_cnpj_corretora.group(1).strip()
        
        return info

    def _parse_operacoes_de_nota(self, texto_nota: str, info_cabecalho: dict) -> list:
        negociacoes_da_nota = []
        
        operacoes_block_match = re.search(r"Negócios\s+realizados\s*\n(.*?)(?=\"?Resumo dos Negócios\"?|\nTotal da Nota|\nLíquido para)", texto_nota, re.DOTALL | re.IGNORECASE)
        if not operacoes_block_match:
            return []

        for linha in operacoes_block_match.group(1).strip().splitlines():
            linha_limpa = ' '.join(linha.strip().split())
            if not linha_limpa or 'especificação do titulo' in linha_limpa.lower():
                continue

            match = re.search(r'^(.*?)\s+([\d\.]+)\s+([\d.,:]+)\s+([\d.,:]+)\s*([CD])$', linha_limpa, re.IGNORECASE)
            
            if not match:
                continue

            try:
                especificacao_completa, qtd_str, preco_str, valor_str, tipo_operacao = match.groups()
                
                especificacao_completa = re.sub(r'B3 RV\s*', '', especificacao_completa, flags=re.IGNORECASE).strip()

                tipo_mercado_str, negociacao_str, titulo_str, vencimento_str, obs_str = "VISTA", "", especificacao_completa.strip(), "", ""
                
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
                    "Quantidade": int(parse_br_float(qtd_str)),
                    "Preço": parse_br_float(preco_str),
                    "Valor": parse_br_float(valor_str),
                    "D/C": tipo_operacao,
                })
            except (ValueError, IndexError) as e:
                continue
        return negociacoes_da_nota

    def extrair_operacoes(self) -> pd.DataFrame:
        info_cabecalho = self.extrair_info_cabecalho()
        operacoes_da_nota = self._parse_operacoes_de_nota(self.texto, info_cabecalho)
        return pd.DataFrame(operacoes_da_nota)

    def extrair_resumo(self) -> pd.DataFrame:
        resumos = []
        match = re.search(r"Resumo dos Neg[óo]cios\n((?:.+\n)+?)Valor das opera[çc][õo]es\s+([0-9.,]+)", self.texto, re.IGNORECASE | re.DOTALL)

        if match:
            bloco = match.group(1)
            total_operacoes = match.group(2)
            
            for linha in bloco.strip().split("\n"):
                campos = re.search(r"(.+?)\s+([0-9.,]+)\s*([CD]?)$", linha.strip())
                if campos:
                    try:
                        descricao = re.sub(r'\s{2,}', ' ', campos.group(1).strip())
                        valor = parse_br_float(campos.group(2))
                        resumos.append({
                            "Numero Nota": self.info_cabecalho.get('numero_nota'),
                            "Data Pregao": self.info_cabecalho.get('data_pregao'),
                            "Descrição": descricao,
                            "Valor": valor
                        })
                    except (ValueError, IndexError):
                        continue
            
            resumos.append({
                "Numero Nota": self.info_cabecalho.get('numero_nota'),
                "Data Pregao": self.info_cabecalho.get('data_pregao'),
                "Descrição": "Valor das operações",
                "Valor": parse_br_float(total_operacoes)
            })

        match_taxas = re.search(r"Taxa de liquidação\s+([0-9.,]+)", self.texto, re.IGNORECASE)
        if match_taxas:
            resumos.append({
                "Numero Nota": self.info_cabecalho.get('numero_nota'),
                "Data Pregao": self.info_cabecalho.get('data_pregao'),
                "Descrição": "Taxa de liquidação",
                "Valor": parse_br_float(match_taxas.group(1))
            })

        match_emolumentos = re.search(r"Emolumentos\s+([0-9.,]+)", self.texto, re.IGNORECASE)
        if match_emolumentos:
            resumos.append({
                "Numero Nota": self.info_cabecalho.get('numero_nota'),
                "Data Pregao": self.info_cabecalho.get('data_pregao'),
                "Descrição": "Emolumentos",
                "Valor": parse_br_float(match_emolumentos.group(1))
            })

        match_irrf = re.search(r"I\.R\.R\.F\.\s+s/\s+operações\s+([0-9.,]+)", self.texto, re.IGNORECASE)
        if match_irrf:
            resumos.append({
                "Numero Nota": self.info_cabecalho.get('numero_nota'),
                "Data Pregao": self.info_cabecalho.get('data_pregao'),
                "Descrição": "IRRF",
                "Valor": parse_br_float(match_irrf.group(1))
            })

        df = pd.DataFrame(resumos)
        if not df.empty:
            df = df[["Numero Nota", "Data Pregao", "Descrição", "Valor"]]
            df = df.drop_duplicates()
            
        return df

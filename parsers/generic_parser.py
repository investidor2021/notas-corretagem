import re
import pandas as pd
from .base_parser import BaseParser
from utils import parse_br_float

class GenericParser(BaseParser):
    NOME_CORRETORA = "Genérico"

    def extrair_info_cabecalho(self) -> dict:
        info = {
            "numero_nota": "N/A",
            "folha": "N/A",
            "data_pregao": "N/A",
            "corretora": "Desconhecida",
            "cnpj": "Não encontrado"
        }

        for _, row in self.df_corretoras.iterrows():
            if re.search(r'\b' + re.escape(row["Nome"]) + r'\b', self.texto, re.IGNORECASE):
                info["corretora"] = row["Nome"]
                info["cnpj"] = row["CNPJ"]
                break
        
        if info["corretora"] == "Desconhecida":
            match_corretora = re.search(r'\n([A-Z\s.,-]+(?:CORRETORA|CCTVM|DTVM)[\s\S]*?LTDA)', self.texto, re.IGNORECASE)
            if match_corretora:
                info["corretora"] = match_corretora.group(1).strip().title()

        match_header = re.search(
            r"(?:Nr\. nota\s+Folha\s+Data pregão|Data pregão\s*Folha\s*Nr\. ?Nota)\s*\n?(\d{2}/\d{2}/\d{4})\s+(\d+)\s+([\d.]+)|([\d.]+)\s+([\d/ ]+)\s+(\d{2}/\d{2}/\d{4})",
            self.texto
        )
        if match_header:
            if match_header.group(1): # Layout 1
                info["data_pregao"] = match_header.group(1)
                info["folha"] = match_header.group(2)
                info["numero_nota"] = match_header.group(3).replace(".", "")
            else: # Layout 2
                info["numero_nota"] = match_header.group(4).replace(".", "")
                info["folha"] = match_header.group(5).strip()
                info["data_pregao"] = match_header.group(6)
        
        return info

    def extrair_operacoes(self) -> pd.DataFrame:
        negociacoes = []
        for linha in self.linhas:
            if "B3 RV" not in linha:
                continue
            
            linha_limpa = ' '.join(linha.strip().split())

            # Regex para capturar Spec, Qtd, Preço, Valor e D/C.
            match = re.search(r'^(.*?)\s+([\d\.]+)\s+([\d.,:]+)\s+([\d.,:]+)\s*([CD])$', linha_limpa, re.IGNORECASE)
            
            if not match:
                continue
            
            try:
                especificacao_completa, qtd_str, preco_str, valor_str, tipo_operacao = match.groups()
                
                especificacao_completa = re.sub(r'B3 RV\s*', '', especificacao_completa, flags=re.IGNORECASE).strip()

                qtd = int(parse_br_float(qtd_str))
                preco = parse_br_float(preco_str)
                valor = parse_br_float(valor_str)

                tipo_mercado = "VISTA"
                prazo = ""
                observacao = ""
                titulo = especificacao_completa

                match_opcao = re.search(r"(OPCAO DE (?:COMPRA|VENDA))\s+(\d{2}/\d{2})\s+(.*)", especificacao_completa, re.IGNORECASE)
                if match_opcao:
                    tipo_mercado = match_opcao.group(1).upper()
                    mes_ano_vencimento = match_opcao.group(2)
                    prazo = f"{mes_ano_vencimento.split('/')[0]}/20{mes_ano_vencimento.split('/')[1]}"
                    titulo = match_opcao.group(3).strip()

                negociacoes.append({
                    "Numero Nota": self.info_cabecalho.get('numero_nota'),
                    "Data Pregao": self.info_cabecalho.get('data_pregao'),
                    "Corretora": self.info_cabecalho.get('corretora'),
                    "CNPJ": self.info_cabecalho.get('cnpj'),
                    "Tipo Mercado": tipo_mercado,
                    "Prazo": prazo,
                    "Titulo": titulo,
                    "Observação": observacao,
                    "Quantidade": qtd,
                    "Preço": preco,
                    "Valor": valor,
                    "D/C": tipo_operacao,
                })
            except Exception as e:
                continue

        return pd.DataFrame(negociacoes)

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

        # Captura de Taxas e IRRF
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

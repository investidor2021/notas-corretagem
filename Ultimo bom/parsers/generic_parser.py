# generic_parser.py
import re
import pandas as pd
from .base_parser import BaseParser

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

        # Tenta encontrar o nome e CNPJ da corretora neste bloco de nota
        for _, row in self.df_corretoras.iterrows():
            if re.search(r'\b' + re.escape(row["Nome"]) + r'\b', self.texto, re.IGNORECASE):
                info["corretora"] = row["Nome"]
                info["cnpj"] = row["CNPJ"]
                break
        
        # Se não achou pelo nome, tenta uma regex mais ampla
        if info["corretora"] == "Desconhecida":
            match_corretora = re.search(r'\n([A-Z\s.,-]+(?:CORRETORA|CCTVM|DTVM)[\s\S]*?LTDA)', self.texto, re.IGNORECASE)
            if match_corretora:
                info["corretora"] = match_corretora.group(1).strip().title()

        # Regex para Nr. nota, Folha, Data pregão (neste bloco de nota)
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
        # Iterar sobre as linhas DESTE BLOCO de nota
        for linha in self.linhas: 
            if "B3 RV" not in linha:
                continue
            
            try:
                partes = linha.strip().split()
                tipo_operacao = partes[-1][-1]
                valor = partes[-1][:-1]
                preco = partes[-2]
                qtd = partes[-3]
                linha_restante = " ".join(partes[:-3])

                match_opcao = re.search(r"(OPCAO DE (?:COMPRA|VENDA))\s+(\d{2}/\d{2})\s+(\S+)\s+(.*)", linha_restante)
                if match_opcao:
                    tipo_mercado = match_opcao.group(1)
                    mes, ano = match_opcao.group(2).split("/")
                    prazo = f"{mes}/20{ano}"
                    especificacao = match_opcao.group(3)
                    observacao = match_opcao.group(4)
                else:
                    tipo_mercado = "VISTA"
                    prazo = ""
                    match_vista = re.search(r"B3 RV\s+(.*?)\s+(VISTA)\s+(.*)", linha_restante, re.IGNORECASE)
                    if match_vista:
                        especificacao = match_vista.group(3).strip().title()
                    else:
                        especificacao = re.sub(r'B3 RV\s+', '', linha_restante).strip().title()
                    observacao = ""

                negociacoes.append({
                    "Numero Nota": self.info_cabecalho.get('numero_nota'),
                    "Data Pregao": self.info_cabecalho.get('data_pregao'),
                    "Tipo Mercado": tipo_mercado,
                    "Prazo": prazo,
                    "Especificação do título": especificacao,
                    "Observação": observacao,
                    "Quantidade": qtd,
                    "Preço": preco,
                    "Valor": valor,
                    "D/C": tipo_operacao,
                })
            except Exception:
                continue

        return pd.DataFrame(negociacoes)

    def extrair_resumo(self) -> pd.DataFrame:
        resumos = []
        # Buscar Resumo dos Negócios NESTE BLOCO de nota
        match = re.search(r"Resumo dos Neg[óo]cios\n((?:.+\n)+?)Valor das opera[çc][õo]es\s+([0-9.,]+)", self.texto, re.IGNORECASE | re.DOTALL)

        if match:
            bloco = match.group(1)
            total_operacoes = match.group(2)
            
            for linha in bloco.strip().split("\n"):
                campos = re.search(r"(.+?)\s+([0-9.,]+)\s*([CD]?)$", linha.strip())
                if campos:
                    try:
                        descricao = re.sub(r'\s{2,}', ' ', campos.group(1).strip())
                        valor = float(campos.group(2).replace(".", "").replace(",", "."))
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
                "Valor": float(total_operacoes.replace(".", "").replace(",", "."))
            })

        df = pd.DataFrame(resumos)
        if not df.empty:
            df = df[["Numero Nota", "Data Pregao", "Descrição", "Valor"]]
            df = df.drop_duplicates()
            
        return df
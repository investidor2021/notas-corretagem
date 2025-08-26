import re
import pandas as pd
from .base_parser import BaseParser

class CMCapitalParser(BaseParser):
    """
    Parser específico para notas de corretagem da CM Capital.
    - Suporta múltiplos pregões (notas) em um único arquivo PDF.
    - Fragmenta os dados da operação em colunas mais detalhadas, incluindo dados da corretora.
    """
    NOME_CORRETORA = "CM Capital"

    def extrair_info_cabecalho(self) -> dict:
        """
        Implementa o método abstrato obrigatório.
        Este método é chamado na inicialização, mas a lógica principal de extração
        que lida com múltiplas notas está em `extrair_operacoes`.
        Aqui, apenas garantimos que a classe pode ser instanciada.
        """
        # Apenas para satisfazer o contrato da classe abstrata.
        # A extração real por nota é feita em outros métodos.
        primeira_nota_match = re.search(r'NOTA DE CORRETAGEM(.*?)(?=NOTA DE CORRETAGEM|\Z)', self.texto, re.DOTALL)
        if primeira_nota_match:
            texto_primeira_nota = primeira_nota_match.group(0)
            return self._parse_cabecalho_de_nota(texto_primeira_nota)
        return self._parse_cabecalho_de_nota(self.texto) # Fallback

    def _parse_cabecalho_de_nota(self, texto_nota: str) -> dict:
        """Extrai informações do cabeçalho de uma única nota de corretagem."""
        info = {
            "numero_nota": "N/A", "folha": "N/A", "data_pregao": "N/A",
            "Nome Corretora": self.NOME_CORRETORA, "CNPJ Corretora": "Não encontrado",
        }

        match = re.search(r"Nr\.\s+nota\s+Folha\s+Data\s+pregão\s*\n\s*([\d\.]+)\s+([\d\s/]+)\s+([\d/]+)", texto_nota)
        if match:
            info["numero_nota"], info["folha"], info["data_pregao"] = match.group(1).replace(".", ""), match.group(2).strip(), match.group(3).strip()

        match_cnpj_corretora = re.search(r'Corretora\s+C\.N\.P\.J\.\s+([\d./-]+)', texto_nota, re.DOTALL)
        if not match_cnpj_corretora: # Fallback
             match_cnpj_corretora = re.search(r'C\.N\.P\.J\.\s+([\d./-]+)', texto_nota)
        if match_cnpj_corretora:
            info["CNPJ Corretora"] = match_cnpj_corretora.group(1).strip()
        
        return info

    def _parse_operacoes_de_nota(self, texto_nota: str, info_cabecalho: dict) -> list:
        """Extrai e fragmenta as operações de uma única nota de corretagem."""
        negociacoes_da_nota = []
        
        operacoes_block_match = re.search(r"Vlr\.\s+de\s+Operação\s+/\s+AjusteD/C\s*\n(.*?)(?=Resumo dos Negócios)", texto_nota, re.DOTALL | re.IGNORECASE)
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

                    # --- Lógica de Fragmentação Aprimorada ---
                    tipo_mercado_str, negociacao_str, titulo_str, vencimento_str, obs_str = "VISTA", "", especificacao_completa, "", ""
                    
                    mercado_pattern = r'\s(VISTA|OPCAO DE COMPRA|OPCAO DE VENDA)\s'
                    mercado_match = re.search(mercado_pattern, especificacao_completa)
                    
                    if mercado_match:
                        tipo_mercado_str = mercado_match.group(1)
                        parts = re.split(mercado_pattern, especificacao_completa, 1)
                        negociacao_str = parts[0].strip()
                        resto = parts[2].strip()

                        # Se for opção, tenta fragmentar ainda mais
                        if "OPCAO" in tipo_mercado_str:
                            opcao_match = re.search(r'^(\d{2}/\d{2})\s+(.*?)\s+([\d,]+\s+.*)$', resto)
                            if opcao_match:
                                vencimento_raw, titulo_str, obs_str = opcao_match.groups()
                                mes, ano = vencimento_raw.split('/')
                                vencimento_str = f"{mes}/20{ano}" # Formato AAAA
                            else:
                                titulo_str = resto # Fallback
                        else:
                            titulo_str = resto
                    # --- Fim da Fragmentação ---

                    negociacoes_da_nota.append({
                        "Numero Nota": info_cabecalho.get('numero_nota'),
                        "Data Pregao": info_cabecalho.get('data_pregao'),
                        "Nome Corretora": info_cabecalho.get('Nome Corretora'),
                        "CNPJ Corretora": info_cabecalho.get('CNPJ Corretora'),
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
        """Orquestra a extração de operações de todas as notas no arquivo."""
        todas_as_operacoes = []
        blocos_de_nota = re.split(r'(?=NOTA DE CORRETAGEM)', self.texto)

        for bloco in blocos_de_nota:
            if "NOTA DE CORRETAGEM" not in bloco: continue
            
            info_cabecalho = self._parse_cabecalho_de_nota(bloco)
            operacoes_da_nota = self._parse_operacoes_de_nota(bloco, info_cabecalho)
            todas_as_operacoes.extend(operacoes_da_nota)
            
        return pd.DataFrame(todas_as_operacoes)

    def extrair_resumo(self) -> pd.DataFrame:
        """Orquestra a extração do resumo de todas as notas no arquivo."""
        # TODO: Implementar a extração do resumo para o formato de colunas fixas.
        return pd.DataFrame()
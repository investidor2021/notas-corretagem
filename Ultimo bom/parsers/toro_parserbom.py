import re
import pandas as pd
from .base_parser import BaseParser

class ToroParser(BaseParser):
    """
    Parser específico para notas de corretagem da Toro Investimentos.
    - Suporta múltiplos pregões (notas) em um único arquivo PDF.
    - Fragmenta os dados da operação em colunas detalhadas.
    - Lida com múltiplos formatos de separadores decimais e de milhar.
    """
    NOME_CORRETORA = "Toro"

    def _parse_float_robust(self, value_str: str) -> float:
        """
        Converte uma string para float de forma robusta, lidando com os
        separadores de milhar ('.' e ':') e decimal (',' ou '.').
        """
        # Remove separadores de milhar e substitui o separador decimal por ponto.
        cleaned_str = value_str.replace('.', '').replace(':', '').replace(',', '.')
        # Se a vírgula era o decimal, a lógica acima já resolveu.
        # Se o ponto era o decimal, a lógica também funciona se não houver separador de milhar.
        # Para casos como '1.43', o replace inicial não faz nada e o float() funciona.
        # A lógica é um pouco complexa, mas cobre os casos da Toro.
        # Uma forma mais segura é tratar os casos explicitamente.
        if ',' in value_str:
            return float(value_str.replace('.', '').replace(':', '').replace(',', '.'))
        return float(value_str.replace(':', ''))


    def extrair_info_cabecalho(self) -> dict:
        """
        Implementa o método abstrato obrigatório.
        A lógica principal de extração está em `extrair_operacoes`.
        """
        primeira_nota_match = re.search(r'NOTA DE CORRETAGEM(.*?)(?=NOTA DE CORRETAGEM|\Z)', self.texto, re.DOTALL)
        if primeira_nota_match:
            texto_primeira_nota = primeira_nota_match.group(0)
            return self._parse_cabecalho_de_nota(texto_primeira_nota)
        return self._parse_cabecalho_de_nota(self.texto)

    def _parse_cabecalho_de_nota(self, texto_nota: str) -> dict:
        """Extrai informações do cabeçalho de uma única nota de corretagem."""
        info = {
            "numero_nota": "N/A", "folha": "N/A", "data_pregao": "N/A",
            "Nome Corretora": self.NOME_CORRETORA, "CNPJ Corretora": "Não encontrado",
        }

        # CORREÇÃO: Regex mais flexível para o cabeçalho, aceitando "Nr.Nota" ou "Nr. Nota"
        match = re.search(r"Nr\.?\s*Nota\s+Folha\s+Data\s+pregão\s*\n\s*(\d+)\s+(\d+)\s+([\d/]+)", texto_nota, re.IGNORECASE)
        if match:
            info["numero_nota"], info["folha"], info["data_pregao"] = match.groups()

        match_cnpj_corretora = re.search(r'C\.N\.P\.J\.:\s*([\d./-]+)', texto_nota)
        if match_cnpj_corretora:
            info["CNPJ Corretora"] = match_cnpj_corretora.group(1).strip()
        
        return info

    def _parse_operacoes_de_nota(self, texto_nota: str, info_cabecalho: dict) -> list:
        """Extrai e fragmenta as operações de uma única nota de corretagem."""
        negociacoes_da_nota = []
        
        # Regex mais flexível para encontrar o bloco de operações.
        operacoes_block_match = re.search(r"Negócios\s+realizados\s*\n(.*?)(?=\"?Resumo dos Negócios\"?)", texto_nota, re.DOTALL | re.IGNORECASE)
        if not operacoes_block_match:
            return []

        # Usar splitlines() para lidar com diferentes tipos de quebra de linha.
        for linha in operacoes_block_match.group(1).strip().splitlines():
            linha_limpa = ' '.join(linha.strip().split())
            if not linha_limpa or 'especificação do titulo' in linha_limpa.lower():
                continue

            # Regex mais robusta para incluir ':' como separador.
            match = re.search(r'^(.*?)\s+([\d,.:]+)\s+([\d,.:]+)\s+([\d,.:]+\s*[CD])$', linha_limpa, re.IGNORECASE)
            
            if match:
                try:
                    especificacao_completa, qtd_str, preco_str, valor_dc_str = match.groups()
                    
                    # --- Lógica de Fragmentação ---
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
                        "Quantidade": int(self._parse_float_robust(qtd_str)),
                        "Preço": self._parse_float_robust(preco_str),
                        "Valor": self._parse_float_robust(valor_dc_str.strip().split()[0]),
                        "D/C": valor_dc_str.strip().split()[-1].upper(),
                    })
                except (ValueError, IndexError) as e:
                    print(f"Linha ignorada no parser de operações da Toro: {linha_limpa} | Erro: {e}")
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
        # TODO: Implementar a extração do resumo para a corretora Toro.
        return pd.DataFrame()

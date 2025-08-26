from abc import ABC, abstractmethod
import pandas as pd

class BaseParser(ABC):
    """
    Classe base abstrata para parsers de notas de corretagem.
    Define a interface que todos os parsers específicos de corretora devem implementar.
    """
    NOME_CORRETORA = "Base"

    def __init__(self, texto_completo: str, df_corretoras: pd.DataFrame):
        """
        Inicializa o parser com o texto completo da nota e o DataFrame de corretoras.
        """
        self.texto = texto_completo
        self.linhas = texto_completo.split('\n')
        self.df_corretoras = df_corretoras
        self.info_cabecalho = self.extrair_info_cabecalho()

    @abstractmethod
    def extrair_info_cabecalho(self) -> dict:
        """
        Extrai informações do cabeçalho da nota, como número da nota, data e dados da corretora.
        Deve retornar um dicionário.
        Ex: {'numero_nota': '123', 'data_pregao': '01/01/2024', 'corretora': 'XP', 'cnpj': '...'}
        """
        pass

    @abstractmethod
    def extrair_operacoes(self) -> pd.DataFrame:
        """
        Extrai a tabela de operações (compra/venda) da nota.
        Deve retornar um DataFrame do pandas.
        """
        pass

    @abstractmethod
    def extrair_resumo(self) -> pd.DataFrame:
        """
        Extrai a tabela de resumo financeiro da nota (taxas, impostos, etc.).
        Deve retornar um DataFrame do pandas.
        """
        pass
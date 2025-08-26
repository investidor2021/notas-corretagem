from .base_parser import BaseParser
from .generic_parser import GenericParser
# Para adicionar uma nova corretora, importe o parser dela aqui.
from .cm_capital_parser import CMCapitalParser
from .toro_parser import ToroParser 
# from .xp_parser import XPParser 
# from .clear_parser import ClearParser


def get_parser_for_text(texto_completo: str, df_corretoras) -> BaseParser:
    """
    Analisa o texto da nota de corretagem e retorna a instância do parser apropriado.

    Args:
        texto_completo: O texto extraído de todas as páginas do PDF.
        df_corretoras: DataFrame com nomes e CNPJs das corretoras.

    Returns:
        Uma instância de um parser que herda de BaseParser.
    """
    texto_lower = texto_completo.lower()

    # Adicione aqui a lógica para identificar outras corretoras.
    # O primeiro match vence, então coloque os mais específicos primeiro.
    # Usar o CNPJ é mais confiável que o nome.
    if "29.162.769/0001-98" in texto_completo or "toro corretora" in texto_lower:
        return ToroParser(texto_completo, df_corretoras)
    if "cm capital markets" in texto_lower:
        return CMCapitalParser(texto_completo, df_corretoras)
        
    # Exemplo (descomente quando criar os parsers específicos):
    # if "xp investimentos" in texto_lower:
    #     return XPParser(texto_completo, df_corretoras)
    # if "clear corretora" in texto_lower:
    #     return ClearParser(texto_completo, df_corretoras)

    # Se nenhuma corretora específica for identificada, usa o parser genérico.
    return GenericParser(texto_completo, df_corretoras)
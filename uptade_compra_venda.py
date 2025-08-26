import sqlite3
import pandas as pd

DB_PATH = "notas_corretagem.db"  # Ajuste para o caminho correto

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. Cria a coluna se não existir
try:
    cursor.execute("ALTER TABLE operacoes ADD COLUMN CompraVenda TEXT")
except sqlite3.OperationalError:
    print("Coluna CompraVenda já existe.")

# 2. Ler dados atuais
query = "SELECT rowid, * FROM operacoes"
df = pd.read_sql_query(query, conn)

def detectar_compra_venda(linha: str, tipo_dc: str) -> str:
    if not isinstance(linha, str):
        linha = ""
    linha_upper = linha.upper()
    if 'LISTADV' in linha_upper or 'LISTADVO' in linha_upper:
        return 'V'
    return tipo_dc

# 3. Atualiza DataFrame
if 'CompraVenda' not in df.columns:
    df['CompraVenda'] = df.apply(lambda x: detectar_compra_venda(str(x.get('Negociacao') or x.get('Obs') or ''), x['D/C']), axis=1)
else:
    df['CompraVenda'] = df.apply(lambda x: x['CompraVenda'] or detectar_compra_venda(str(x.get('Negociacao') or x.get('Obs') or ''), x['D/C']), axis=1)

# 4. Persistir alterações
for idx, row in df.iterrows():
    conn.execute("UPDATE operacoes SET CompraVenda=? WHERE rowid=?", (row['CompraVenda'], row['rowid']))

conn.commit()
conn.close()
print("Banco atualizado com coluna CompraVenda preenchida!")

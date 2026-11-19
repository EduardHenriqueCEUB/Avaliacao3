"""
criar_banco.py

PASSO 4 do projeto: criar o banco de dados da API (data/banco.db) e
preencher com os 350 mil usuários e 5,1 milhões de avaliações da base.

Depois disso, a API passa a ler e gravar usuários e avaliações no banco.
Assim, um usuário da base pode receber recomendações e também alterar as
avaliações dele, do mesmo jeito que um usuário criado pela API.

Como rodar (na pasta raiz do projeto, com o venv ativo):
    python scripts/criar_banco.py

Leva menos de 1 minuto e gera um arquivo de uns 100 MB.

ATENÇÃO: se o banco já existir, o script não faz nada, para não apagar o
que foi criado pela API. Para recriar do zero, apague data/banco.db antes.
"""

import os
import sys
import time

import pandas as pd

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_PROJETO)

from app.banco import CAMINHO_BANCO, conectar, contar, criar_tabelas  # noqa: E402
from app.modelo import PASTA_PROCESSED  # noqa: E402

TAMANHO_LOTE = 500_000


def main():
    if os.path.exists(CAMINHO_BANCO):
        print(f"O banco já existe em {CAMINHO_BANCO}. Nada a fazer.")
        print("Para recriar do zero, apague o arquivo e rode o script de novo.")
        return
    if not os.path.exists(os.path.join(PASTA_PROCESSED, "avaliacoes.csv")):
        print("ERRO: dados tratados não encontrados. Rode antes: python scripts/preparar_dados.py")
        return

    inicio = time.time()
    print("1 - Lendo as avaliações tratadas...")
    avaliacoes = pd.read_csv(
        os.path.join(PASTA_PROCESSED, "avaliacoes.csv"),
        dtype={"livro_id": "int32", "usuario_id": "int32", "nota": "int8"},
    )
    # Ordenar por usuário deixa a gravação mais rápida, porque a tabela de
    # avaliações é guardada nessa mesma ordem
    avaliacoes = avaliacoes.sort_values(["usuario_id", "livro_id"]).reset_index(drop=True)
    print(f"   {len(avaliacoes):,} avaliações")

    print("\n2 - Criando o banco e as tabelas...")
    os.makedirs(os.path.dirname(CAMINHO_BANCO), exist_ok=True)
    conexao = conectar()
    # Durante a carga inicial, desligamos duas proteções do SQLite que
    # deixam a gravação lenta. Se der erro no meio, é só apagar o arquivo e
    # rodar de novo, então aqui elas não fazem falta.
    conexao.execute("PRAGMA journal_mode = OFF")
    conexao.execute("PRAGMA synchronous = OFF")
    conexao.execute("PRAGMA foreign_keys = OFF")
    criar_tabelas(conexao)

    print("\n3 - Gravando os usuários da base...")
    usuarios = avaliacoes["usuario_id"].unique()
    with conexao:
        conexao.executemany(
            "INSERT INTO usuarios (usuario_id, nome, origem) VALUES (?, NULL, 'base')",
            ((int(u),) for u in usuarios),
        )
    print(f"   {len(usuarios):,} usuários")

    print("\n4 - Gravando as avaliações (em lotes de 500 mil)...")
    for inicio_lote in range(0, len(avaliacoes), TAMANHO_LOTE):
        lote = avaliacoes.iloc[inicio_lote:inicio_lote + TAMANHO_LOTE]
        with conexao:
            conexao.executemany(
                "INSERT INTO avaliacoes (usuario_id, livro_id, nota) VALUES (?, ?, ?)",
                lote[["usuario_id", "livro_id", "nota"]].itertuples(index=False, name=None),
            )
        fim_lote = min(inicio_lote + TAMANHO_LOTE, len(avaliacoes))
        print(f"   {fim_lote:,} de {len(avaliacoes):,}")

    totais = contar(conexao)
    conexao.close()
    tamanho_mb = os.path.getsize(CAMINHO_BANCO) / (1024 * 1024)
    print(f"\nPronto! Banco criado em {time.time() - inicio:.0f} segundos ({tamanho_mb:,.0f} MB).")
    print(f"   {totais['usuarios']:,} usuários e {totais['avaliacoes']:,} avaliações")


if __name__ == "__main__":
    main()
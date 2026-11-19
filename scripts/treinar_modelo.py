"""
treinar_modelo.py

PASSO 3 do projeto: treinar o filtro colaborativo.

O que "treinar" significa aqui:
    Para cada um dos 9.374 livros, encontrar os 50 livros mais parecidos
    com ele, olhando para quem avaliou cada um. Isso é calculado uma vez só
    e salvo em data/modelo/vizinhos_cf.npz. A API só lê esse arquivo.

    A parte de conteúdo (Tag Genome) não precisa de treino: a API compara
    as tags na hora, porque é uma conta rápida.

Como rodar (na pasta raiz do projeto, com o venv ativo):
    python scripts/treinar_modelo.py

Leva poucos segundos e usa menos de 1 GB de memória.
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd

# Permite importar a pasta app/ mesmo rodando o script de dentro de scripts/
PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_PROJETO)

from app.modelo import PASTA_MODELO, PASTA_PROCESSED, calcular_vizinhos_cf  # noqa: E402

NUM_VIZINHOS = 50


def carregar_avaliacoes(livros):
    """Lê as avaliações com tipos pequenos e acrescenta a posição de cada
    livro (a linha dele em livros.csv), que é o que as matrizes usam."""
    avaliacoes = pd.read_csv(
        os.path.join(PASTA_PROCESSED, "avaliacoes.csv"),
        dtype={"livro_id": "int32", "usuario_id": "int32", "nota": "int8"},
    )
    indice = pd.Index(livros["livro_id"])
    avaliacoes["posicao"] = indice.get_indexer(avaliacoes["livro_id"]).astype("int32")
    return avaliacoes


def main():
    if not os.path.exists(os.path.join(PASTA_PROCESSED, "avaliacoes.csv")):
        print("ERRO: dados tratados não encontrados. Rode antes: python scripts/preparar_dados.py")
        return

    inicio = time.time()
    print("1 - Lendo os dados tratados...")
    livros = pd.read_csv(os.path.join(PASTA_PROCESSED, "livros.csv"))
    avaliacoes = carregar_avaliacoes(livros)
    print(f"   {len(livros):,} livros e {len(avaliacoes):,} avaliações")

    print(f"\n2 - Calculando os {NUM_VIZINHOS} vizinhos de cada livro (filtro colaborativo)...")
    indices, similaridades = calcular_vizinhos_cf(avaliacoes, len(livros), k=NUM_VIZINHOS)

    print("\n3 - Salvando em data/modelo/...")
    os.makedirs(PASTA_MODELO, exist_ok=True)
    np.savez(os.path.join(PASTA_MODELO, "vizinhos_cf.npz"),
             indices=indices, similaridades=similaridades)
    info = {"livros": len(livros), "avaliacoes": len(avaliacoes), "vizinhos_por_livro": NUM_VIZINHOS}
    with open(os.path.join(PASTA_MODELO, "info_treino.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)

    # Conferência rápida: os vizinhos de um livro conhecido fazem sentido?
    exemplo = livros.index[livros["titulo"].str.startswith("Harry Potter and the Sorcerer")]
    if len(exemplo):
        p = exemplo[0]
        print(f"\nConferência: livros mais parecidos com '{livros.at[p, 'titulo']}':")
        for q, s in zip(indices[p][:5], similaridades[p][:5]):
            print(f"   {s:.2f}  {livros.at[q, 'titulo']}")

    print(f"\nPronto! Treino concluído em {time.time() - inicio:.0f} segundos.")


if __name__ == "__main__":
    main()
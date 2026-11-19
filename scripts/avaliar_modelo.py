"""
avaliar_modelo.py

PASSO 3 do projeto: medir se o modelo recomenda bem.

Como o teste funciona (técnica "deixar um de fora"):
    1 - Sorteamos 3.000 usuários de um grupo (ver GRUPOS abaixo).
    2 - De cada um, escondemos UM livro que ele deu nota 5.
    3 - Treinamos o colaborativo de novo SEM esses livros escondidos,
        para o modelo não "colar" a resposta.
    4 - Pedimos 10 recomendações para cada usuário e verificamos se o
        livro escondido está entre elas.

    A métrica é a "taxa de acerto em 10" (hit rate@10): a porcentagem de
    usuários para quem o livro escondido apareceu no top 10. Escolher 10
    livros ao acaso entre 9.374 acertaria só 0,1% das vezes.

O teste é feito em dois grupos de usuários:
    * poucas avaliações (5 a 10 livros): o caso mais difícil, porque o
      colaborativo tem pouca informação sobre a pessoa
    * muitas avaliações (20 livros ou mais)

E compara, em cada grupo:
    * só popularidade (o que o usuário novo recebe)
    * só conteúdo, só colaborativo e o híbrido com vários pesos
    Foi esse teste que definiu o peso padrão de 0.5 usado na API.

Como rodar (na pasta raiz do projeto, com o venv ativo):
    python scripts/avaliar_modelo.py

Leva cerca de 1 minuto. O resultado também é salvo em data/modelo/avaliacao.json.
"""

import json
import os
import sys
import time

import numpy as np
import pandas as pd

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PASTA_PROJETO)
sys.path.insert(0, os.path.join(PASTA_PROJETO, "scripts"))

from app.modelo import PASTA_MODELO, PASTA_PROCESSED, Recomendador, calcular_vizinhos_cf  # noqa: E402
from treinar_modelo import carregar_avaliacoes  # noqa: E402

NUM_USUARIOS_TESTE = 3000
# (nome do grupo, mínimo de avaliações, máximo de avaliações ou None = sem máximo)
GRUPOS = [
    ("poucas avaliações (5 a 10)", 5, 10),
    ("muitas avaliações (20 ou mais)", 20, None),
]
TOP_N = 10
PESOS_CONTEUDO = [0.0, 0.25, 0.5, 0.75, 1.0]
SEMENTE = 42  # fixa o sorteio, para o resultado ser sempre o mesmo


def acertou(pontos, ja_avaliados, alvo):
    """True se o livro alvo está entre os TOP_N de maior pontuação."""
    pontos = pontos.copy()
    pontos[ja_avaliados] = -np.inf
    return alvo in np.argpartition(-pontos, TOP_N)[:TOP_N]


def avaliar_grupo(livros, genome, tags, avaliacoes, minimo, maximo):
    """Roda o teste completo para um grupo de usuários e devolve as taxas de acerto."""
    # Sorteia os usuários do grupo e esconde um livro nota 5 de cada
    contagem = avaliacoes["usuario_id"].value_counts()
    no_grupo = contagem >= minimo
    if maximo is not None:
        no_grupo &= contagem <= maximo
    candidatos = contagem[no_grupo].index.to_numpy()
    sorteio = np.random.default_rng(SEMENTE)
    usuarios = sorteio.choice(candidatos, NUM_USUARIOS_TESTE, replace=False)
    notas_5 = avaliacoes[avaliacoes["usuario_id"].isin(usuarios) & (avaliacoes["nota"] == 5)]
    escondidas = notas_5.groupby("usuario_id").sample(1, random_state=SEMENTE)
    treino = avaliacoes.drop(escondidas.index)

    # Treina o colaborativo de novo, sem os livros escondidos
    indices, similaridades = calcular_vizinhos_cf(treino, len(livros))
    modelo = Recomendador(livros, genome, tags, indices, similaridades)

    # Recomenda e conta os acertos
    acertos = {peso: 0 for peso in PESOS_CONTEUDO}
    acertos_populares = 0
    alvo_do_usuario = dict(zip(escondidas["usuario_id"], escondidas["posicao"]))
    teste = treino[treino["usuario_id"].isin(alvo_do_usuario)]
    for usuario, grupo in teste.groupby("usuario_id"):
        alvo = alvo_do_usuario[usuario]
        ja_avaliados = grupo["posicao"].to_numpy()
        avaliacoes_usuario = dict(zip(grupo["livro_id"].astype(int), grupo["nota"].astype(int)))

        for peso in PESOS_CONTEUDO:
            pontos = modelo.pontuacoes(avaliacoes_usuario, peso_conteudo=peso)
            if pontos is not None and acertou(pontos, ja_avaliados, alvo):
                acertos[peso] += 1
        if acertou(modelo.nota_popular, ja_avaliados, alvo):
            acertos_populares += 1

    total = len(alvo_do_usuario)
    resultado = {"usuarios_testados": total,
                 "so_popularidade": round(acertos_populares / total, 4)}
    for peso in PESOS_CONTEUDO:
        resultado[f"peso_conteudo_{peso}"] = round(acertos[peso] / total, 4)
    return resultado


def main():
    inicio = time.time()
    print("Lendo os dados tratados...")
    livros = pd.read_csv(os.path.join(PASTA_PROCESSED, "livros.csv"))
    genome = np.load(os.path.join(PASTA_PROCESSED, "genome.npy"))
    tags = pd.read_csv(os.path.join(PASTA_PROCESSED, "tags.csv"))["tag"]
    avaliacoes = carregar_avaliacoes(livros)

    resultados = {"top_n": TOP_N}
    for nome, minimo, maximo in GRUPOS:
        print(f"\nTestando usuários com {nome}...")
        r = avaliar_grupo(livros, genome, tags, avaliacoes, minimo, maximo)
        resultados[nome] = r

        print(f"   Taxa de acerto em {TOP_N} ({r['usuarios_testados']:,} usuários):")
        print(f"      só popularidade            {r['so_popularidade']:6.1%}")
        for peso in PESOS_CONTEUDO:
            rotulo = {0.0: "só colaborativo", 1.0: "só conteúdo"}.get(peso, f"híbrido ({peso:.0%} conteúdo)")
            print(f"      {rotulo:<26} {r[f'peso_conteudo_{peso}']:6.1%}")

    os.makedirs(PASTA_MODELO, exist_ok=True)
    with open(os.path.join(PASTA_MODELO, "avaliacao.json"), "w", encoding="utf-8") as f:
        json.dump(resultados, f, indent=2, ensure_ascii=False)
    print(f"\nPronto! Avaliação concluída em {time.time() - inicio:.0f} segundos.")
    print("Resultado salvo em data/modelo/avaliacao.json")


if __name__ == "__main__":
    main()
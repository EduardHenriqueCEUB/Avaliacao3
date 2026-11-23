"""
dados_sinteticos.py

Gera uma base PEQUENA e FALSA, no mesmo formato da Book Genome, para os testes.

Por que não usar a base real?
    A base real tem 1,4 GB e leva minutos para baixar e tratar. Os testes
    precisam rodar em segundos, em qualquer computador e sem internet.
    Por isso montamos uma "mini Book Genome" com o mesmo formato dos arquivos
    originais (metadata.json, ratings.json, tags.json e glmer.csv).

Como a base falsa é montada:
    * 60 livros, divididos em 3 gêneros de 20 livros cada:
          fantasia  -> tags fortes: magic, dragons, fantasy
          ficção    -> tags fortes: space, science fiction, aliens
          romance   -> tags fortes: love, romance, wedding
      e 3 tags "genéricas" que todo livro tem um pouco: good, classic, funny.
    * 60 usuários. Cada um tem um gênero favorito: dá nota 4 ou 5 para livros
      desse gênero e nota 1 ou 2 para livros de outro gênero.

    Assim o resultado esperado é óbvio: quem gosta de fantasia deve receber
    livros de fantasia. Os testes conferem isso.

Problemas colocados de propósito (os mesmos tipos da base real), para
testar o scripts/preparar_dados.py:
    * um livro com ano = 0 (ano desconhecido)
    * um título com caractere invisível (\\x01) e espaços sobrando
    * um livro repetido no metadata.json
    * um livro sem nenhuma avaliação
    * uma avaliação com nota 7 (inválida)
    * uma avaliação de um livro que não existe no catálogo
    * uma avaliação repetida (mesmo usuário e livro): fica a última
"""

import csv
import json
import os

import numpy as np

SEMENTE = 2026

GENEROS = {
    "fantasia": ["magic", "dragons", "fantasy"],
    "ficcao": ["space", "science fiction", "aliens"],
    "romance": ["love", "romance", "wedding"],
}
TAGS_GENERICAS = ["good", "classic", "funny"]
TAGS = [t for tags in GENEROS.values() for t in tags] + TAGS_GENERICAS

LIVROS_POR_GENERO = 20
NUM_USUARIOS = 60

# Os ids NÃO são 0, 1, 2...: assim os testes pegam qualquer confusão entre o
# livro_id (id da base) e a posição do livro nas matrizes.
PRIMEIRO_LIVRO_ID = 1000
PASSO_LIVRO_ID = 7
PRIMEIRO_USUARIO_ID = 10

# Casos especiais (posição do livro na lista)
POS_ANO_ZERO = 0          # livro de fantasia com ano = 0
POS_TITULO_SUJO = 1       # livro de fantasia com \x01 no título
POS_SEM_AVALIACOES = 59   # último livro de romance: ninguém avalia
LIVRO_INEXISTENTE = 999_999


def livro_id(posicao):
    return PRIMEIRO_LIVRO_ID + PASSO_LIVRO_ID * posicao


def genero_do_livro(posicao):
    return list(GENEROS)[posicao // LIVROS_POR_GENERO]


def ids_do_genero(genero):
    """Os livro_id de um gênero (na ordem)."""
    return [livro_id(p) for p in range(len(GENEROS) * LIVROS_POR_GENERO) if genero_do_livro(p) == genero]


def gerar_livros():
    livros = []
    for p in range(len(GENEROS) * LIVROS_POR_GENERO):
        genero = genero_do_livro(p)
        livros.append({
            "item_id": livro_id(p),
            "title": f"Livro de {genero} {p:02d}",
            "authors": f"Autor {genero.title()}",
            "year": 2000 + p,
            "lang": "eng",
            "description": f"Uma história de {genero}.",
            "img": f"https://exemplo.com/capa/{p}.jpg",
            "url": f"https://exemplo.com/livro/{p}",
        })
    livros[POS_ANO_ZERO]["year"] = 0
    livros[POS_TITULO_SUJO]["title"] = "  Livro\x01 sujo  "
    livros[POS_TITULO_SUJO]["description"] = "Linha 1\nLinha 2\x02"
    return livros


def gerar_genome(rng):
    """Lista de linhas (tag, item_id, score) no formato do glmer.csv."""
    linhas = []
    for p in range(len(GENEROS) * LIVROS_POR_GENERO):
        genero = genero_do_livro(p)
        for tag in TAGS:
            if tag in GENEROS[genero]:
                nota = rng.uniform(0.75, 1.0)
            elif tag in TAGS_GENERICAS:
                nota = rng.uniform(0.3, 0.6)
            else:
                nota = rng.uniform(0.0, 0.15)
            linhas.append((tag, livro_id(p), round(float(nota), 4)))
    return linhas


def genero_do_usuario(usuario_id):
    return list(GENEROS)[(usuario_id - PRIMEIRO_USUARIO_ID) % len(GENEROS)]


def gerar_avaliacoes(rng):
    avaliacoes = []
    generos = list(GENEROS)
    for j in range(NUM_USUARIOS):
        usuario = PRIMEIRO_USUARIO_ID + j
        favorito = genero_do_usuario(usuario)
        outro = generos[(generos.index(favorito) + 1) % len(generos)]

        gosta = [l for l in ids_do_genero(favorito) if l != livro_id(POS_SEM_AVALIACOES)]
        nao_gosta = [l for l in ids_do_genero(outro) if l != livro_id(POS_SEM_AVALIACOES)]
        # Alguns usuários (1 em cada 6) avaliam poucos livros: menos de 5,
        # então ficam fora do treino do colaborativo
        poucos = j % 6 == 5
        n_gosta, n_nao_gosta = (2, 1) if poucos else (8, 4)

        for l in rng.choice(gosta, n_gosta, replace=False):
            avaliacoes.append({"item_id": int(l), "user_id": usuario, "rating": int(rng.integers(4, 6))})
        for l in rng.choice(nao_gosta, n_nao_gosta, replace=False):
            avaliacoes.append({"item_id": int(l), "user_id": usuario, "rating": int(rng.integers(1, 3))})
    return avaliacoes


def gerar_base(pasta_raw):
    """Grava os 4 arquivos da base falsa em pasta_raw e devolve um resumo."""
    os.makedirs(pasta_raw, exist_ok=True)
    rng = np.random.default_rng(SEMENTE)

    livros = gerar_livros()
    # Livro repetido no metadata (deve ser removido)
    linhas_metadata = livros + [dict(livros[5], title="Duplicado")]
    with open(os.path.join(pasta_raw, "metadata.json"), "w", encoding="utf-8") as f:
        for livro in linhas_metadata:
            f.write(json.dumps(livro, ensure_ascii=False) + "\n")

    avaliacoes = gerar_avaliacoes(rng)
    validas = len(avaliacoes)
    primeiro = avaliacoes[0]
    problemas = [
        {"item_id": livro_id(3), "user_id": 10, "rating": 7},                # nota inválida
        {"item_id": LIVRO_INEXISTENTE, "user_id": 10, "rating": 5},          # livro inexistente
        {"item_id": primeiro["item_id"], "user_id": primeiro["user_id"], "rating": 3},  # repetida
    ]
    with open(os.path.join(pasta_raw, "ratings.json"), "w", encoding="utf-8") as f:
        for a in avaliacoes + problemas:
            f.write(json.dumps(a) + "\n")

    # Fora de ordem de propósito: o preparar_dados.py precisa ordenar pelo id
    with open(os.path.join(pasta_raw, "tags.json"), "w", encoding="utf-8") as f:
        for i, tag in reversed(list(enumerate(TAGS))):
            f.write(json.dumps({"tag": tag, "id": i}) + "\n")

    with open(os.path.join(pasta_raw, "glmer.csv"), "w", encoding="utf-8", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(["tag", "item_id", "score"])
        escritor.writerows(gerar_genome(rng))

    return {
        "livros": len(livros),
        "avaliacoes_validas": validas,
        "usuarios": NUM_USUARIOS,
        "tags": len(TAGS),
        "primeira_avaliacao": primeiro,
    }

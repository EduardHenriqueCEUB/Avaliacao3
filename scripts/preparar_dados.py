"""
preparar_dados.py

PASSO 2 do projeto: tratar a base Book Genome e salvar os arquivos limpos
que o modelo de recomendação e a API vão usar.

Entrada  (gerada pelo passo 1):  data/raw/
    metadata.json   informações dos livros
    ratings.json    avaliações de 1 a 5 estrelas
    tags.json       nomes das 727 tags
    glmer.csv       Tag Genome: nota de 0 a 1 de cada tag para cada livro

Saída (gerada por este script):  data/processed/
    livros.csv      livros limpos + quantidade e média de avaliações
    avaliacoes.csv  avaliações validadas (usuario_id, livro_id, nota)
    tags.csv        as 727 tags, na mesma ordem das colunas do genome.npy
    genome.npy      matriz livros x tags (9.374 x 727) com as notas do Tag Genome

Como rodar (a partir da pasta raiz do projeto, com o venv ativo):
    python scripts/preparar_dados.py

Problemas encontrados na base (analisados nos arquivos reais):
    * 1.256 livros com ano = 0, que significa "ano desconhecido"
    * 65 livros sem descrição e descrições com caracteres invisíveis (ex.: \\x01)
    * coluna de idioma sem utilidade: todos os livros são em inglês
      (eng, en-US, en-GB, en-CA, en) e 556 estão sem idioma
    * metade dos 350 mil usuários avaliou 4 livros ou menos
      (isso é tratado no modelo, no passo 3, e não aqui: esses usuários
      continuam existindo e podem pedir recomendações pela API)

Uso de memória:
    O pico fica em torno de 1 GB, então roda em computadores com 8 GB de RAM.
    O segredo é ler as avaliações em pedaços e guardar cada número no menor
    tipo possível (explicado na função tratar_avaliacoes).
"""

import json
import os
import time

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_RAW = os.path.join(PASTA_PROJETO, "data", "raw")
PASTA_PROCESSED = os.path.join(PASTA_PROJETO, "data", "processed")

# Quantas linhas de avaliações lemos por vez (ver tratar_avaliacoes)
TAMANHO_PEDACO = 500_000


# ---------------------------------------------------------------------------
# 1 - Livros
# ---------------------------------------------------------------------------

def limpar_texto(texto):
    """Remove caracteres invisíveis e espaços sobrando de um texto.

    Caracteres de controle são códigos de 0 a 31 da tabela ASCII que não
    aparecem na tela, mas podem quebrar a resposta da API (ex.: \\x01).
    Mantemos só a quebra de linha (\\n), que é útil na descrição.
    """
    if not isinstance(texto, str):
        return ""
    sem_controle = "".join(c for c in texto if c == "\n" or ord(c) >= 32)
    return sem_controle.strip()


def tratar_livros():
    print("1 - Tratando os livros (metadata.json)...")
    livros = pd.read_json(os.path.join(PASTA_RAW, "metadata.json"), lines=True)
    total_original = len(livros)

    # O README da base manda remover a coluna "pop". Na versão que baixamos
    # ela já não existe, mas deixamos a linha para o caso de existir.
    # A coluna "lang" sai porque todos os livros são em inglês.
    livros = livros.drop(columns=["pop", "lang"], errors="ignore")

    # Renomeia as colunas para português, deixando a API mais clara
    livros = livros.rename(columns={
        "item_id": "livro_id",
        "title": "titulo",
        "authors": "autores",
        "year": "ano",
        "description": "descricao",
        "img": "capa",
    })

    # Um mesmo livro não pode aparecer duas vezes
    livros = livros.drop_duplicates(subset="livro_id", keep="first")

    # Textos: tira caracteres invisíveis e espaços sobrando.
    # Descrição vazia vira "" (texto vazio) em vez de NaN.
    for coluna in ["titulo", "autores", "descricao"]:
        livros[coluna] = livros[coluna].apply(limpar_texto)

    # Ano 0 significa "desconhecido". Trocamos por um valor vazio (pd.NA).
    # O tipo "Int64" (com I maiúsculo) é um inteiro que aceita valor vazio.
    livros["ano"] = livros["ano"].replace(0, pd.NA).astype("Int64")

    # Ordena pelo id. A linha N de livros.csv vai ser a linha N do genome.npy
    livros = livros.sort_values("livro_id").reset_index(drop=True)

    print(f"   {total_original:,} livros lidos, {len(livros):,} mantidos")
    print(f"   {livros['ano'].isna().sum():,} livros com ano desconhecido")
    print(f"   {(livros['descricao'] == '').sum():,} livros sem descrição")
    return livros


# ---------------------------------------------------------------------------
# 2 - Avaliações
# ---------------------------------------------------------------------------

def tratar_avaliacoes(livros):
    print("\n2 - Tratando as avaliações (ratings.json)...")

    # Por que ler em pedaços?
    #   Ler as 5,1 milhões de linhas de uma vez faz o pandas usar ~3,5 GB de
    #   RAM, porque ele guarda cada número como int64 (8 bytes).
    #   Lendo 500 mil linhas por vez e convertendo cada pedaço para tipos
    #   menores, o pico cai para ~0,4 GB:
    #     int32 (4 bytes) para os ids: vai até 2,1 bilhões, sobra espaço
    #     int8  (1 byte)  para a nota: vai até 127, e a nota vai só até 5
    tipos = {"item_id": "int32", "user_id": "int32", "rating": "int8"}
    pedacos = []
    leitor = pd.read_json(
        os.path.join(PASTA_RAW, "ratings.json"),
        lines=True,
        chunksize=TAMANHO_PEDACO,
    )
    for pedaco in leitor:
        pedacos.append(pedaco.astype(tipos))
    avaliacoes = pd.concat(pedacos, ignore_index=True)
    del pedacos  # libera a memória da lista de pedaços
    total_original = len(avaliacoes)

    avaliacoes = avaliacoes.rename(columns={
        "user_id": "usuario_id",
        "item_id": "livro_id",
        "rating": "nota",
    })

    # Validações. Na base atual nenhuma delas remove linhas (conferimos),
    # mas elas protegem o projeto se a base mudar.
    #   a) a nota precisa estar entre 1 e 5
    avaliacoes = avaliacoes[avaliacoes["nota"].between(1, 5)]
    #   b) o livro avaliado precisa existir no catálogo
    avaliacoes = avaliacoes[avaliacoes["livro_id"].isin(livros["livro_id"])]
    #   c) um usuário avalia cada livro uma vez só (fica a última avaliação)
    avaliacoes = avaliacoes.drop_duplicates(
        subset=["usuario_id", "livro_id"], keep="last"
    )
    avaliacoes = avaliacoes.reset_index(drop=True)

    removidas = total_original - len(avaliacoes)
    print(f"   {total_original:,} avaliações lidas, {removidas:,} removidas")
    print(f"   {avaliacoes['usuario_id'].nunique():,} usuários")
    return avaliacoes


def adicionar_estatisticas(livros, avaliacoes):
    """Adiciona a cada livro quantas avaliações ele tem e a nota média.

    Isso serve para dois usos na API:
      * mostrar a nota média junto com cada recomendação
      * recomendar os livros mais populares para um usuário novo que ainda
        não avaliou nada (o chamado "problema do usuário frio")
    """
    estatisticas = avaliacoes.groupby("livro_id")["nota"].agg(
        num_avaliacoes="count", media_avaliacoes="mean"
    )
    livros = livros.merge(estatisticas, on="livro_id", how="left")
    livros["num_avaliacoes"] = livros["num_avaliacoes"].fillna(0).astype("int32")
    livros["media_avaliacoes"] = livros["media_avaliacoes"].round(2)

    # Organiza as colunas numa ordem fácil de ler (a descrição, que é longa, vai por último)
    colunas = ["livro_id", "titulo", "autores", "ano", "num_avaliacoes",
               "media_avaliacoes", "url", "capa", "descricao"]
    return livros[colunas]


# ---------------------------------------------------------------------------
# 3 - Tags e Tag Genome
# ---------------------------------------------------------------------------

def tratar_tags():
    print("\n3 - Lendo as tags (tags.json)...")
    tags = pd.read_json(os.path.join(PASTA_RAW, "tags.json"), lines=True)
    tags = tags.rename(columns={"id": "tag_id"})
    tags = tags.sort_values("tag_id").reset_index(drop=True)
    print(f"   {len(tags):,} tags")
    return tags[["tag_id", "tag"]]


def tratar_genome(livros, tags):
    print("\n4 - Montando a matriz do Tag Genome (glmer.csv)...")

    # O arquivo vem no formato "longo": uma linha por par (tag, livro).
    #     tag,item_id,score
    #     samurai,16416771,0.0344
    # Tipos menores aqui também: "category" guarda cada nome de tag uma
    # vez só, em vez de repetir o texto em 6,8 milhões de linhas.
    genome_longo = pd.read_csv(
        os.path.join(PASTA_RAW, "glmer.csv"),
        dtype={"tag": "category", "item_id": "int32", "score": "float32"},
    )

    # pivot transforma para o formato "largo": uma linha por livro e uma
    # coluna por tag. É o vetor de características de cada livro.
    genome = genome_longo.pivot(index="item_id", columns="tag", values="score")
    del genome_longo

    # Garante a mesma ordem dos outros arquivos:
    #   linhas  = mesma ordem de livros.csv
    #   colunas = mesma ordem de tags.csv
    genome = genome.reindex(index=livros["livro_id"], columns=tags["tag"])

    # Se faltar a nota de algum par (livro, tag), consideramos 0, ou seja,
    # "a tag não descreve o livro". Na base atual não falta nenhuma.
    faltando = int(genome.isna().sum().sum())
    genome = genome.fillna(0)

    # As notas do glmer já vão de 0 a 1, mas garantimos isso
    matriz = genome.to_numpy(dtype="float32").clip(0, 1)

    print(f"   matriz de {matriz.shape[0]:,} livros x {matriz.shape[1]:,} tags")
    print(f"   {faltando:,} notas faltando (preenchidas com 0)")
    return matriz


# ---------------------------------------------------------------------------
# 4 - Conferência final e gravação
# ---------------------------------------------------------------------------

def conferir(livros, avaliacoes, tags, matriz):
    """Testes rápidos: se algo estiver errado, o script para aqui com erro,
    em vez de salvar arquivos ruins que só dariam problema lá na API."""
    assert livros["livro_id"].is_unique, "livro_id repetido"
    assert matriz.shape == (len(livros), len(tags)), "genome desalinhado"
    assert not np.isnan(matriz).any(), "genome com valor vazio"
    assert avaliacoes["nota"].between(1, 5).all(), "nota fora de 1 a 5"
    assert avaliacoes["livro_id"].isin(livros["livro_id"]).all(), "livro inexistente"


def salvar(livros, avaliacoes, tags, matriz):
    print("\n5 - Salvando em data/processed/...")
    os.makedirs(PASTA_PROCESSED, exist_ok=True)

    livros.to_csv(os.path.join(PASTA_PROCESSED, "livros.csv"), index=False)
    avaliacoes.to_csv(os.path.join(PASTA_PROCESSED, "avaliacoes.csv"), index=False)
    tags.to_csv(os.path.join(PASTA_PROCESSED, "tags.csv"), index=False)
    # .npy é o formato do numpy: salva a matriz como ela está na memória,
    # muito mais rápido e menor que um CSV de 9.374 x 727 números
    np.save(os.path.join(PASTA_PROCESSED, "genome.npy"), matriz)

    # Um resumo legível para conferir sem abrir os arquivos grandes
    resumo = {
        "livros": len(livros),
        "usuarios": int(avaliacoes["usuario_id"].nunique()),
        "avaliacoes": len(avaliacoes),
        "tags": len(tags),
    }
    with open(os.path.join(PASTA_PROCESSED, "resumo.json"), "w", encoding="utf-8") as f:
        json.dump(resumo, f, indent=2, ensure_ascii=False)

    for nome in sorted(os.listdir(PASTA_PROCESSED)):
        tamanho_mb = os.path.getsize(os.path.join(PASTA_PROCESSED, nome)) / (1024 * 1024)
        print(f"   ok  {nome}  ({tamanho_mb:,.1f} MB)")


def main():
    if not os.path.exists(os.path.join(PASTA_RAW, "ratings.json")):
        print("ERRO: base não encontrada. Rode antes: python scripts/baixar_dados.py")
        return

    inicio = time.time()

    livros = tratar_livros()
    avaliacoes = tratar_avaliacoes(livros)
    livros = adicionar_estatisticas(livros, avaliacoes)
    tags = tratar_tags()
    matriz = tratar_genome(livros, tags)

    conferir(livros, avaliacoes, tags, matriz)
    salvar(livros, avaliacoes, tags, matriz)

    print(f"\nPronto! Tratamento concluído em {time.time() - inicio:.0f} segundos.")


if __name__ == "__main__":
    main()
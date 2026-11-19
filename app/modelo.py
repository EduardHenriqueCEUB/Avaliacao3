"""
modelo.py

PASSO 3 do projeto: o modelo de recomendação híbrido.

O modelo junta duas técnicas e faz uma média ponderada entre elas:

    1 - Filtragem baseada em CONTEÚDO (Tag Genome)
        Cada livro tem uma nota de 0 a 1 em 727 tags ("magic", "dark",
        "funny"...). Juntando as tags dos livros que o usuário gostou,
        montamos o "perfil de gosto" dele e procuramos livros com tags
        parecidas.

    2 - Filtragem COLABORATIVA (item a item)
        "Quem gostou deste livro também gostou daquele." Dois livros são
        parecidos quando as mesmas pessoas avaliam os dois de forma
        parecida. Os 50 vizinhos mais próximos de cada livro são
        calculados uma vez só, pelo scripts/treinar_modelo.py.

Por que híbrido? (medido pelo scripts/avaliar_modelo.py)
    O colaborativo acerta mais, mas não funciona para um livro novo, que
    ninguém avaliou ainda. O conteúdo funciona para qualquer livro que
    tenha tags. Juntos, acertam mais do que cada um sozinho.

Tags favoritas:
    Além das avaliações, o usuário pode escolher tags favoritas (ex.:
    "magic", "dystopia"). Elas entram no perfil de gosto do conteúdo e
    permitem recomendar algo útil para quem ainda não avaliou nenhum livro.

Por que este modelo combina com a API?
    Nenhuma das duas técnicas precisa ser retreinada quando chega um
    usuário novo ou uma avaliação nova: a recomendação é calculada na hora
    a partir das avaliações do usuário. Livros novos entram pelo conteúdo.

Este arquivo tem duas partes:
    * calcular_vizinhos_cf: o "treino" do colaborativo (usado pelos scripts)
    * Recomendador: carrega o modelo pronto e faz as recomendações (usado pela API)
"""

import os

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from sklearn.preprocessing import normalize

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_PROCESSED = os.path.join(PASTA_PROJETO, "data", "processed")
PASTA_MODELO = os.path.join(PASTA_PROJETO, "data", "modelo")

# Nota que consideramos "neutra". Notas acima puxam o gosto do usuário a
# favor das características do livro; notas abaixo puxam contra.
#   nota 5 -> peso +2   |   nota 4 -> +1   |   nota 3 -> 0
#   nota 2 -> peso -1   |   nota 1 -> -2
NOTA_NEUTRA = 3

# Peso padrão do conteúdo na média híbrida (o colaborativo fica com o resto).
# 0.5 foi o valor com mais acertos no scripts/avaliar_modelo.py.
PESO_CONTEUDO_PADRAO = 0.5

# Quanto vale uma tag favorita no perfil de gosto. 2.0 é o mesmo peso de
# um livro com nota 5: escolher "magic" como favorita equivale a dizer
# "adoro livros com magia".
PESO_TAG_FAVORITA = 2.0


# ---------------------------------------------------------------------------
# Treino do filtro colaborativo
# ---------------------------------------------------------------------------

def calcular_vizinhos_cf(avaliacoes, num_livros, k=50, min_avaliacoes_usuario=5, bloco=1000):
    """Calcula, para cada livro, os k livros mais parecidos pelas avaliações.

    avaliacoes: DataFrame com as colunas posicao (linha do livro em
                livros.csv), usuario_id e nota
    Retorna duas matrizes (num_livros x k):
        indices:       posição dos k vizinhos de cada livro
        similaridades: o quanto cada vizinho é parecido (de -1 a 1)
    """
    # 1 - Só entram no cálculo usuários com pelo menos 5 avaliações.
    #     Um usuário com 1 avaliação não diz nada sobre a relação entre dois
    #     livros e só adiciona ruído. Ele continua existindo na base e pode
    #     pedir recomendações normalmente.
    contagem = avaliacoes["usuario_id"].value_counts()
    usuarios_ok = contagem[contagem >= min_avaliacoes_usuario].index
    av = avaliacoes[avaliacoes["usuario_id"].isin(usuarios_ok)]

    # 2 - Centraliza a nota pela média de cada usuário.
    #     Tem gente que dá 5 para tudo e gente que é exigente. Subtraindo a
    #     média, um 4 de uma pessoa exigente vale mais do que um 4 de
    #     alguém que só dá 5.
    media_usuario = av.groupby("usuario_id")["nota"].transform("mean")
    nota_centrada = (av["nota"] - media_usuario).astype("float32")

    # 3 - Monta a matriz livros x usuários.
    #     Ela é "esparsa": guarda só as células preenchidas. Uma matriz
    #     comum de 9.374 livros x 160 mil usuários teria 1,5 bilhão de
    #     células, quase todas vazias, e não caberia na memória.
    codigo_usuario = av["usuario_id"].astype("category").cat.codes.to_numpy()
    matriz = csr_matrix(
        (nota_centrada.to_numpy(), (av["posicao"].to_numpy(), codigo_usuario)),
        shape=(num_livros, codigo_usuario.max() + 1),
    )

    # 4 - Normaliza cada linha (cada livro) para tamanho 1. Assim, o produto
    #     entre dois livros vira a similaridade do cosseno (de -1 a 1).
    matriz = normalize(matriz)
    transposta = matriz.T.tocsr()

    # 5 - Calcula as similaridades em blocos de 1.000 livros, guardando só os
    #     k maiores de cada um. A tabela completa (9.374 x 9.374) usaria
    #     muito mais memória, e a API só precisa dos vizinhos mais próximos.
    indices = np.zeros((num_livros, k), dtype="int32")
    similaridades = np.zeros((num_livros, k), dtype="float32")
    for inicio in range(0, num_livros, bloco):
        fim = min(inicio + bloco, num_livros)
        sim = (matriz[inicio:fim] @ transposta).toarray()

        # Um livro não pode ser vizinho dele mesmo
        linhas = np.arange(fim - inicio)
        sim[linhas, linhas + inicio] = -np.inf

        # argpartition acha os k maiores sem ordenar a linha inteira (mais
        # rápido); depois ordenamos só esses k, do mais parecido ao menos
        top = np.argpartition(-sim, k, axis=1)[:, :k]
        sim_top = np.take_along_axis(sim, top, axis=1)
        ordem = np.argsort(-sim_top, axis=1)
        indices[inicio:fim] = np.take_along_axis(top, ordem, axis=1)
        similaridades[inicio:fim] = np.take_along_axis(sim_top, ordem, axis=1)

    return indices, similaridades


# ---------------------------------------------------------------------------
# Recomendador (usado pela API)
# ---------------------------------------------------------------------------

def _escala_0_a_1(valores):
    """Coloca as notas na escala de 0 a 1, para poder somar conteúdo e
    colaborativo de forma justa (cada um tem sua própria escala)."""
    minimo, maximo = valores.min(), valores.max()
    if maximo <= minimo:
        return np.zeros_like(valores)
    return (valores - minimo) / (maximo - minimo)


class Recomendador:
    """Guarda o modelo na memória e faz as recomendações.

    Todos os métodos recebem e devolvem livro_id (o id da base), nunca a
    posição interna nas matrizes. A tradução é feita pelo self.posicao.
    """

    def __init__(self, livros, genome, tags, vizinhos_indices, vizinhos_similaridades):
        self.livros = livros.reset_index(drop=True)
        self.tags = list(tags)
        # nome da tag -> posição (coluna) no genome
        self.indice_tag = {tag: i for i, tag in enumerate(self.tags)}
        self.vizinhos_indices = vizinhos_indices
        self.vizinhos_similaridades = vizinhos_similaridades
        # Quantos livros têm vizinhos calculados. Livros adicionados depois
        # pela API ficam além desse número e usam só o conteúdo.
        self.num_livros_cf = len(vizinhos_indices)

        # livro_id -> posição (linha) nas matrizes
        self.posicao = {int(lid): i for i, lid in enumerate(self.livros["livro_id"])}

        # Média de cada tag em todos os livros. Serve para centralizar o
        # genome e como valor padrão das tags de um livro novo.
        self.media_tags = genome.mean(axis=0)
        self.genome = genome
        self._preparar_genome()

        # Nota de popularidade para quem ainda não avaliou nada
        self._calcular_populares()

    @classmethod
    def carregar(cls, pasta_processed=PASTA_PROCESSED, pasta_modelo=PASTA_MODELO):
        """Lê os arquivos gerados pelos scripts e monta o Recomendador."""
        livros = pd.read_csv(os.path.join(pasta_processed, "livros.csv"))
        genome = np.load(os.path.join(pasta_processed, "genome.npy"))
        tags = pd.read_csv(os.path.join(pasta_processed, "tags.csv"))["tag"]
        vizinhos = np.load(os.path.join(pasta_modelo, "vizinhos_cf.npz"))
        return cls(livros, genome, tags, vizinhos["indices"], vizinhos["similaridades"])

    # ---- preparação ------------------------------------------------------

    def _preparar_genome(self):
        """Centraliza e normaliza o genome para comparar livros.

        Centralizar (subtrair a média de cada tag) faz o modelo olhar para o
        que é ESPECIAL em cada livro. Sem isso, tags que quase todo livro
        tem um pouco (ex.: "good") deixariam todos os livros parecidos.
        No teste, centralizar mais que dobrou os acertos do modelo de conteúdo.
        """
        self.genome_centrado = (self.genome - self.media_tags).astype("float32")
        self.genome_normalizado = normalize(self.genome_centrado)

    def _calcular_populares(self):
        """Média bayesiana: a média de notas, "puxada" para a média geral
        quando o livro tem poucas avaliações.

        Sem isso, um livro com uma única avaliação 5 ficaria acima de um
        livro com 20 mil avaliações e média 4,6.
        """
        qtd = self.livros["num_avaliacoes"].fillna(0).to_numpy(dtype="float64")
        media = self.livros["media_avaliacoes"].fillna(0).to_numpy(dtype="float64")
        minimo = np.median(qtd[qtd > 0])  # "quantas avaliações dão confiança"
        media_geral = (media * qtd).sum() / qtd.sum()
        self.nota_popular = (qtd / (qtd + minimo)) * media + (minimo / (qtd + minimo)) * media_geral

    # ---- consultas -------------------------------------------------------

    def existe(self, livro_id):
        return int(livro_id) in self.posicao

    def tags_invalidas(self, nomes):
        """Devolve as tags da lista que não existem na base (lista vazia = tudo certo)."""
        return [t for t in nomes if t not in self.indice_tag]

    def proximo_livro_id(self):
        """O id que um livro novo deve receber: o maior id existente + 1."""
        return max(self.posicao) + 1

    def info_livro(self, livro_id):
        """Dados de um livro, prontos para a API (tipos simples do Python)."""
        linha = self.livros.iloc[self.posicao[int(livro_id)]]

        def limpo(valor):
            return None if pd.isna(valor) else valor

        return {
            "livro_id": int(linha["livro_id"]),
            "titulo": linha["titulo"],
            "autores": linha["autores"],
            "ano": None if pd.isna(linha["ano"]) else int(linha["ano"]),
            "num_avaliacoes": int(linha["num_avaliacoes"]),
            "media_avaliacoes": None if pd.isna(linha["media_avaliacoes"]) else float(linha["media_avaliacoes"]),
            "url": limpo(linha["url"]),
            "capa": limpo(linha["capa"]),
        }

    def detalhes_livro(self, livro_id, n_tags=10):
        """Tudo sobre um livro: dados, descrição e principais tags."""
        info = self.info_livro(livro_id)
        descricao = self.livros.at[self.posicao[int(livro_id)], "descricao"]
        info["descricao"] = "" if pd.isna(descricao) else descricao
        info["tags"] = self.tags_do_livro(livro_id, n_tags)
        return info

    def buscar(self, texto, limite=10):
        """Procura livros pelo título ou pelo autor (sem diferenciar
        maiúsculas de minúsculas). Os mais avaliados aparecem primeiro."""
        texto = texto.strip()
        achou = (self.livros["titulo"].str.contains(texto, case=False, regex=False, na=False)
                 | self.livros["autores"].str.contains(texto, case=False, regex=False, na=False))
        encontrados = self.livros[achou].sort_values("num_avaliacoes", ascending=False)
        return [self.info_livro(int(lid)) for lid in encontrados["livro_id"].head(limite)]

    def tags_do_livro(self, livro_id, n=10):
        """As n tags que mais caracterizam o livro.

        A ordem usa o genome centrado: assim aparecem as tags que são
        especiais NESTE livro (ex.: "space" para Dune), e não tags genéricas
        que quase todo livro tem (ex.: "good"). A nota mostrada é a original.
        """
        p = self.posicao[int(livro_id)]
        notas = self.genome[p]
        melhores = np.argsort(-self.genome_centrado[p])[:n]
        return [{"tag": self.tags[t], "nota": round(float(notas[t]), 3)} for t in melhores]

    # ---- recomendação ----------------------------------------------------

    def pontuacoes(self, avaliacoes, peso_conteudo=PESO_CONTEUDO_PADRAO, tags_favoritas=None):
        """Calcula a pontuação híbrida de TODOS os livros para um usuário.

        avaliacoes:     dicionário {livro_id: nota} com o que o usuário já avaliou
        tags_favoritas: lista de nomes de tags que o usuário escolheu (opcional)
        Retorna um array com uma pontuação (de 0 a 1) por livro, ou None se
        não há nada que diga o gosto do usuário (nenhuma avaliação diferente
        de 3 e nenhuma tag favorita).
        """
        posicoes = np.array([self.posicao[l] for l in avaliacoes if l in self.posicao], dtype="int64")
        pesos = np.array(
            [avaliacoes[l] - NOTA_NEUTRA for l in avaliacoes if l in self.posicao], dtype="float32"
        )
        indices_tags = [self.indice_tag[t] for t in (tags_favoritas or []) if t in self.indice_tag]
        if not pesos.any() and not indices_tags:
            return None

        # CONTEÚDO: o perfil do usuário é a soma das tags dos livros que ele
        # avaliou, cada um multiplicado pelo peso da nota, mais as tags
        # favoritas. A pontuação de um livro é o quanto as tags dele se
        # parecem com esse perfil (similaridade do cosseno).
        perfil = np.zeros(len(self.tags), dtype="float32")
        if len(posicoes):
            perfil += (pesos[:, None] * self.genome_normalizado[posicoes]).sum(axis=0)
        perfil[indices_tags] += PESO_TAG_FAVORITA
        conteudo = self.genome_normalizado @ perfil

        # COLABORATIVO: cada livro avaliado "vota" nos seus 50 vizinhos.
        # O voto é a similaridade x o peso da nota. Similaridades negativas
        # são ignoradas, porque "diferente de um livro que gostei" não quer
        # dizer "vou gostar".
        colaborativo = np.zeros(len(self.livros), dtype="float32")
        com_cf = posicoes < self.num_livros_cf  # livros novos não têm vizinhos
        if com_cf.any():
            viz = self.vizinhos_indices[posicoes[com_cf]]
            sims = self.vizinhos_similaridades[posicoes[com_cf]].clip(min=0)
            votos = sims * pesos[com_cf][:, None]
            np.add.at(colaborativo, viz.ravel(), votos.ravel())

        hibrido = (peso_conteudo * _escala_0_a_1(conteudo)
                   + (1 - peso_conteudo) * _escala_0_a_1(colaborativo))
        return hibrido

    def recomendar(self, avaliacoes, n=10, peso_conteudo=PESO_CONTEUDO_PADRAO, tags_favoritas=None):
        """Os n melhores livros para um usuário, com o motivo de cada um.

        Retorna um dicionário:
            estrategia:     "personalizada" ou "populares"
            recomendacoes:  lista de livros com pontuação e motivo

        Se ainda não há nada sobre o gosto do usuário (sem avaliações e sem
        tags favoritas), devolve os livros mais populares. Isso resolve o
        "problema do usuário frio".
        """
        tags_favoritas = [t for t in (tags_favoritas or []) if t in self.indice_tag]
        pontos = self.pontuacoes(avaliacoes, peso_conteudo, tags_favoritas)
        if pontos is None:
            return {"estrategia": "populares",
                    "recomendacoes": self.populares(n, excluir=avaliacoes)}

        # Não recomenda o que o usuário já avaliou
        ja_avaliados = [self.posicao[l] for l in avaliacoes if l in self.posicao]
        pontos[ja_avaliados] = -np.inf
        melhores = np.argsort(-pontos)[:n]

        gostou = [self.posicao[l] for l, nota in avaliacoes.items()
                  if l in self.posicao and nota > NOTA_NEUTRA]
        indices_tags = [self.indice_tag[t] for t in tags_favoritas]
        resultado = []
        for p in melhores:
            item = self.info_livro(int(self.livros.at[p, "livro_id"]))
            item["pontuacao"] = round(float(pontos[p]), 4)
            item["motivo"] = self._explicar(p, gostou, indices_tags)
            resultado.append(item)
        return {"estrategia": "personalizada", "recomendacoes": resultado}

    def _explicar(self, posicao, gostou, indices_tags):
        """Explica uma recomendação: as tags em comum e o livro de origem."""
        # Gosto do usuário por tag: a média das tags dos livros que ele
        # gostou, com um reforço nas tags favoritas (elas aparecem primeiro)
        gosto = np.zeros(len(self.tags), dtype="float32")
        if gostou:
            gosto += self.genome_centrado[gostou].clip(min=0).mean(axis=0)
        gosto[indices_tags] += 1.0

        # Tags fortes no livro recomendado E no gosto do usuário
        comum = self.genome_centrado[posicao].clip(min=0) * gosto
        tags = [self.tags[t] for t in np.argsort(-comum)[:3] if comum[t] > 0]

        # Entre os livros que o usuário gostou, o mais parecido com este
        parecido_com = None
        if gostou:
            semelhanca = self.genome_normalizado[gostou] @ self.genome_normalizado[posicao]
            origem = gostou[int(np.argmax(semelhanca))]
            parecido_com = {
                "livro_id": int(self.livros.at[origem, "livro_id"]),
                "titulo": self.livros.at[origem, "titulo"],
            }
        return {"tags_em_comum": tags, "parecido_com": parecido_com}

    def populares(self, n=10, excluir=()):
        """Os n livros com a melhor nota bayesiana."""
        pontos = self.nota_popular.copy()
        fora = [self.posicao[l] for l in excluir if l in self.posicao]
        pontos[fora] = -np.inf
        resultado = []
        for p in np.argsort(-pontos)[:n]:
            item = self.info_livro(int(self.livros.at[p, "livro_id"]))
            item["pontuacao"] = round(float(pontos[p]), 4)
            item["motivo"] = {"tags_em_comum": [], "parecido_com": None}
            resultado.append(item)
        return resultado

    def livros_parecidos(self, livro_id, n=10, peso_conteudo=PESO_CONTEUDO_PADRAO):
        """Os n livros mais parecidos com um livro, pelos dois critérios."""
        p = self.posicao[int(livro_id)]
        conteudo = self.genome_normalizado @ self.genome_normalizado[p]
        colaborativo = np.zeros(len(self.livros), dtype="float32")
        if p < self.num_livros_cf:
            colaborativo[self.vizinhos_indices[p]] = self.vizinhos_similaridades[p].clip(min=0)

        pontos = peso_conteudo * _escala_0_a_1(conteudo) + (1 - peso_conteudo) * _escala_0_a_1(colaborativo)
        pontos[p] = -np.inf
        resultado = []
        for q in np.argsort(-pontos)[:n]:
            item = self.info_livro(int(self.livros.at[q, "livro_id"]))
            item["pontuacao"] = round(float(pontos[q]), 4)
            resultado.append(item)
        return resultado

    # ---- livros novos ----------------------------------------------------

    def adicionar_livro(self, livro_id, titulo, autores, ano=None, tags=None):
        """Coloca um livro novo no modelo, sem precisar retreinar.

        tags: dicionário {nome_da_tag: nota de 0 a 1}, ex.: {"magic": 1.0}
              As tags não informadas recebem a média da base, ou seja, o
              livro fica "neutro" nelas.

        O livro entra só pelo conteúdo: ele ainda não tem avaliações, então
        não tem vizinhos no colaborativo. Isso muda quando o modelo for
        retreinado com as avaliações novas.
        """
        livro_id = int(livro_id)
        if livro_id in self.posicao:
            raise ValueError(f"O livro {livro_id} já existe.")
        tags = tags or {}
        desconhecidas = self.tags_invalidas(tags)
        if desconhecidas:
            raise ValueError(f"Tags que não existem na base: {desconhecidas}")

        vetor = self.media_tags.copy()
        for nome, nota in tags.items():
            vetor[self.indice_tag[nome]] = min(max(float(nota), 0.0), 1.0)

        nova_linha = pd.DataFrame([{
            "livro_id": livro_id, "titulo": titulo, "autores": autores, "ano": ano,
            "num_avaliacoes": 0, "media_avaliacoes": np.nan,
            "url": np.nan, "capa": np.nan, "descricao": "",
        }])
        self.livros = pd.concat([self.livros, nova_linha], ignore_index=True)
        self.posicao[livro_id] = len(self.livros) - 1
        self.genome = np.vstack([self.genome, vetor.astype("float32")])
        # A média das tags continua a da base original (não recalculamos)
        self._preparar_genome()
        self.nota_popular = np.append(self.nota_popular, 0.0)
        return self.info_livro(livro_id)
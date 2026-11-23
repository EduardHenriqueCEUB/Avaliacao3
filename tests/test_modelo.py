"""
Testes do app/modelo.py (o modelo de recomendação híbrido).

Duas partes:
    * Testes com um modelo MÍNIMO montado à mão (4 livros, 3 tags), onde dá
      para saber a resposta certa fazendo a conta.
    * Testes com o modelo treinado na base sintética (60 livros em 3
      gêneros), onde a resposta certa é "quem gosta de fantasia recebe
      fantasia".
"""

import numpy as np
import pandas as pd
import pytest

import dados_sinteticos as ds
from app.modelo import (
    NOTA_NEUTRA,
    PESO_CONTEUDO_PADRAO,
    Recomendador,
    _escala_0_a_1,
    calcular_vizinhos_cf,
)

FANTASIA = set(ds.ids_do_genero("fantasia"))
FICCAO = set(ds.ids_do_genero("ficcao"))
ROMANCE = set(ds.ids_do_genero("romance"))
TAGS_FANTASIA = set(ds.GENEROS["fantasia"])


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------


def test_constantes_do_modelo():
    assert NOTA_NEUTRA == 3
    assert PESO_CONTEUDO_PADRAO == 0.5  # o melhor valor no scripts/avaliar_modelo.py


# ---------------------------------------------------------------------------
# _escala_0_a_1
# ---------------------------------------------------------------------------


def test_escala_0_a_1():
    r = _escala_0_a_1(np.array([2.0, 4.0, 6.0]))
    np.testing.assert_allclose(r, [0.0, 0.5, 1.0])


def test_escala_0_a_1_com_negativos():
    r = _escala_0_a_1(np.array([-1.0, 0.0, 1.0]))
    np.testing.assert_allclose(r, [0.0, 0.5, 1.0])


def test_escala_0_a_1_valores_iguais_viram_zero():
    # Sem isso haveria divisão por zero (ex.: colaborativo todo zerado)
    r = _escala_0_a_1(np.array([3.0, 3.0, 3.0]))
    np.testing.assert_array_equal(r, [0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# calcular_vizinhos_cf (o "treino" do colaborativo)
# ---------------------------------------------------------------------------


def _avaliacoes_cf():
    """4 livros e 5 usuários com 4 avaliações cada. Quem gosta do 0 gosta do
    1 e não gosta do 2 e do 3. Então: 0 e 1 são parecidos (sim = 1), 2 e 3
    também. Os testes usam min_avaliacoes_usuario=4 (o padrão é 5)."""
    linhas = []
    for usuario in range(1, 6):
        for posicao, nota in [(0, 5), (1, 5), (2, 1), (3, 1)]:
            linhas.append({"usuario_id": usuario, "posicao": posicao, "nota": nota})
    return pd.DataFrame(linhas)


def test_vizinhos_formato_e_tipos():
    indices, sims = calcular_vizinhos_cf(_avaliacoes_cf(), num_livros=4, k=2, min_avaliacoes_usuario=4)
    assert indices.shape == (4, 2) and sims.shape == (4, 2)
    assert indices.dtype == np.int32 and sims.dtype == np.float32


def test_vizinhos_acha_os_livros_parecidos():
    indices, sims = calcular_vizinhos_cf(_avaliacoes_cf(), num_livros=4, k=2, min_avaliacoes_usuario=4)
    assert indices[0, 0] == 1 and indices[1, 0] == 0
    assert indices[2, 0] == 3 and indices[3, 0] == 2
    assert sims[0, 0] == pytest.approx(1.0, abs=1e-5)


def test_livro_nao_e_vizinho_dele_mesmo():
    indices, _ = calcular_vizinhos_cf(_avaliacoes_cf(), num_livros=4, k=3, min_avaliacoes_usuario=4)
    for livro in range(4):
        assert livro not in indices[livro]


def test_vizinhos_ordenados_do_mais_parecido_ao_menos():
    indices, sims = calcular_vizinhos_cf(_avaliacoes_cf(), num_livros=4, k=3, min_avaliacoes_usuario=4)
    assert (np.diff(sims, axis=1) <= 1e-6).all()
    assert sims[0, -1] == pytest.approx(-1.0, abs=1e-5)  # o oposto fica por último


def test_vizinhos_ignora_usuarios_com_poucas_avaliacoes():
    base = _avaliacoes_cf()
    # Um usuário com só 2 avaliações que "liga" o livro 0 ao 3
    ruido = pd.DataFrame([{"usuario_id": 99, "posicao": 0, "nota": 5},
                          {"usuario_id": 99, "posicao": 3, "nota": 5}])
    com_ruido = pd.concat([base, ruido], ignore_index=True)

    i1, s1 = calcular_vizinhos_cf(base, 4, k=2, min_avaliacoes_usuario=4)
    i2, s2 = calcular_vizinhos_cf(com_ruido, 4, k=2, min_avaliacoes_usuario=4)
    np.testing.assert_array_equal(i1, i2)
    np.testing.assert_allclose(s1, s2)


def test_vizinhos_centraliza_pela_media_do_usuario():
    # Um usuário que dá 5 para tudo não diz nada: depois de subtrair a média,
    # as notas dele viram 0 e não criam similaridade
    linhas = [{"usuario_id": 1, "posicao": p, "nota": 5} for p in range(4)]
    _, sims = calcular_vizinhos_cf(pd.DataFrame(linhas), 4, k=2, min_avaliacoes_usuario=1)
    np.testing.assert_allclose(sims, 0.0)


def test_vizinhos_em_blocos_dao_o_mesmo_resultado():
    av = _avaliacoes_cf()
    i1, s1 = calcular_vizinhos_cf(av, 4, k=2, min_avaliacoes_usuario=4, bloco=1000)
    i2, s2 = calcular_vizinhos_cf(av, 4, k=2, min_avaliacoes_usuario=4, bloco=1)
    np.testing.assert_allclose(s1, s2, atol=1e-6)
    # Os mais parecidos (sem empate) são os mesmos
    np.testing.assert_array_equal(i1[:, 0], i2[:, 0])


# ---------------------------------------------------------------------------
# Modelo mínimo, montado à mão
# ---------------------------------------------------------------------------


@pytest.fixture
def mini():
    """4 livros e 3 tags. Livros 10 e 20 são de "magia", 30 e 40 de "espaço"."""
    livros = pd.DataFrame({
        "livro_id": [10, 20, 30, 40],
        "titulo": ["Magia Um", "Magia Dois", "Espaço Um", "Espaço Dois"],
        "autores": ["Ana", "Ana", "Bruno", "Bruno"],
        "ano": [2001, np.nan, 2003, 2004],
        "num_avaliacoes": [1, 1000, 50, 0],
        "media_avaliacoes": [5.0, 4.6, 3.0, np.nan],
        "url": ["u10", "u20", "u30", np.nan],
        "capa": ["c10", "c20", "c30", np.nan],
        "descricao": ["d10", "d20", "d30", np.nan],
    })
    genome = np.array([
        [0.9, 0.1, 0.5],
        [0.8, 0.2, 0.5],
        [0.1, 0.9, 0.5],
        [0.2, 0.8, 0.5],
    ], dtype="float32")
    tags = ["magia", "espaco", "bom"]
    indices = np.array([[1, 2], [0, 3], [3, 0], [2, 1]], dtype="int32")
    sims = np.array([[0.9, -0.5], [0.9, -0.5], [0.8, -0.5], [0.8, -0.5]], dtype="float32")
    return Recomendador(livros, genome, tags, indices, sims)


def test_mini_posicao_traduz_id_para_linha(mini):
    assert mini.posicao == {10: 0, 20: 1, 30: 2, 40: 3}
    assert mini.indice_tag == {"magia": 0, "espaco": 1, "bom": 2}
    assert mini.num_livros_cf == 4


def test_mini_genome_centrado_e_normalizado(mini):
    np.testing.assert_allclose(mini.genome_centrado.mean(axis=0), 0, atol=1e-6)
    normas = np.linalg.norm(mini.genome_normalizado, axis=1)
    np.testing.assert_allclose(normas, 1, atol=1e-5)
    # A tag "bom" é igual em todos os livros: depois de centralizar, ela não
    # pesa nada (é isso que o modelo quer: olhar o que é especial no livro)
    np.testing.assert_allclose(mini.genome_centrado[:, 2], 0, atol=1e-6)


def test_mini_media_bayesiana(mini):
    # Um livro com UMA avaliação 5 não pode ficar acima de um livro com
    # 1.000 avaliações e média 4,6
    pos = mini.posicao
    assert mini.nota_popular[pos[20]] > mini.nota_popular[pos[10]]
    assert mini.populares(1)[0]["livro_id"] == 20


def test_mini_pontuacoes_sem_informacao_devolve_none(mini):
    assert mini.pontuacoes({}) is None
    assert mini.pontuacoes({10: 3, 30: 3}) is None  # só notas neutras
    assert mini.pontuacoes({999: 5}) is None          # livro que não existe


def test_mini_pontuacoes_na_escala_0_a_1(mini):
    p = mini.pontuacoes({10: 5})
    assert p.shape == (4,)
    assert p.min() >= 0 and p.max() <= 1 + 1e-6


def test_mini_quem_gosta_de_magia_recebe_magia(mini):
    r = mini.recomendar({10: 5}, n=1)
    assert r["estrategia"] == "personalizada"
    assert r["recomendacoes"][0]["livro_id"] == 20


def test_mini_nota_baixa_afasta(mini):
    # Odiar um livro de magia puxa para os livros de espaço
    r = mini.recomendar({10: 1}, n=1)
    assert r["recomendacoes"][0]["livro_id"] in (30, 40)


def test_mini_tag_favorita_sozinha_personaliza(mini):
    r = mini.recomendar({}, n=2, tags_favoritas=["espaco"])
    assert r["estrategia"] == "personalizada"
    assert {x["livro_id"] for x in r["recomendacoes"]} == {30, 40}
    assert r["recomendacoes"][0]["motivo"]["tags_em_comum"] == ["espaco"]
    assert r["recomendacoes"][0]["motivo"]["parecido_com"] is None


def test_mini_peso_conteudo_extremos(mini):
    so_conteudo = mini.pontuacoes({10: 5}, peso_conteudo=1.0)
    so_cf = mini.pontuacoes({10: 5}, peso_conteudo=0.0)
    # Só colaborativo: o livro 10 vota só nos vizinhos dele (20 com 0,9;
    # o 30 tem similaridade negativa, que é ignorada)
    pos = mini.posicao
    assert so_cf[pos[20]] == pytest.approx(1.0)
    assert so_cf[pos[30]] == pytest.approx(0.0)
    assert so_cf[pos[40]] == pytest.approx(0.0)
    # Só conteúdo: o 20 (magia) fica acima do 30 e do 40 (espaço)
    assert so_conteudo[pos[20]] > so_conteudo[pos[30]]
    assert so_conteudo[pos[20]] > so_conteudo[pos[40]]


def test_mini_info_livro_com_valores_vazios(mini):
    info = mini.info_livro(40)
    assert info == {
        "livro_id": 40, "titulo": "Espaço Dois", "autores": "Bruno", "ano": 2004,
        "num_avaliacoes": 0, "media_avaliacoes": None, "url": None, "capa": None,
    }
    assert mini.info_livro(20)["ano"] is None
    assert mini.detalhes_livro(40)["descricao"] == ""


def test_mini_info_livro_tipos_simples_do_python(mini):
    # A API transforma em JSON: não pode sobrar tipo do numpy
    info = mini.info_livro(10)
    assert type(info["livro_id"]) is int
    assert type(info["ano"]) is int
    assert type(info["num_avaliacoes"]) is int
    assert type(info["media_avaliacoes"]) is float


# ---------------------------------------------------------------------------
# Modelo treinado na base sintética
# ---------------------------------------------------------------------------


def test_carregar_monta_o_modelo(modelo):
    assert len(modelo.livros) == 60
    assert modelo.tags == ds.TAGS
    assert modelo.genome.shape == (60, len(ds.TAGS))
    assert modelo.vizinhos_indices.shape == (60, 10)
    assert modelo.num_livros_cf == 60


def test_existe(modelo):
    assert modelo.existe(ds.livro_id(0))
    assert modelo.existe(str(ds.livro_id(0)))  # aceita texto também
    assert not modelo.existe(ds.LIVRO_INEXISTENTE)


def test_tags_invalidas(modelo):
    assert modelo.tags_invalidas(["magic", "space"]) == []
    assert modelo.tags_invalidas(["magic", "nao existe", "Magic"]) == ["nao existe", "Magic"]
    assert modelo.tags_invalidas([]) == []


def test_proximo_livro_id(modelo):
    assert modelo.proximo_livro_id() == ds.livro_id(59) + 1


def test_tags_do_livro_mostra_as_especiais(modelo):
    tags = modelo.tags_do_livro(ds.livro_id(3), n=3)
    assert len(tags) == 3
    assert {t["tag"] for t in tags} == TAGS_FANTASIA
    for t in tags:
        assert 0 <= t["nota"] <= 1


def test_detalhes_livro(modelo):
    d = modelo.detalhes_livro(ds.livro_id(25))
    assert d["livro_id"] == ds.livro_id(25)
    assert d["descricao"] == "Uma história de ficcao."
    assert len(d["tags"]) == 10


def test_buscar_sem_diferenciar_maiusculas(modelo):
    r = modelo.buscar("LIVRO DE ROMANCE", limite=50)
    assert len(r) == 20
    assert all("romance" in x["titulo"] for x in r)


def test_buscar_pelo_autor(modelo):
    r = modelo.buscar("autor ficcao", limite=50)
    assert {x["livro_id"] for x in r} == FICCAO


def test_buscar_mais_avaliados_primeiro_e_limite(modelo):
    r = modelo.buscar("livro", limite=5)
    assert len(r) == 5
    qtd = [x["num_avaliacoes"] for x in r]
    assert qtd == sorted(qtd, reverse=True)


def test_buscar_ignora_espacos_e_caracteres_especiais(modelo):
    assert modelo.buscar("  sujo  ")[0]["livro_id"] == ds.livro_id(ds.POS_TITULO_SUJO)
    assert modelo.buscar("(") == []  # não é tratado como expressão regular
    assert modelo.buscar("nada parecido") == []


def _usuario_fantasia():
    return {lid: 5 for lid in sorted(FANTASIA)[2:7]}


def test_recomenda_o_genero_que_o_usuario_gosta(modelo):
    r = modelo.recomendar(_usuario_fantasia(), n=10)
    ids = [x["livro_id"] for x in r["recomendacoes"]]
    assert r["estrategia"] == "personalizada"
    assert len(ids) == 10
    assert set(ids) <= FANTASIA


def test_nao_recomenda_o_que_ja_foi_avaliado(modelo):
    avaliacoes = _usuario_fantasia()
    r = modelo.recomendar(avaliacoes, n=50)
    ids = {x["livro_id"] for x in r["recomendacoes"]}
    assert not ids & set(avaliacoes)


def test_recomendacoes_ordenadas_e_sem_repeticao(modelo):
    r = modelo.recomendar(_usuario_fantasia(), n=20)["recomendacoes"]
    pontos = [x["pontuacao"] for x in r]
    assert pontos == sorted(pontos, reverse=True)
    assert len({x["livro_id"] for x in r}) == len(r)


def test_respeita_o_numero_pedido(modelo):
    for n in (1, 3, 10):
        assert len(modelo.recomendar(_usuario_fantasia(), n=n)["recomendacoes"]) == n


def test_motivo_da_recomendacao(modelo):
    avaliacoes = _usuario_fantasia()
    for item in modelo.recomendar(avaliacoes, n=5)["recomendacoes"]:
        motivo = item["motivo"]
        assert motivo["tags_em_comum"]
        assert set(motivo["tags_em_comum"]) <= TAGS_FANTASIA
        assert len(motivo["tags_em_comum"]) <= 3
        assert motivo["parecido_com"]["livro_id"] in avaliacoes


def test_parecido_com_so_usa_livros_que_o_usuario_gostou(modelo):
    avaliacoes = {**_usuario_fantasia(), sorted(ROMANCE)[0]: 1}
    for item in modelo.recomendar(avaliacoes, n=5)["recomendacoes"]:
        assert item["motivo"]["parecido_com"]["livro_id"] in FANTASIA


def test_quem_so_odeia_romance_nao_recebe_romance(modelo):
    avaliacoes = {lid: 1 for lid in sorted(ROMANCE)[:5]}
    ids = {x["livro_id"] for x in modelo.recomendar(avaliacoes, n=10)["recomendacoes"]}
    assert not ids & ROMANCE


def test_tags_favoritas_sem_avaliacoes(modelo):
    r = modelo.recomendar({}, n=10, tags_favoritas=["space", "aliens"])
    assert r["estrategia"] == "personalizada"
    assert {x["livro_id"] for x in r["recomendacoes"]} <= FICCAO


def test_tags_favoritas_invalidas_sao_ignoradas(modelo):
    r = modelo.recomendar({}, n=5, tags_favoritas=["nao existe"])
    assert r["estrategia"] == "populares"


def test_usuario_sem_nada_recebe_populares(modelo):
    r = modelo.recomendar({}, n=5)
    assert r["estrategia"] == "populares"
    assert [x["livro_id"] for x in r["recomendacoes"]] == [x["livro_id"] for x in modelo.populares(5)]


def test_usuario_so_com_notas_neutras_recebe_populares_sem_os_avaliados(modelo):
    avaliacoes = {x["livro_id"]: 3 for x in modelo.populares(2)}
    r = modelo.recomendar(avaliacoes, n=5)
    assert r["estrategia"] == "populares"
    assert not {x["livro_id"] for x in r["recomendacoes"]} & set(avaliacoes)


def test_livros_desconhecidos_nas_avaliacoes_sao_ignorados(modelo):
    com = modelo.recomendar({**_usuario_fantasia(), ds.LIVRO_INEXISTENTE: 5}, n=5)
    sem = modelo.recomendar(_usuario_fantasia(), n=5)
    assert com == sem


def test_peso_conteudo_muda_o_resultado(modelo):
    a = modelo.pontuacoes(_usuario_fantasia(), peso_conteudo=0.0)
    b = modelo.pontuacoes(_usuario_fantasia(), peso_conteudo=1.0)
    assert not np.allclose(a, b)
    h = modelo.pontuacoes(_usuario_fantasia(), peso_conteudo=0.5)
    np.testing.assert_allclose(h, 0.5 * a + 0.5 * b, atol=1e-5)


def test_recomendar_nao_altera_as_avaliacoes_recebidas(modelo):
    avaliacoes = _usuario_fantasia()
    copia = dict(avaliacoes)
    modelo.recomendar(avaliacoes, n=5)
    assert avaliacoes == copia


# Os dois testes abaixo mostram um bug do app/modelo.py. Com a base real
# (9.374 livros e no máximo 100 recomendações por pedido) ele só aparece se
# o usuário tiver avaliado mais de 9.274 livros, mas a regra "não recomendar
# o que já foi avaliado" deveria valer sempre. O "xfail" marca o teste como
# "falha esperada": a bateria continua verde, e quando o bug for corrigido o
# pytest avisa (strict=True), para tirarmos a marcação.
#
# Correção sugerida (em recomendar e em populares): depois do argsort,
# manter só as posições com pontuação diferente de -inf, por exemplo:
#     melhores = [p for p in np.argsort(-pontos)[:n] if np.isfinite(pontos[p])]

BUG_MENOS_INFINITO = (
    "Bug conhecido: com n maior que o número de livros não avaliados, "
    "os já avaliados voltam na lista com pontuação -inf."
)


@pytest.mark.xfail(strict=True, reason=BUG_MENOS_INFINITO)
def test_pedindo_todos_os_livros_ainda_nao_traz_os_avaliados(modelo):
    avaliacoes = _usuario_fantasia()
    r = modelo.recomendar(avaliacoes, n=60)["recomendacoes"]
    assert not {x["livro_id"] for x in r} & set(avaliacoes)
    assert all(np.isfinite(x["pontuacao"]) for x in r)


@pytest.mark.xfail(strict=True, reason=BUG_MENOS_INFINITO)
def test_populares_pedindo_todos_ainda_respeita_o_excluir(modelo):
    fora = modelo.populares(1)[0]["livro_id"]
    r = modelo.populares(60, excluir=[fora])
    assert fora not in {x["livro_id"] for x in r}


def test_populares(modelo):
    r = modelo.populares(10)
    assert len(r) == 10
    pontos = [x["pontuacao"] for x in r]
    assert pontos == sorted(pontos, reverse=True)
    for x in r:
        assert x["motivo"] == {"tags_em_comum": [], "parecido_com": None}
    # O livro sem avaliações não está entre os populares
    assert ds.livro_id(ds.POS_SEM_AVALIACOES) not in {x["livro_id"] for x in r}


def test_populares_com_excluir(modelo):
    primeiro = modelo.populares(1)[0]["livro_id"]
    r = modelo.populares(5, excluir=[primeiro])
    assert primeiro not in {x["livro_id"] for x in r}


def test_livros_parecidos(modelo):
    alvo = ds.livro_id(25)  # ficção
    r = modelo.livros_parecidos(alvo, n=5)
    ids = [x["livro_id"] for x in r]
    assert len(ids) == 5
    assert alvo not in ids
    assert set(ids) <= FICCAO
    pontos = [x["pontuacao"] for x in r]
    assert pontos == sorted(pontos, reverse=True)


# ---------------------------------------------------------------------------
# Livros novos (sem retreinar)
# ---------------------------------------------------------------------------


def test_adicionar_livro(modelo):
    novo_id = modelo.proximo_livro_id()
    info = modelo.adicionar_livro(novo_id, "Dragões de Brasília", "Fulano", 2026,
                                  {"dragons": 1.0, "magic": 0.9})
    assert info["livro_id"] == novo_id
    assert info["num_avaliacoes"] == 0
    assert info["media_avaliacoes"] is None and info["url"] is None
    assert modelo.existe(novo_id)
    assert len(modelo.livros) == 61
    assert modelo.genome.shape == (61, len(ds.TAGS))
    assert modelo.num_livros_cf == 60  # continua fora do colaborativo
    assert modelo.proximo_livro_id() == novo_id + 1


def test_adicionar_livro_tags_nao_informadas_ficam_na_media(modelo):
    novo_id = modelo.proximo_livro_id()
    modelo.adicionar_livro(novo_id, "X", "Y", tags={"magic": 5.0, "space": -1.0})
    vetor = modelo.genome[modelo.posicao[novo_id]]
    i = modelo.indice_tag
    assert vetor[i["magic"]] == 1.0   # limitado a 1
    assert vetor[i["space"]] == 0.0   # limitado a 0
    assert vetor[i["love"]] == pytest.approx(modelo.media_tags[i["love"]])


def test_adicionar_livro_repetido_da_erro(modelo):
    with pytest.raises(ValueError, match="já existe"):
        modelo.adicionar_livro(ds.livro_id(0), "X", "Y")


def test_adicionar_livro_com_tag_invalida_da_erro(modelo):
    with pytest.raises(ValueError, match="não existem"):
        modelo.adicionar_livro(modelo.proximo_livro_id(), "X", "Y", tags={"inventada": 1.0})
    assert len(modelo.livros) == 60  # nada foi adicionado


def test_livro_novo_ja_pode_ser_recomendado_pelo_conteudo(modelo):
    novo_id = modelo.proximo_livro_id()
    # Tags de um livro de fantasia típico: alto nas de fantasia, zero nas
    # dos outros gêneros
    tags = {t: 0.0 for t in ds.TAGS if t not in ds.TAGS_GENERICAS}
    tags.update({"magic": 1.0, "dragons": 1.0, "fantasy": 1.0})
    modelo.adicionar_livro(novo_id, "Novo de fantasia", "Fulano", tags=tags)
    r = modelo.recomendar(_usuario_fantasia(), n=5, peso_conteudo=1.0)
    assert novo_id in [x["livro_id"] for x in r["recomendacoes"]]
    assert novo_id in [x["livro_id"] for x in modelo.buscar("novo de fantasia")]


def test_usuario_que_avaliou_livro_novo(modelo):
    # O livro novo não tem vizinhos no colaborativo: não pode dar erro
    novo_id = modelo.proximo_livro_id()
    modelo.adicionar_livro(novo_id, "Novo", "Fulano", tags={"space": 1.0, "aliens": 1.0})
    r = modelo.recomendar({novo_id: 5}, n=5)
    assert r["estrategia"] == "personalizada"
    assert novo_id not in [x["livro_id"] for x in r["recomendacoes"]]
    assert {x["livro_id"] for x in r["recomendacoes"]} <= FICCAO


def test_livro_novo_em_parecidos_e_populares(modelo):
    novo_id = modelo.proximo_livro_id()
    modelo.adicionar_livro(novo_id, "Novo", "Fulano", tags={"love": 1.0, "romance": 1.0})
    parecidos = modelo.livros_parecidos(novo_id, n=5)
    assert {x["livro_id"] for x in parecidos} <= ROMANCE
    assert len(modelo.populares(61)) == 61
    assert modelo.detalhes_livro(novo_id)["descricao"] == ""

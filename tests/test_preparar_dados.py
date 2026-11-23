"""
Testes do scripts/preparar_dados.py (tratamento da base).

Unitários: as funções sozinhas (limpar_texto, conferir...).
Integração: os arquivos que o script gerou a partir da base sintética.
"""

import json
import os

import numpy as np
import pandas as pd
import pytest

import dados_sinteticos as ds
import preparar_dados

# ---------------------------------------------------------------------------
# limpar_texto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entrada, esperado",
    [
        ("Harry Potter", "Harry Potter"),
        ("  com espaços  ", "com espaços"),
        ("invi\x01sível", "invisível"),
        ("tab\tremovido", "tabremovido"),
        ("linha 1\nlinha 2", "linha 1\nlinha 2"),  # a quebra de linha fica
        ("acentuação é mantida: ção", "acentuação é mantida: ção"),
        ("", ""),
        (None, ""),
        (float("nan"), ""),
        (123, ""),
    ],
)
def test_limpar_texto(entrada, esperado):
    assert preparar_dados.limpar_texto(entrada) == esperado


# ---------------------------------------------------------------------------
# conferir: precisa travar o script quando os dados estão errados
# ---------------------------------------------------------------------------


def _dados_ok():
    livros = pd.DataFrame({"livro_id": [1, 2]})
    avaliacoes = pd.DataFrame({"usuario_id": [1, 1], "livro_id": [1, 2], "nota": [5, 1]})
    tags = pd.DataFrame({"tag_id": [0, 1, 2], "tag": ["a", "b", "c"]})
    matriz = np.zeros((2, 3), dtype="float32")
    return livros, avaliacoes, tags, matriz


def test_conferir_aceita_dados_corretos():
    preparar_dados.conferir(*_dados_ok())


def test_conferir_recusa_livro_repetido():
    livros, avaliacoes, tags, matriz = _dados_ok()
    livros = pd.DataFrame({"livro_id": [1, 1]})
    with pytest.raises(AssertionError, match="repetido"):
        preparar_dados.conferir(livros, avaliacoes, tags, matriz)


def test_conferir_recusa_genome_desalinhado():
    livros, avaliacoes, tags, _ = _dados_ok()
    with pytest.raises(AssertionError, match="desalinhado"):
        preparar_dados.conferir(livros, avaliacoes, tags, np.zeros((3, 3)))


def test_conferir_recusa_genome_com_vazio():
    livros, avaliacoes, tags, matriz = _dados_ok()
    matriz[0, 0] = np.nan
    with pytest.raises(AssertionError, match="vazio"):
        preparar_dados.conferir(livros, avaliacoes, tags, matriz)


def test_conferir_recusa_nota_invalida():
    livros, avaliacoes, tags, matriz = _dados_ok()
    avaliacoes.loc[0, "nota"] = 6
    with pytest.raises(AssertionError, match="nota"):
        preparar_dados.conferir(livros, avaliacoes, tags, matriz)


def test_conferir_recusa_livro_inexistente():
    livros, avaliacoes, tags, matriz = _dados_ok()
    avaliacoes.loc[0, "livro_id"] = 99
    with pytest.raises(AssertionError, match="inexistente"):
        preparar_dados.conferir(livros, avaliacoes, tags, matriz)


# ---------------------------------------------------------------------------
# adicionar_estatisticas
# ---------------------------------------------------------------------------


def test_adicionar_estatisticas_conta_e_calcula_media():
    livros = pd.DataFrame({
        "livro_id": [1, 2], "titulo": ["A", "B"], "autores": ["x", "y"], "ano": [2000, 2001],
        "url": ["u1", "u2"], "capa": ["c1", "c2"], "descricao": ["d1", "d2"],
    })
    avaliacoes = pd.DataFrame({"usuario_id": [1, 2, 3], "livro_id": [1, 1, 1], "nota": [5, 4, 4]})
    r = preparar_dados.adicionar_estatisticas(livros, avaliacoes)

    assert list(r.columns) == ["livro_id", "titulo", "autores", "ano", "num_avaliacoes",
                               "media_avaliacoes", "url", "capa", "descricao"]
    assert r.loc[0, "num_avaliacoes"] == 3
    assert r.loc[0, "media_avaliacoes"] == pytest.approx(4.33)
    # Livro sem avaliações: 0 avaliações e média vazia
    assert r.loc[1, "num_avaliacoes"] == 0
    assert pd.isna(r.loc[1, "media_avaliacoes"])


# ---------------------------------------------------------------------------
# main sem a base
# ---------------------------------------------------------------------------


def test_main_sem_base_avisa_e_nao_cria_nada(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(preparar_dados, "PASTA_RAW", str(tmp_path / "raw"))
    monkeypatch.setattr(preparar_dados, "PASTA_PROCESSED", str(tmp_path / "processed"))
    preparar_dados.main()
    assert "base não encontrada" in capsys.readouterr().out
    assert not (tmp_path / "processed").exists()


# ---------------------------------------------------------------------------
# Integração: arquivos gerados a partir da base sintética
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def processados(pasta_dados):
    p = pasta_dados["processed"]
    return {
        "livros": pd.read_csv(os.path.join(p, "livros.csv")),
        "avaliacoes": pd.read_csv(os.path.join(p, "avaliacoes.csv")),
        "tags": pd.read_csv(os.path.join(p, "tags.csv")),
        "genome": np.load(os.path.join(p, "genome.npy")),
        "resumo": json.load(open(os.path.join(p, "resumo.json"), encoding="utf-8")),
        "base": pasta_dados["resumo_base"],
    }


def test_gera_todos_os_arquivos(pasta_dados):
    for nome in ["livros.csv", "avaliacoes.csv", "tags.csv", "genome.npy", "resumo.json"]:
        assert os.path.exists(os.path.join(pasta_dados["processed"], nome)), nome


def test_livro_repetido_e_removido(processados):
    livros = processados["livros"]
    assert livros["livro_id"].is_unique
    assert len(livros) == processados["base"]["livros"]
    assert "Duplicado" not in set(livros["titulo"])


def test_livros_ordenados_pelo_id(processados):
    assert processados["livros"]["livro_id"].is_monotonic_increasing


def test_colunas_em_portugues_e_sem_idioma(processados):
    colunas = set(processados["livros"].columns)
    assert {"livro_id", "titulo", "autores", "ano", "descricao", "capa"} <= colunas
    assert "lang" not in colunas and "title" not in colunas


def test_ano_zero_vira_desconhecido(processados):
    livros = processados["livros"].set_index("livro_id")
    assert pd.isna(livros.at[ds.livro_id(ds.POS_ANO_ZERO), "ano"])
    assert (livros["ano"].dropna() > 0).all()


def test_caracteres_invisiveis_removidos(processados):
    livros = processados["livros"].set_index("livro_id")
    sujo = ds.livro_id(ds.POS_TITULO_SUJO)
    assert livros.at[sujo, "titulo"] == "Livro sujo"
    assert livros.at[sujo, "descricao"] == "Linha 1\nLinha 2"


def test_avaliacoes_invalidas_removidas(processados):
    av = processados["avaliacoes"]
    assert av["nota"].between(1, 5).all()
    assert ds.LIVRO_INEXISTENTE not in set(av["livro_id"])
    assert not av.duplicated(["usuario_id", "livro_id"]).any()
    assert len(av) == processados["base"]["avaliacoes_validas"]


def test_avaliacao_repetida_mantem_a_ultima(processados):
    primeira = processados["base"]["primeira_avaliacao"]
    av = processados["avaliacoes"]
    linha = av[(av["usuario_id"] == primeira["user_id"]) & (av["livro_id"] == primeira["item_id"])]
    assert linha["nota"].tolist() == [3]  # a repetida (a última) tinha nota 3


def test_estatisticas_batem_com_as_avaliacoes(processados):
    livros = processados["livros"].set_index("livro_id")
    contagem = processados["avaliacoes"].groupby("livro_id").size()
    for lid, n in contagem.items():
        assert livros.at[lid, "num_avaliacoes"] == n
    sem = ds.livro_id(ds.POS_SEM_AVALIACOES)
    assert livros.at[sem, "num_avaliacoes"] == 0
    assert pd.isna(livros.at[sem, "media_avaliacoes"])


def test_tags_ordenadas_pelo_id(processados):
    tags = processados["tags"]
    assert tags["tag_id"].tolist() == list(range(len(ds.TAGS)))
    assert tags["tag"].tolist() == ds.TAGS


def test_genome_alinhado_com_livros_e_tags(processados):
    genome, livros, tags = processados["genome"], processados["livros"], processados["tags"]
    assert genome.shape == (len(livros), len(tags))
    assert genome.dtype == np.float32
    assert genome.min() >= 0 and genome.max() <= 1
    # Linha certa do livro e coluna certa da tag: um livro de fantasia
    # tem nota alta em "magic" e baixa em "space"
    p = livros.index[livros["livro_id"] == ds.livro_id(5)][0]
    magic, space = tags["tag"].tolist().index("magic"), tags["tag"].tolist().index("space")
    assert genome[p, magic] > 0.7
    assert genome[p, space] < 0.2


def test_resumo(processados):
    assert processados["resumo"] == {
        "livros": processados["base"]["livros"],
        "usuarios": processados["base"]["usuarios"],
        "avaliacoes": processados["base"]["avaliacoes_validas"],
        "tags": len(ds.TAGS),
    }

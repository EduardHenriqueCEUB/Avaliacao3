"""
Testes dos scripts de preparação (pasta scripts/):

    baixar_dados.py    sem internet: o download é simulado com um arquivo local
    treinar_modelo.py  arquivos gerados pelo treino na base sintética
    criar_banco.py     banco gerado a partir da base sintética
    avaliar_modelo.py  a métrica de acerto e o teste "deixar um de fora"
"""

import json
import os
import sqlite3
import zipfile

import numpy as np
import pandas as pd
import pytest

import avaliar_modelo
import baixar_dados
import criar_banco
import dados_sinteticos as ds
import treinar_modelo

# ---------------------------------------------------------------------------
# baixar_dados.py
# ---------------------------------------------------------------------------


@pytest.fixture
def pastas_download(tmp_path, monkeypatch):
    """Aponta o baixar_dados.py para uma pasta temporária."""
    dados = tmp_path / "data"
    dados.mkdir()
    monkeypatch.setattr(baixar_dados, "PASTA_DADOS", str(dados))
    monkeypatch.setattr(baixar_dados, "PASTA_RAW", str(dados / "raw"))
    monkeypatch.setattr(baixar_dados, "CAMINHO_ZIP", str(dados / "book-genome.zip"))
    return dados


def _criar_zip(caminho, pasta_extra="book-genome/", faltando=None):
    """Cria um zip parecido com o da GroupLens (com uma pasta extra dentro)."""
    with zipfile.ZipFile(caminho, "w") as z:
        for nome in baixar_dados.ARQUIVOS_NECESSARIOS:
            if nome != faltando:
                z.writestr(pasta_extra + nome, f"conteudo de {nome}")
        z.writestr(pasta_extra + "raw/reviews.json", "não deve ser extraído")


def test_arquivos_necessarios():
    nomes = [os.path.basename(n) for n in baixar_dados.ARQUIVOS_NECESSARIOS]
    assert nomes == ["metadata.json", "ratings.json", "tags.json", "glmer.csv"]


def test_url_padrao_da_grouplens():
    assert baixar_dados.URL_ZIP.startswith("https://files.grouplens.org/")


def test_arquivos_ja_extraidos(pastas_download):
    raw = pastas_download / "raw"
    raw.mkdir()
    assert not baixar_dados.arquivos_ja_extraidos()
    for nome in ["metadata.json", "ratings.json", "tags.json"]:
        (raw / nome).write_text("x")
    assert not baixar_dados.arquivos_ja_extraidos()  # ainda falta o glmer.csv
    (raw / "glmer.csv").write_text("x")
    assert baixar_dados.arquivos_ja_extraidos()


def test_extrair_so_os_arquivos_usados(pastas_download):
    (pastas_download / "raw").mkdir()
    _criar_zip(baixar_dados.CAMINHO_ZIP)
    baixar_dados.extrair_arquivos()
    extraidos = sorted(os.listdir(pastas_download / "raw"))
    assert extraidos == ["glmer.csv", "metadata.json", "ratings.json", "tags.json"]
    assert (pastas_download / "raw" / "glmer.csv").read_text() == "conteudo de scores/glmer.csv"


def test_extrair_zip_sem_pasta_extra(pastas_download):
    (pastas_download / "raw").mkdir()
    _criar_zip(baixar_dados.CAMINHO_ZIP, pasta_extra="")
    baixar_dados.extrair_arquivos()
    assert baixar_dados.arquivos_ja_extraidos()


def test_extrair_avisa_quando_falta_arquivo_no_zip(pastas_download):
    (pastas_download / "raw").mkdir()
    _criar_zip(baixar_dados.CAMINHO_ZIP, faltando="raw/ratings.json")
    with pytest.raises(FileNotFoundError, match="ratings.json"):
        baixar_dados.extrair_arquivos()


def test_checar_espaco_em_disco(pastas_download, monkeypatch, capsys):
    baixar_dados.checar_espaco_em_disco(0)  # sempre há 0 GB livres

    class PoucoEspaco:
        free = 1024 ** 3  # 1 GB

    monkeypatch.setattr(baixar_dados.shutil, "disk_usage", lambda _: PoucoEspaco)
    with pytest.raises(SystemExit) as erro:
        baixar_dados.checar_espaco_em_disco(2.5)
    assert erro.value.code == 1
    assert "espaço livre insuficiente" in capsys.readouterr().out


def test_main_nao_faz_nada_se_ja_extraido(pastas_download, monkeypatch, capsys):
    raw = pastas_download / "raw"
    raw.mkdir()
    for nome in ["metadata.json", "ratings.json", "tags.json", "glmer.csv"]:
        (raw / nome).write_text("x")
    monkeypatch.setattr(baixar_dados, "baixar_zip", lambda: pytest.fail("não devia baixar"))
    baixar_dados.main()
    assert "Nada a fazer" in capsys.readouterr().out


def test_main_usa_o_zip_que_ja_esta_na_pasta(pastas_download, monkeypatch):
    _criar_zip(baixar_dados.CAMINHO_ZIP)
    monkeypatch.setattr(baixar_dados, "baixar_zip", lambda: pytest.fail("não devia baixar"))
    baixar_dados.main()
    assert baixar_dados.arquivos_ja_extraidos()
    assert not os.path.exists(baixar_dados.CAMINHO_ZIP)  # apagado para liberar espaço


def test_main_mantem_o_zip_se_configurado(pastas_download, monkeypatch):
    _criar_zip(baixar_dados.CAMINHO_ZIP)
    monkeypatch.setattr(baixar_dados, "APAGAR_ZIP_DEPOIS", False)
    baixar_dados.main()
    assert os.path.exists(baixar_dados.CAMINHO_ZIP)


def test_main_com_zip_corrompido(pastas_download, capsys):
    with open(baixar_dados.CAMINHO_ZIP, "wb") as f:
        f.write(b"isto nao e um zip")
    with pytest.raises(SystemExit) as erro:
        baixar_dados.main()
    assert erro.value.code == 1
    assert "corrompido" in capsys.readouterr().out
    assert os.path.exists(baixar_dados.CAMINHO_ZIP)  # não apaga: a pessoa decide


def test_baixar_zip_simulado(pastas_download, tmp_path, monkeypatch):
    # O "site" é um arquivo local (file://): testa o download sem internet
    origem = tmp_path / "site" / "book-genome.zip"
    origem.parent.mkdir()
    _criar_zip(str(origem))
    monkeypatch.setattr(baixar_dados, "URL_ZIP", origem.as_uri())

    baixar_dados.main()
    assert baixar_dados.arquivos_ja_extraidos()
    assert not os.path.exists(baixar_dados.CAMINHO_ZIP + ".parcial")


def test_baixar_zip_grava_parcial_e_renomeia(pastas_download, tmp_path, monkeypatch):
    origem = tmp_path / "arquivo.zip"
    origem.write_bytes(b"0123456789" * 1000)
    monkeypatch.setattr(baixar_dados, "URL_ZIP", origem.as_uri())
    baixar_dados.baixar_zip()
    assert open(baixar_dados.CAMINHO_ZIP, "rb").read() == origem.read_bytes()
    assert not os.path.exists(baixar_dados.CAMINHO_ZIP + ".parcial")


def test_main_com_falha_no_download(pastas_download, monkeypatch, capsys):
    def falha():
        open(baixar_dados.CAMINHO_ZIP + ".parcial", "wb").close()  # sobrou um pedaço
        raise baixar_dados.urllib.error.URLError("sem internet")

    monkeypatch.setattr(baixar_dados, "baixar_zip", falha)
    with pytest.raises(SystemExit) as erro:
        baixar_dados.main()
    assert erro.value.code == 1
    saida = capsys.readouterr().out
    assert "ERRO no download" in saida and "Plano B" in saida
    assert not os.path.exists(baixar_dados.CAMINHO_ZIP + ".parcial")


# ---------------------------------------------------------------------------
# treinar_modelo.py
# ---------------------------------------------------------------------------


def test_treino_gera_os_arquivos(pasta_dados):
    pasta = pasta_dados["modelo"]
    vizinhos = np.load(os.path.join(pasta, "vizinhos_cf.npz"))
    assert vizinhos["indices"].shape == (60, 10)
    assert vizinhos["similaridades"].shape == (60, 10)
    assert vizinhos["indices"].min() >= 0 and vizinhos["indices"].max() < 60

    info = json.load(open(os.path.join(pasta, "info_treino.json"), encoding="utf-8"))
    assert info == {"livros": 60, "avaliacoes": pasta_dados["resumo_base"]["avaliacoes_validas"],
                    "vizinhos_por_livro": 10}


def test_treino_vizinhos_sao_do_mesmo_genero(pasta_dados):
    # O colaborativo não sabe nada das tags: só olha as avaliações. Mesmo
    # assim, o vizinho mais parecido de cada livro tem que ser do mesmo gênero.
    vizinhos = np.load(os.path.join(pasta_dados["modelo"], "vizinhos_cf.npz"))
    sem_avaliacao = ds.POS_SEM_AVALIACOES
    acertos = [
        ds.genero_do_livro(p) == ds.genero_do_livro(int(vizinhos["indices"][p, 0]))
        for p in range(60) if p != sem_avaliacao
    ]
    assert all(acertos)


def test_carregar_avaliacoes_acrescenta_a_posicao(pasta_dados, monkeypatch):
    monkeypatch.setattr(treinar_modelo, "PASTA_PROCESSED", pasta_dados["processed"])
    livros = pd.read_csv(os.path.join(pasta_dados["processed"], "livros.csv"))
    av = treinar_modelo.carregar_avaliacoes(livros)
    assert (av["posicao"] >= 0).all()
    np.testing.assert_array_equal(livros["livro_id"].to_numpy()[av["posicao"]], av["livro_id"])


def test_treino_sem_dados_avisa(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(treinar_modelo, "PASTA_PROCESSED", str(tmp_path))
    monkeypatch.setattr(treinar_modelo, "PASTA_MODELO", str(tmp_path / "modelo"))
    treinar_modelo.main()
    assert "dados tratados não encontrados" in capsys.readouterr().out
    assert not (tmp_path / "modelo").exists()


# ---------------------------------------------------------------------------
# criar_banco.py
# ---------------------------------------------------------------------------


def test_banco_tem_os_usuarios_e_avaliacoes_da_base(pasta_dados):
    con = sqlite3.connect(pasta_dados["banco"])
    usuarios = con.execute("SELECT COUNT(*) FROM usuarios WHERE origem = 'base'").fetchone()[0]
    avaliacoes = con.execute("SELECT COUNT(*) FROM avaliacoes").fetchone()[0]
    sem_nome = con.execute("SELECT COUNT(*) FROM usuarios WHERE nome IS NULL").fetchone()[0]
    con.close()
    assert usuarios == sem_nome == ds.NUM_USUARIOS
    assert avaliacoes == pasta_dados["resumo_base"]["avaliacoes_validas"]


def test_banco_igual_ao_csv(pasta_dados):
    csv = pd.read_csv(os.path.join(pasta_dados["processed"], "avaliacoes.csv"))
    con = sqlite3.connect(pasta_dados["banco"])
    db = pd.read_sql("SELECT usuario_id, livro_id, nota FROM avaliacoes", con)
    con.close()
    ordem = ["usuario_id", "livro_id"]
    pd.testing.assert_frame_equal(
        csv.sort_values(ordem).reset_index(drop=True)[["usuario_id", "livro_id", "nota"]],
        db.sort_values(ordem).reset_index(drop=True),
        check_dtype=False,
    )


def test_criar_banco_nao_apaga_banco_existente(pasta_dados, caminho_banco_copia, monkeypatch, capsys):
    con = sqlite3.connect(caminho_banco_copia)
    with con:
        con.execute("INSERT INTO usuarios (nome, origem) VALUES ('Criado pela API', 'api')")
    con.close()

    monkeypatch.setattr(criar_banco, "CAMINHO_BANCO", caminho_banco_copia)
    monkeypatch.setattr(criar_banco, "PASTA_PROCESSED", pasta_dados["processed"])
    criar_banco.main()
    assert "Nada a fazer" in capsys.readouterr().out

    con = sqlite3.connect(caminho_banco_copia)
    assert con.execute("SELECT COUNT(*) FROM usuarios WHERE origem = 'api'").fetchone()[0] == 1
    con.close()


def test_criar_banco_sem_dados_avisa(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(criar_banco, "CAMINHO_BANCO", str(tmp_path / "banco.db"))
    monkeypatch.setattr(criar_banco, "PASTA_PROCESSED", str(tmp_path))
    criar_banco.main()
    assert "dados tratados não encontrados" in capsys.readouterr().out
    assert not (tmp_path / "banco.db").exists()


# ---------------------------------------------------------------------------
# avaliar_modelo.py
# ---------------------------------------------------------------------------


def test_acertou():
    pontos = np.arange(20, dtype="float64")  # o livro 19 tem a maior pontuação
    assert avaliar_modelo.acertou(pontos, ja_avaliados=[], alvo=19)
    assert avaliar_modelo.acertou(pontos, ja_avaliados=[], alvo=10)      # 10º lugar
    assert not avaliar_modelo.acertou(pontos, ja_avaliados=[], alvo=9)   # 11º lugar
    # Tirando os 2 primeiros (já avaliados), o 9 entra no top 10
    assert avaliar_modelo.acertou(pontos, ja_avaliados=[19, 18], alvo=9)


def test_acertou_nao_altera_as_pontuacoes():
    pontos = np.arange(20, dtype="float64")
    avaliar_modelo.acertou(pontos, ja_avaliados=[19], alvo=0)
    assert pontos[19] == 19


def test_avaliar_grupo_na_base_sintetica(pasta_dados, monkeypatch):
    monkeypatch.setattr(avaliar_modelo, "NUM_USUARIOS_TESTE", 15)
    monkeypatch.setattr(avaliar_modelo, "TOP_N", 5)
    p = pasta_dados["processed"]
    monkeypatch.setattr(treinar_modelo, "PASTA_PROCESSED", p)
    livros = pd.read_csv(os.path.join(p, "livros.csv"))
    genome = np.load(os.path.join(p, "genome.npy"))
    tags = pd.read_csv(os.path.join(p, "tags.csv"))["tag"]
    avaliacoes = treinar_modelo.carregar_avaliacoes(livros)

    r = avaliar_modelo.avaliar_grupo(livros, genome, tags, avaliacoes, minimo=5, maximo=None)

    assert 0 < r["usuarios_testados"] <= 15
    chaves = {"usuarios_testados", "so_popularidade"} | {
        f"peso_conteudo_{peso}" for peso in avaliar_modelo.PESOS_CONTEUDO}
    assert set(r) == chaves
    for chave in chaves - {"usuarios_testados"}:
        assert 0 <= r[chave] <= 1
    # Na base sintética os gêneros são bem separados: o híbrido tem que
    # acertar mais do que só recomendar os populares
    assert r["peso_conteudo_0.5"] > r["so_popularidade"]


def test_avaliar_grupo_e_reproduzivel(pasta_dados, monkeypatch):
    monkeypatch.setattr(avaliar_modelo, "NUM_USUARIOS_TESTE", 10)
    p = pasta_dados["processed"]
    monkeypatch.setattr(treinar_modelo, "PASTA_PROCESSED", p)
    livros = pd.read_csv(os.path.join(p, "livros.csv"))
    genome = np.load(os.path.join(p, "genome.npy"))
    tags = pd.read_csv(os.path.join(p, "tags.csv"))["tag"]
    avaliacoes = treinar_modelo.carregar_avaliacoes(livros)
    a = avaliar_modelo.avaliar_grupo(livros, genome, tags, avaliacoes, 5, 15)
    b = avaliar_modelo.avaliar_grupo(livros, genome, tags, avaliacoes, 5, 15)
    assert a == b  # a semente fixa faz o sorteio ser sempre o mesmo


def test_avaliar_modelo_main_grava_o_resultado(pasta_dados, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(avaliar_modelo, "NUM_USUARIOS_TESTE", 10)
    monkeypatch.setattr(avaliar_modelo, "GRUPOS", [("teste", 5, None)])
    monkeypatch.setattr(avaliar_modelo, "PASTA_PROCESSED", pasta_dados["processed"])
    monkeypatch.setattr(treinar_modelo, "PASTA_PROCESSED", pasta_dados["processed"])
    monkeypatch.setattr(avaliar_modelo, "PASTA_MODELO", str(tmp_path / "modelo"))

    avaliar_modelo.main()

    resultado = json.load(open(tmp_path / "modelo" / "avaliacao.json", encoding="utf-8"))
    assert resultado["top_n"] == avaliar_modelo.TOP_N
    assert resultado["teste"]["usuarios_testados"] == 10
    saida = capsys.readouterr().out
    assert "só colaborativo" in saida and "só conteúdo" in saida

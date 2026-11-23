"""
conftest.py

Arquivo especial do pytest: as "fixtures" definidas aqui ficam disponíveis
para todos os testes, sem precisar importar.

Uma fixture é uma função que prepara algo que o teste usa (uma pasta com
dados, um banco, a API ligada...). O teste só precisa pedir pelo nome dela
como parâmetro, e o pytest entrega pronto.

Regra de ouro dos testes deste projeto:
    NENHUM teste mexe na pasta data/ de verdade. Tudo é feito em pastas
    temporárias, com a base sintética de tests/dados_sinteticos.py.
"""

import importlib.util
import os
import shutil
import sys
import tempfile

import pytest

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_TESTES = os.path.dirname(os.path.abspath(__file__))

# Proteção: o app/banco.py lê a variável BANCO_PATH na hora em que é
# importado. Apontando para uma pasta temporária ANTES de qualquer import do
# app, garantimos que nenhum teste grava no data/banco.db de verdade.
_PASTA_PROTECAO = tempfile.mkdtemp(prefix="testes_recomendacao_")
os.environ["BANCO_PATH"] = os.path.join(_PASTA_PROTECAO, "banco_nao_usar.db")

# Permite importar o app/, os scripts/ e os módulos da pasta tests/
for caminho in (PASTA_PROJETO, os.path.join(PASTA_PROJETO, "scripts"), PASTA_TESTES):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

import criar_banco  # noqa: E402
import dados_sinteticos  # noqa: E402
import preparar_dados  # noqa: E402
import treinar_modelo  # noqa: E402

from app import banco  # noqa: E402
from app.modelo import Recomendador  # noqa: E402


def carregar_docker_preparar():
    """Importa o docker/preparar.py. A pasta docker/ não é um pacote do
    Python, então o import é feito pelo caminho do arquivo."""
    caminho = os.path.join(PASTA_PROJETO, "docker", "preparar.py")
    spec = importlib.util.spec_from_file_location("docker_preparar", caminho)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ---------------------------------------------------------------------------
# Base sintética e pipeline completo (feitos UMA vez para todos os testes)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def pasta_dados(tmp_path_factory):
    """Roda o caminho completo dos scripts, como no README (passos 4, 5 e 7),
    só que com a base sintética e numa pasta temporária:

        data/raw/        base sintética (no lugar do download)
        data/processed/  gerado pelo scripts/preparar_dados.py
        data/modelo/     gerado pelo scripts/treinar_modelo.py
        data/banco.db    gerado pelo scripts/criar_banco.py
    """
    raiz = tmp_path_factory.mktemp("data")
    pastas = {
        "raiz": str(raiz),
        "raw": str(raiz / "raw"),
        "processed": str(raiz / "processed"),
        "modelo": str(raiz / "modelo"),
        "banco": str(raiz / "banco.db"),
    }
    pastas["resumo_base"] = dados_sinteticos.gerar_base(pastas["raw"])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(preparar_dados, "PASTA_RAW", pastas["raw"])
        mp.setattr(preparar_dados, "PASTA_PROCESSED", pastas["processed"])
        mp.setattr(preparar_dados, "TAMANHO_PEDACO", 100)  # força a leitura em vários pedaços
        preparar_dados.main()

        mp.setattr(treinar_modelo, "PASTA_PROCESSED", pastas["processed"])
        mp.setattr(treinar_modelo, "PASTA_MODELO", pastas["modelo"])
        mp.setattr(treinar_modelo, "NUM_VIZINHOS", 10)  # a base tem só 60 livros
        treinar_modelo.main()

        mp.setattr(criar_banco, "PASTA_PROCESSED", pastas["processed"])
        mp.setattr(criar_banco, "CAMINHO_BANCO", pastas["banco"])
        mp.setattr(criar_banco, "conectar", lambda: banco.conectar(pastas["banco"]))
        mp.setattr(criar_banco, "TAMANHO_LOTE", 100)  # força a gravação em vários lotes
        criar_banco.main()

    return pastas


@pytest.fixture
def modelo(pasta_dados):
    """Um Recomendador novo para cada teste (adicionar livros muda o modelo)."""
    return Recomendador.carregar(pasta_dados["processed"], pasta_dados["modelo"])


# ---------------------------------------------------------------------------
# Banco de dados
# ---------------------------------------------------------------------------


@pytest.fixture
def conexao(tmp_path):
    """Um banco vazio, só com as tabelas, para os testes do app/banco.py."""
    con = banco.conectar(str(tmp_path / "teste.db"))
    banco.criar_tabelas(con)
    yield con
    con.close()


@pytest.fixture
def caminho_banco_copia(pasta_dados, tmp_path):
    """Cópia do banco criado pelo pipeline. Cada teste da API recebe a sua,
    então o que um teste grava não aparece no outro."""
    destino = str(tmp_path / "banco.db")
    shutil.copy(pasta_dados["banco"], destino)
    return destino


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


@pytest.fixture
def configurar_api(pasta_dados, caminho_banco_copia, monkeypatch):
    """Aponta a API para os arquivos temporários (modelo e banco)."""
    from app import main

    carregar_original = Recomendador.carregar.__func__
    monkeypatch.setattr(main, "PASTA_MODELO", pasta_dados["modelo"])
    monkeypatch.setattr(banco, "CAMINHO_BANCO", caminho_banco_copia)
    monkeypatch.setattr(banco, "conectar", _conectar_em(caminho_banco_copia))
    monkeypatch.setattr(
        Recomendador, "carregar",
        classmethod(lambda cls: carregar_original(cls, pasta_dados["processed"], pasta_dados["modelo"])),
    )
    return main.app


def _conectar_em(caminho):
    conectar_original = banco.conectar

    def conectar(c=None):
        return conectar_original(c or caminho)

    return conectar


@pytest.fixture
def cliente(configurar_api):
    """A API ligada (com o lifespan rodando), pronta para receber pedidos.

    O TestClient do FastAPI faz os pedidos HTTP direto na aplicação, sem
    precisar ligar o uvicorn nem abrir uma porta.
    """
    from fastapi.testclient import TestClient

    with TestClient(configurar_api) as c:
        yield c

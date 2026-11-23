"""
Testes do app/schemas.py (formatos de entrada e saída da API).

O Pydantic valida os dados antes de chegarem no código da API. Aqui
conferimos que as regras (nota de 1 a 5, nome obrigatório...) funcionam.
"""

import pytest
from pydantic import ValidationError

from app.schemas import (
    AvaliacaoEntrada,
    AvaliacaoSalvaSaida,
    LivroEntrada,
    NotaEntrada,
    PreferenciasEntrada,
    RecomendacoesSaida,
    UsuarioEntrada,
    UsuarioSaida,
)


@pytest.mark.parametrize("nota", [1, 2, 3, 4, 5])
def test_nota_valida(nota):
    assert NotaEntrada(nota=nota).nota == nota
    assert AvaliacaoEntrada(livro_id=1, nota=nota).nota == nota


@pytest.mark.parametrize("nota", [0, 6, -1, 10, "cinco", None])
def test_nota_invalida(nota):
    with pytest.raises(ValidationError):
        NotaEntrada(nota=nota)
    with pytest.raises(ValidationError):
        AvaliacaoEntrada(livro_id=1, nota=nota)


def test_usuario_entrada_valores_padrao():
    u = UsuarioEntrada(nome="Ana")
    assert u.tags_favoritas == [] and u.avaliacoes == []


def test_usuario_entrada_completo():
    u = UsuarioEntrada(nome="Ana", tags_favoritas=["magic"],
                       avaliacoes=[{"livro_id": 10, "nota": 5}])
    assert u.avaliacoes[0].livro_id == 10


@pytest.mark.parametrize("nome", ["", "x" * 101])
def test_usuario_nome_invalido(nome):
    with pytest.raises(ValidationError):
        UsuarioEntrada(nome=nome)


def test_usuario_sem_nome():
    with pytest.raises(ValidationError):
        UsuarioEntrada()


def test_usuario_no_maximo_20_tags():
    UsuarioEntrada(nome="Ana", tags_favoritas=["t"] * 20)
    with pytest.raises(ValidationError):
        UsuarioEntrada(nome="Ana", tags_favoritas=["t"] * 21)


def test_usuario_com_avaliacao_invalida():
    with pytest.raises(ValidationError):
        UsuarioEntrada(nome="Ana", avaliacoes=[{"livro_id": 10, "nota": 9}])


def test_preferencias():
    assert PreferenciasEntrada(tags_favoritas=[]).tags_favoritas == []
    with pytest.raises(ValidationError):
        PreferenciasEntrada(tags_favoritas=["t"] * 21)
    with pytest.raises(ValidationError):
        PreferenciasEntrada()


def test_livro_entrada_valido():
    livro = LivroEntrada(titulo="T", autores="A", tags={"magic": 0.5})
    assert livro.ano is None


@pytest.mark.parametrize(
    "dados",
    [
        {"titulo": "", "autores": "A", "tags": {"magic": 1}},
        {"titulo": "T", "autores": "", "tags": {"magic": 1}},
        {"titulo": "T", "autores": "A", "tags": {}},             # pelo menos uma tag
        {"titulo": "T", "autores": "A"},                         # tags obrigatórias
        {"titulo": "T", "autores": "A", "ano": -1, "tags": {"magic": 1}},
        {"titulo": "T", "autores": "A", "ano": 2101, "tags": {"magic": 1}},
        {"titulo": "x" * 301, "autores": "A", "tags": {"magic": 1}},
    ],
)
def test_livro_entrada_invalido(dados):
    with pytest.raises(ValidationError):
        LivroEntrada(**dados)


def test_saidas_aceitam_so_valores_conhecidos():
    with pytest.raises(ValidationError):
        AvaliacaoSalvaSaida(usuario_id=1, livro_id=1, nota=5, situacao="outra")
    with pytest.raises(ValidationError):
        UsuarioSaida(usuario_id=1, origem="outra", tags_favoritas=[], num_avaliacoes=0, criado_em="x")
    with pytest.raises(ValidationError):
        RecomendacoesSaida(usuario_id=1, estrategia="outra", peso_conteudo=0.5, recomendacoes=[])


def test_exemplos_do_swagger_sao_validos():
    # Os exemplos que aparecem no /docs precisam passar na validação
    for classe in (UsuarioEntrada, LivroEntrada, NotaEntrada, PreferenciasEntrada):
        for exemplo in classe.model_config["json_schema_extra"]["examples"]:
            classe(**exemplo)

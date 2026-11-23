"""
Testes do app/banco.py (banco de dados SQLite da API).

Cada teste recebe um banco novo e vazio (fixture "conexao" do conftest.py),
num arquivo temporário. O data/banco.db de verdade nunca é usado.
"""

import sqlite3

import pytest

from app import banco


def test_criar_tabelas(conexao):
    tabelas = {linha[0] for linha in conexao.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"usuarios", "avaliacoes", "livros_novos"} <= tabelas


def test_criar_tabelas_pode_rodar_de_novo(conexao):
    banco.criar_usuario(conexao, "Ana")
    banco.criar_tabelas(conexao)  # CREATE TABLE IF NOT EXISTS: não apaga nada
    assert banco.contar(conexao)["usuarios"] == 1


def test_conectar_liga_chaves_estrangeiras(conexao):
    assert conexao.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_caminho_do_banco_vem_da_variavel_de_ambiente():
    # O conftest.py define BANCO_PATH antes de importar o app (proteção)
    import os
    assert banco.CAMINHO_BANCO == os.environ["BANCO_PATH"]


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


def test_criar_e_buscar_usuario(conexao):
    uid = banco.criar_usuario(conexao, "Ana", tags_favoritas=["magic", "ficção"],
                              avaliacoes=[(10, 5), (20, 3)])
    u = banco.buscar_usuario(conexao, uid)
    assert u["usuario_id"] == uid
    assert u["nome"] == "Ana"
    assert u["origem"] == "api"
    assert u["tags_favoritas"] == ["magic", "ficção"]
    assert u["num_avaliacoes"] == 2
    assert u["criado_em"]


def test_criar_usuario_sem_tags_e_sem_avaliacoes(conexao):
    uid = banco.criar_usuario(conexao, "Bia")
    u = banco.buscar_usuario(conexao, uid)
    assert u["tags_favoritas"] == []
    assert u["num_avaliacoes"] == 0


def test_ids_de_usuario_continuam_depois_dos_da_base(conexao):
    with conexao:
        conexao.execute("INSERT INTO usuarios (usuario_id, origem) VALUES (500, 'base')")
    assert banco.criar_usuario(conexao, "Novo") == 501
    assert banco.buscar_usuario(conexao, 500)["origem"] == "base"
    assert banco.buscar_usuario(conexao, 500)["nome"] is None


def test_buscar_usuario_inexistente(conexao):
    assert banco.buscar_usuario(conexao, 12345) is None


def test_criar_usuario_com_avaliacao_repetida_fica_a_ultima(conexao):
    uid = banco.criar_usuario(conexao, "Ana", avaliacoes=[(10, 5), (10, 2)])
    assert banco.avaliacoes_do_usuario(conexao, uid) == {10: 2}


def test_criar_usuario_e_tudo_ou_nada(conexao):
    # Nota 9 viola a regra do banco (1 a 5): o usuário também não pode ficar gravado
    with pytest.raises(sqlite3.IntegrityError):
        banco.criar_usuario(conexao, "Erro", avaliacoes=[(10, 5), (20, 9)])
    assert banco.contar(conexao) == {"usuarios": 0, "avaliacoes": 0, "livros_novos": 0}


def test_atualizar_tags_favoritas(conexao):
    uid = banco.criar_usuario(conexao, "Ana", tags_favoritas=["a"])
    banco.atualizar_tags_favoritas(conexao, uid, ["b", "c"])
    assert banco.buscar_usuario(conexao, uid)["tags_favoritas"] == ["b", "c"]
    banco.atualizar_tags_favoritas(conexao, uid, [])
    assert banco.buscar_usuario(conexao, uid)["tags_favoritas"] == []


# ---------------------------------------------------------------------------
# Avaliações
# ---------------------------------------------------------------------------


def test_salvar_avaliacao_cria_e_depois_atualiza(conexao):
    uid = banco.criar_usuario(conexao, "Ana")
    assert banco.salvar_avaliacao(conexao, uid, 10, 4) == "criada"
    assert banco.salvar_avaliacao(conexao, uid, 10, 1) == "atualizada"
    assert banco.avaliacoes_do_usuario(conexao, uid) == {10: 1}


def test_avaliacoes_de_usuarios_diferentes_nao_se_misturam(conexao):
    a = banco.criar_usuario(conexao, "Ana", avaliacoes=[(10, 5)])
    b = banco.criar_usuario(conexao, "Bia", avaliacoes=[(10, 1), (20, 2)])
    assert banco.avaliacoes_do_usuario(conexao, a) == {10: 5}
    assert banco.avaliacoes_do_usuario(conexao, b) == {10: 1, 20: 2}


def test_avaliacoes_de_usuario_sem_avaliacoes(conexao):
    uid = banco.criar_usuario(conexao, "Ana")
    assert banco.avaliacoes_do_usuario(conexao, uid) == {}


@pytest.mark.parametrize("nota", [0, 6, -1])
def test_banco_recusa_nota_fora_de_1_a_5(conexao, nota):
    uid = banco.criar_usuario(conexao, "Ana")
    with pytest.raises(sqlite3.IntegrityError):
        banco.salvar_avaliacao(conexao, uid, 10, nota)


def test_banco_recusa_avaliacao_de_usuario_inexistente(conexao):
    with pytest.raises(sqlite3.IntegrityError):
        banco.salvar_avaliacao(conexao, 999, 10, 5)


def test_remover_avaliacao(conexao):
    uid = banco.criar_usuario(conexao, "Ana", avaliacoes=[(10, 5), (20, 4)])
    assert banco.remover_avaliacao(conexao, uid, 10) is True
    assert banco.avaliacoes_do_usuario(conexao, uid) == {20: 4}
    assert banco.remover_avaliacao(conexao, uid, 10) is False  # já não existe


def test_apagar_usuario_apaga_as_avaliacoes(conexao):
    uid = banco.criar_usuario(conexao, "Ana", avaliacoes=[(10, 5)])
    with conexao:
        conexao.execute("DELETE FROM usuarios WHERE usuario_id = ?", (uid,))
    assert banco.contar(conexao)["avaliacoes"] == 0  # ON DELETE CASCADE


# ---------------------------------------------------------------------------
# Livros novos
# ---------------------------------------------------------------------------


def test_salvar_e_listar_livros_novos(conexao):
    banco.salvar_livro_novo(conexao, 2000, "Segundo", "B", None, {"space": 1.0})
    banco.salvar_livro_novo(conexao, 1000, "Primeiro", "A", 2026, {"magic": 0.5, "ação": 1.0})
    assert banco.listar_livros_novos(conexao) == [
        {"livro_id": 1000, "titulo": "Primeiro", "autores": "A", "ano": 2026,
         "tags": {"magic": 0.5, "ação": 1.0}},
        {"livro_id": 2000, "titulo": "Segundo", "autores": "B", "ano": None,
         "tags": {"space": 1.0}},
    ]


def test_listar_livros_novos_vazio(conexao):
    assert banco.listar_livros_novos(conexao) == []


def test_livro_novo_com_id_repetido(conexao):
    banco.salvar_livro_novo(conexao, 1000, "A", "A", None, {})
    with pytest.raises(sqlite3.IntegrityError):
        banco.salvar_livro_novo(conexao, 1000, "B", "B", None, {})


# ---------------------------------------------------------------------------
# Estatísticas
# ---------------------------------------------------------------------------


def test_contar(conexao):
    assert banco.contar(conexao) == {"usuarios": 0, "avaliacoes": 0, "livros_novos": 0}
    banco.criar_usuario(conexao, "Ana", avaliacoes=[(10, 5), (20, 4)])
    banco.criar_usuario(conexao, "Bia", avaliacoes=[(10, 1)])
    banco.salvar_livro_novo(conexao, 3000, "Novo", "X", None, {})
    assert banco.contar(conexao) == {"usuarios": 2, "avaliacoes": 3, "livros_novos": 1}


def test_dados_ficam_gravados_no_arquivo(tmp_path):
    # Fecha e abre de novo: o que foi gravado continua lá
    caminho = str(tmp_path / "persistencia.db")
    con = banco.conectar(caminho)
    banco.criar_tabelas(con)
    uid = banco.criar_usuario(con, "Ana", avaliacoes=[(10, 5)])
    con.close()

    con = banco.conectar(caminho)
    assert banco.buscar_usuario(con, uid)["nome"] == "Ana"
    assert banco.avaliacoes_do_usuario(con, uid) == {10: 5}
    con.close()

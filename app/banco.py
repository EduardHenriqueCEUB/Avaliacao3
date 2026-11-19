"""
banco.py

PASSO 4 do projeto: o banco de dados da API (SQLite).

Por que um banco de dados?
    A API precisa guardar o que muda: usuários novos, avaliações novas ou
    alteradas, tags favoritas e livros novos. Se isso ficasse só na memória,
    tudo se perderia quando a API fosse reiniciada.

Por que SQLite?
    O SQLite é um banco de dados que fica num arquivo só (data/banco.db).
    Já vem com o Python (não precisa instalar nada), não precisa de um
    servidor separado e aguenta tranquilamente o tamanho deste projeto.

Tabelas:
    usuarios      usuario_id, nome, origem ("base" ou "api"), tags_favoritas, criado_em
    avaliacoes    usuario_id, livro_id, nota (1 a 5)
    livros_novos  livros cadastrados pela API (os 9.374 da base ficam no livros.csv)

O banco é criado e preenchido com os usuários e avaliações da base pelo
scripts/criar_banco.py.
"""

import json
import os
import sqlite3

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# O caminho pode ser trocado pela variável de ambiente BANCO_PATH
# (útil no Docker, para guardar o banco num volume)
CAMINHO_BANCO = os.environ.get("BANCO_PATH", os.path.join(PASTA_PROJETO, "data", "banco.db"))

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    usuario_id      INTEGER PRIMARY KEY,
    nome            TEXT,
    origem          TEXT NOT NULL DEFAULT 'api',
    tags_favoritas  TEXT NOT NULL DEFAULT '[]',
    criado_em       TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- WITHOUT ROWID guarda as avaliações ordenadas por (usuario_id, livro_id).
-- Assim, buscar todas as avaliações de um usuário é muito rápido, porque
-- elas ficam juntas no arquivo.
CREATE TABLE IF NOT EXISTS avaliacoes (
    usuario_id  INTEGER NOT NULL REFERENCES usuarios(usuario_id) ON DELETE CASCADE,
    livro_id    INTEGER NOT NULL,
    nota        INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    PRIMARY KEY (usuario_id, livro_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS livros_novos (
    livro_id   INTEGER PRIMARY KEY,
    titulo     TEXT NOT NULL,
    autores    TEXT NOT NULL,
    ano        INTEGER,
    tags       TEXT NOT NULL DEFAULT '{}',
    criado_em  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def conectar(caminho=CAMINHO_BANCO):
    """Abre uma conexão com o banco.

    check_same_thread=False: o FastAPI pode abrir a conexão numa thread e
    usá-la em outra. Cada pedido à API tem a sua própria conexão, então isso
    é seguro aqui.
    """
    conexao = sqlite3.connect(caminho, check_same_thread=False)
    conexao.row_factory = sqlite3.Row  # permite ler as colunas pelo nome
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def criar_tabelas(conexao):
    conexao.executescript(ESQUEMA)


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------

def _usuario_para_dict(linha, num_avaliacoes):
    return {
        "usuario_id": linha["usuario_id"],
        "nome": linha["nome"],
        "origem": linha["origem"],
        "tags_favoritas": json.loads(linha["tags_favoritas"]),
        "num_avaliacoes": num_avaliacoes,
        "criado_em": linha["criado_em"],
    }


def buscar_usuario(conexao, usuario_id):
    """Dados de um usuário, ou None se ele não existe."""
    linha = conexao.execute(
        "SELECT * FROM usuarios WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()
    if linha is None:
        return None
    num = conexao.execute(
        "SELECT COUNT(*) FROM avaliacoes WHERE usuario_id = ?", (usuario_id,)
    ).fetchone()[0]
    return _usuario_para_dict(linha, num)


def criar_usuario(conexao, nome, tags_favoritas=(), avaliacoes=()):
    """Cria um usuário (com tags e avaliações opcionais) e devolve o id dele.

    O "with conexao" faz tudo numa transação: ou grava tudo, ou nada.
    """
    with conexao:
        cursor = conexao.execute(
            "INSERT INTO usuarios (nome, origem, tags_favoritas) VALUES (?, 'api', ?)",
            (nome, json.dumps(list(tags_favoritas), ensure_ascii=False)),
        )
        usuario_id = cursor.lastrowid
        conexao.executemany(
            "INSERT OR REPLACE INTO avaliacoes (usuario_id, livro_id, nota) VALUES (?, ?, ?)",
            [(usuario_id, livro_id, nota) for livro_id, nota in avaliacoes],
        )
    return usuario_id


def atualizar_tags_favoritas(conexao, usuario_id, tags_favoritas):
    with conexao:
        conexao.execute(
            "UPDATE usuarios SET tags_favoritas = ? WHERE usuario_id = ?",
            (json.dumps(list(tags_favoritas), ensure_ascii=False), usuario_id),
        )


# ---------------------------------------------------------------------------
# Avaliações
# ---------------------------------------------------------------------------

def avaliacoes_do_usuario(conexao, usuario_id):
    """Todas as avaliações de um usuário, como dicionário {livro_id: nota}."""
    linhas = conexao.execute(
        "SELECT livro_id, nota FROM avaliacoes WHERE usuario_id = ?", (usuario_id,)
    ).fetchall()
    return {linha["livro_id"]: linha["nota"] for linha in linhas}


def salvar_avaliacao(conexao, usuario_id, livro_id, nota):
    """Cria a avaliação ou troca a nota, se ela já existir.

    Devolve "criada" ou "atualizada".
    """
    with conexao:
        existia = conexao.execute(
            "SELECT 1 FROM avaliacoes WHERE usuario_id = ? AND livro_id = ?",
            (usuario_id, livro_id),
        ).fetchone()
        # "UPSERT": insere; se já existir, atualiza a nota
        conexao.execute(
            """INSERT INTO avaliacoes (usuario_id, livro_id, nota) VALUES (?, ?, ?)
               ON CONFLICT (usuario_id, livro_id) DO UPDATE SET nota = excluded.nota""",
            (usuario_id, livro_id, nota),
        )
    return "atualizada" if existia else "criada"


def remover_avaliacao(conexao, usuario_id, livro_id):
    """Apaga uma avaliação. Devolve True se ela existia."""
    with conexao:
        cursor = conexao.execute(
            "DELETE FROM avaliacoes WHERE usuario_id = ? AND livro_id = ?",
            (usuario_id, livro_id),
        )
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Livros novos
# ---------------------------------------------------------------------------

def salvar_livro_novo(conexao, livro_id, titulo, autores, ano, tags):
    with conexao:
        conexao.execute(
            "INSERT INTO livros_novos (livro_id, titulo, autores, ano, tags) VALUES (?, ?, ?, ?, ?)",
            (livro_id, titulo, autores, ano, json.dumps(tags, ensure_ascii=False)),
        )


def listar_livros_novos(conexao):
    """Os livros cadastrados pela API, na ordem em que foram criados."""
    linhas = conexao.execute("SELECT * FROM livros_novos ORDER BY livro_id").fetchall()
    return [
        {
            "livro_id": linha["livro_id"],
            "titulo": linha["titulo"],
            "autores": linha["autores"],
            "ano": linha["ano"],
            "tags": json.loads(linha["tags"]),
        }
        for linha in linhas
    ]


# ---------------------------------------------------------------------------
# Estatísticas
# ---------------------------------------------------------------------------

def contar(conexao):
    """Quantos usuários, avaliações e livros novos existem no banco."""
    return {
        "usuarios": conexao.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0],
        "avaliacoes": conexao.execute("SELECT COUNT(*) FROM avaliacoes").fetchone()[0],
        "livros_novos": conexao.execute("SELECT COUNT(*) FROM livros_novos").fetchone()[0],
    }
"""
main.py

PASSO 5 do projeto: a API com FastAPI.

Como rodar (na pasta raiz do projeto, com o venv ativo):
    uvicorn app.main:app --reload

Depois abra no navegador:
    http://127.0.0.1:8000/docs    documentação interativa (Swagger UI)

Endpoints pedidos no trabalho:
    * Adicionar novos usuários ........ POST /usuarios
    * Adicionar novos itens ........... POST /livros
    * Obter recomendações ............. GET  /usuarios/{usuario_id}/recomendacoes
    * Atualizar preferências .......... PUT  /usuarios/{usuario_id}/avaliacoes/{livro_id}
                                        PUT  /usuarios/{usuario_id}/preferencias

Endpoints extras, para a API ser usável de verdade:
    * buscar livros pelo nome, ver detalhes, livros parecidos, populares,
      lista de tags, ver e apagar avaliações
"""

import os
import threading
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status

from app import banco
from app.modelo import PASTA_MODELO, PESO_CONTEUDO_PADRAO, Recomendador
from app.schemas import (
    AvaliacaoSaida,
    AvaliacaoSalvaSaida,
    LivroDetalhe,
    LivroEntrada,
    LivroParecido,
    LivroResumo,
    NotaEntrada,
    PreferenciasEntrada,
    RecomendacoesSaida,
    StatusSaida,
    UsuarioEntrada,
    UsuarioSaida,
)

# ---------------------------------------------------------------------------
# Inicialização
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Roda uma vez quando a API liga (antes do yield) e uma vez quando
    desliga (depois do yield).

    Carregar o modelo aqui, e não a cada pedido, é o que deixa as
    recomendações rápidas: o modelo fica pronto na memória.
    """
    if not os.path.exists(os.path.join(PASTA_MODELO, "vizinhos_cf.npz")):
        raise RuntimeError("Modelo não encontrado. Rode antes: python scripts/treinar_modelo.py")
    if not os.path.exists(banco.CAMINHO_BANCO):
        raise RuntimeError("Banco não encontrado. Rode antes: python scripts/criar_banco.py")

    modelo = Recomendador.carregar()

    # Os livros cadastrados pela API ficam no banco. Ao ligar, colocamos
    # todos de volta no modelo.
    conexao = banco.conectar()
    for livro in banco.listar_livros_novos(conexao):
        modelo.adicionar_livro(**livro)
    conexao.close()

    app.state.modelo = modelo
    # Trava usada ao cadastrar livros: impede que dois pedidos ao mesmo
    # tempo recebam o mesmo livro_id ou alterem o modelo juntos
    app.state.trava_livros = threading.Lock()
    yield


DESCRICAO = """
API de recomendação de livros com a base **Book Genome** (GroupLens):
9.374 livros, 350 mil usuários, 5,1 milhões de avaliações e 727 tags.

**Modelo híbrido**: média ponderada entre
* **conteúdo**: as 727 tags de cada livro (Tag Genome) comparadas com o gosto do usuário;
* **colaborativo**: "quem gostou deste livro também gostou daquele".

**Como testar aqui no Swagger:**
1. `GET /livros/busca` para achar o `livro_id` de livros que você conhece;
2. `POST /usuarios` para criar um usuário com algumas avaliações;
3. `GET /usuarios/{usuario_id}/recomendacoes` para ver as recomendações;
4. `PUT /usuarios/{usuario_id}/avaliacoes/{livro_id}` para avaliar mais livros e ver as recomendações mudarem.
"""

app = FastAPI(
    title="Sistema de Recomendação de Livros",
    description=DESCRICAO,
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=[
        {"name": "Geral", "description": "Situação da API"},
        {"name": "Usuários", "description": "Criar e consultar usuários"},
        {"name": "Avaliações e preferências", "description": "Atualizar o gosto do usuário"},
        {"name": "Recomendações", "description": "Recomendações personalizadas"},
        {"name": "Livros", "description": "Catálogo, busca e cadastro de livros"},
    ],
)


# ---------------------------------------------------------------------------
# Dependências
# ---------------------------------------------------------------------------
# O FastAPI chama estas funções sozinho, antes de cada endpoint que pede
# por elas com Depends(...). Assim cada endpoint recebe pronto o modelo e
# uma conexão com o banco, sem repetir código.


def obter_modelo(request: Request) -> Recomendador:
    return request.app.state.modelo


def obter_conexao():
    """Abre uma conexão para o pedido e fecha no final, mesmo se der erro."""
    conexao = banco.conectar()
    try:
        yield conexao
    finally:
        conexao.close()


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------


def usuario_ou_404(conexao, usuario_id):
    usuario = banco.buscar_usuario(conexao, usuario_id)
    if usuario is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Usuário {usuario_id} não encontrado.")
    return usuario


def checar_livro(modelo, livro_id):
    if not modelo.existe(livro_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Livro {livro_id} não encontrado.")


def checar_tags(modelo, tags):
    invalidas = modelo.tags_invalidas(tags)
    if invalidas:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Tags que não existem na base: {invalidas}. Veja a lista em GET /tags.",
        )


# ---------------------------------------------------------------------------
# Geral
# ---------------------------------------------------------------------------


@app.get("/", response_model=StatusSaida, tags=["Geral"], summary="Situação da API")
def status_api(modelo: Recomendador = Depends(obter_modelo), conexao=Depends(obter_conexao)):
    totais = banco.contar(conexao)
    return {
        "status": "ok",
        "livros": len(modelo.livros),
        "usuarios": totais["usuarios"],
        "avaliacoes": totais["avaliacoes"],
        "tags": len(modelo.tags),
    }


@app.get("/tags", response_model=list[str], tags=["Geral"], summary="Lista das 727 tags")
def listar_tags(modelo: Recomendador = Depends(obter_modelo)):
    """Nomes válidos para as tags favoritas dos usuários e para cadastrar livros."""
    return modelo.tags


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


@app.post(
    "/usuarios",
    response_model=UsuarioSaida,
    status_code=status.HTTP_201_CREATED,
    tags=["Usuários"],
    summary="Adicionar um usuário novo",
)
def criar_usuario(
    dados: UsuarioEntrada,
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    """Cria um usuário. As tags favoritas e as avaliações são opcionais.

    Sem nenhuma das duas, o usuário recebe os livros mais populares até
    avaliar algum livro ou escolher tags favoritas.
    """
    checar_tags(modelo, dados.tags_favoritas)
    for avaliacao in dados.avaliacoes:
        checar_livro(modelo, avaliacao.livro_id)

    usuario_id = banco.criar_usuario(
        conexao,
        dados.nome,
        tags_favoritas=dados.tags_favoritas,
        avaliacoes=[(a.livro_id, a.nota) for a in dados.avaliacoes],
    )
    return banco.buscar_usuario(conexao, usuario_id)


@app.get("/usuarios/{usuario_id}", response_model=UsuarioSaida, tags=["Usuários"], summary="Ver um usuário")
def ver_usuario(usuario_id: int, conexao=Depends(obter_conexao)):
    """Funciona para usuários da base (ids de 0 a 350331) e para os criados pela API."""
    return usuario_ou_404(conexao, usuario_id)


# ---------------------------------------------------------------------------
# Avaliações e preferências
# ---------------------------------------------------------------------------


@app.get(
    "/usuarios/{usuario_id}/avaliacoes",
    response_model=list[AvaliacaoSaida],
    tags=["Avaliações e preferências"],
    summary="Listar as avaliações de um usuário",
)
def listar_avaliacoes(
    usuario_id: int,
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    usuario_ou_404(conexao, usuario_id)
    avaliacoes = banco.avaliacoes_do_usuario(conexao, usuario_id)
    resultado = []
    # Da maior nota para a menor
    for livro_id, nota in sorted(avaliacoes.items(), key=lambda par: -par[1]):
        if modelo.existe(livro_id):
            info = modelo.info_livro(livro_id)
            resultado.append({"livro_id": livro_id, "titulo": info["titulo"],
                              "autores": info["autores"], "nota": nota})
    return resultado


@app.put(
    "/usuarios/{usuario_id}/avaliacoes/{livro_id}",
    response_model=AvaliacaoSalvaSaida,
    tags=["Avaliações e preferências"],
    summary="Avaliar um livro ou mudar a nota",
)
def salvar_avaliacao(
    usuario_id: int,
    livro_id: int,
    dados: NotaEntrada,
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    """Atualiza as preferências do usuário: se ele ainda não avaliou o
    livro, cria a avaliação; se já avaliou, troca a nota.

    A próxima recomendação já leva a nota nova em conta, sem retreinar nada.
    """
    usuario_ou_404(conexao, usuario_id)
    checar_livro(modelo, livro_id)
    situacao = banco.salvar_avaliacao(conexao, usuario_id, livro_id, dados.nota)
    return {"usuario_id": usuario_id, "livro_id": livro_id, "nota": dados.nota, "situacao": situacao}


@app.delete(
    "/usuarios/{usuario_id}/avaliacoes/{livro_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Avaliações e preferências"],
    summary="Apagar uma avaliação",
)
def apagar_avaliacao(usuario_id: int, livro_id: int, conexao=Depends(obter_conexao)):
    usuario_ou_404(conexao, usuario_id)
    if not banco.remover_avaliacao(conexao, usuario_id, livro_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"O usuário {usuario_id} não tem avaliação para o livro {livro_id}.",
        )


@app.put(
    "/usuarios/{usuario_id}/preferencias",
    response_model=UsuarioSaida,
    tags=["Avaliações e preferências"],
    summary="Atualizar as tags favoritas",
)
def atualizar_preferencias(
    usuario_id: int,
    dados: PreferenciasEntrada,
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    """Troca as tags favoritas do usuário (ex.: "fantasy", "space").

    Elas entram no perfil de gosto junto com as avaliações. Servem
    principalmente para quem ainda avaliou poucos livros.
    """
    usuario_ou_404(conexao, usuario_id)
    checar_tags(modelo, dados.tags_favoritas)
    # dict.fromkeys tira as repetidas mantendo a ordem
    banco.atualizar_tags_favoritas(conexao, usuario_id, list(dict.fromkeys(dados.tags_favoritas)))
    return banco.buscar_usuario(conexao, usuario_id)


# ---------------------------------------------------------------------------
# Recomendações
# ---------------------------------------------------------------------------


@app.get(
    "/usuarios/{usuario_id}/recomendacoes",
    response_model=RecomendacoesSaida,
    tags=["Recomendações"],
    summary="Recomendar livros para um usuário",
)
def recomendar(
    usuario_id: int,
    n: int = Query(10, ge=1, le=100, description="Quantos livros recomendar"),
    peso_conteudo: float = Query(
        PESO_CONTEUDO_PADRAO, ge=0, le=1,
        description="Peso do conteúdo (tags) na média. 0 = só colaborativo; 1 = só conteúdo.",
    ),
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    """Recomendações personalizadas, cada uma com o motivo.

    * Usa as avaliações e as tags favoritas do usuário.
    * Não recomenda livros que o usuário já avaliou.
    * Sem avaliações e sem tags favoritas, devolve os livros mais populares.
    """
    usuario = usuario_ou_404(conexao, usuario_id)
    avaliacoes = banco.avaliacoes_do_usuario(conexao, usuario_id)
    resultado = modelo.recomendar(
        avaliacoes, n=n, peso_conteudo=peso_conteudo, tags_favoritas=usuario["tags_favoritas"]
    )
    return {"usuario_id": usuario_id, "peso_conteudo": peso_conteudo, **resultado}


# ---------------------------------------------------------------------------
# Livros
# ---------------------------------------------------------------------------
# Atenção à ordem: /livros/busca e /livros/populares precisam vir antes de
# /livros/{livro_id}. Senão o FastAPI tentaria ler "busca" como um livro_id.


@app.get("/livros/busca", response_model=list[LivroResumo], tags=["Livros"], summary="Buscar livros")
def buscar_livros(
    texto: str = Query(min_length=2, description="Parte do título ou do autor, ex.: harry potter"),
    limite: int = Query(10, ge=1, le=50),
    modelo: Recomendador = Depends(obter_modelo),
):
    """Procura no título e no autor. Os livros mais avaliados aparecem primeiro."""
    return modelo.buscar(texto, limite)


@app.get("/livros/populares", response_model=list[LivroParecido], tags=["Livros"], summary="Livros mais populares")
def livros_populares(n: int = Query(10, ge=1, le=100), modelo: Recomendador = Depends(obter_modelo)):
    """Ranking pela média bayesiana: a nota média, ajustada pela quantidade de avaliações."""
    return modelo.populares(n)


@app.post(
    "/livros",
    response_model=LivroDetalhe,
    status_code=status.HTTP_201_CREATED,
    tags=["Livros"],
    summary="Adicionar um livro novo",
)
def criar_livro(
    dados: LivroEntrada,
    request: Request,
    modelo: Recomendador = Depends(obter_modelo),
    conexao=Depends(obter_conexao),
):
    """Cadastra um livro com as tags que o descrevem.

    O livro já pode ser recomendado na mesma hora, pelo conteúdo. Ele não
    tem avaliações ainda, então não participa do filtro colaborativo.
    """
    checar_tags(modelo, dados.tags)
    tags = {nome: min(max(nota, 0.0), 1.0) for nome, nota in dados.tags.items()}
    with request.app.state.trava_livros:
        livro_id = modelo.proximo_livro_id()
        banco.salvar_livro_novo(conexao, livro_id, dados.titulo, dados.autores, dados.ano, tags)
        modelo.adicionar_livro(livro_id, dados.titulo, dados.autores, dados.ano, tags)
    return modelo.detalhes_livro(livro_id)


@app.get("/livros/{livro_id}", response_model=LivroDetalhe, tags=["Livros"], summary="Ver um livro")
def ver_livro(livro_id: int, modelo: Recomendador = Depends(obter_modelo)):
    """Dados, descrição e as 10 tags que mais caracterizam o livro."""
    checar_livro(modelo, livro_id)
    return modelo.detalhes_livro(livro_id)


@app.get(
    "/livros/{livro_id}/parecidos",
    response_model=list[LivroParecido],
    tags=["Livros"],
    summary="Livros parecidos com um livro",
)
def livros_parecidos(
    livro_id: int,
    n: int = Query(10, ge=1, le=100),
    peso_conteudo: float = Query(PESO_CONTEUDO_PADRAO, ge=0, le=1),
    modelo: Recomendador = Depends(obter_modelo),
):
    checar_livro(modelo, livro_id)
    return modelo.livros_parecidos(livro_id, n=n, peso_conteudo=peso_conteudo)
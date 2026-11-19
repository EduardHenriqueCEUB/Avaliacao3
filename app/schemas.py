"""
schemas.py

PASSO 5 do projeto: os formatos de entrada e saída da API.

Cada classe aqui descreve um "formato" de dados em JSON, usando o Pydantic
(biblioteca que já vem com o FastAPI). Isso serve para três coisas:

    1 - Validar a entrada: se alguém mandar nota 7, o FastAPI recusa
        sozinho com erro 422, antes mesmo de chegar no nosso código.
    2 - Padronizar a saída: a resposta sempre tem os mesmos campos.
    3 - Documentar: o Swagger (/docs) mostra esses formatos e os exemplos.

Convenção dos nomes:
    ...Entrada  o que a API recebe
    ...Saida    o que a API devolve
"""

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Livros
# ---------------------------------------------------------------------------


class LivroResumo(BaseModel):
    livro_id: int
    titulo: str
    autores: str
    ano: int | None = Field(None, description="Vazio quando o ano é desconhecido")
    num_avaliacoes: int
    media_avaliacoes: float | None = Field(None, description="Vazio para livros sem avaliações")
    url: str | None = Field(None, description="Página do livro no Goodreads")
    capa: str | None = Field(None, description="Imagem da capa")


class TagNota(BaseModel):
    tag: str
    nota: float = Field(description="O quanto a tag descreve o livro, de 0 a 1")


class LivroDetalhe(LivroResumo):
    descricao: str
    tags: list[TagNota] = Field(description="As tags que mais caracterizam o livro")


class LivroParecido(LivroResumo):
    pontuacao: float = Field(description="Semelhança com o livro pedido, de 0 a 1")


class LivroEntrada(BaseModel):
    titulo: str = Field(min_length=1, max_length=300)
    autores: str = Field(min_length=1, max_length=300)
    ano: int | None = Field(None, ge=0, le=2100)
    tags: dict[str, float] = Field(
        min_length=1,
        description=(
            "Tags que descrevem o livro, com uma nota de 0 a 1 para cada. "
            "Os nomes válidos estão em GET /tags."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "titulo": "O Dragão de Brasília",
                "autores": "Eduardo Santos",
                "ano": 2026,
                "tags": {"dragons": 1.0, "magic": 0.9, "fantasy": 1.0, "adventure": 0.7},
            }]
        }
    }


# ---------------------------------------------------------------------------
# Avaliações e preferências
# ---------------------------------------------------------------------------


class AvaliacaoEntrada(BaseModel):
    livro_id: int
    nota: int = Field(ge=1, le=5, description="De 1 a 5 estrelas")


class NotaEntrada(BaseModel):
    nota: int = Field(ge=1, le=5, description="De 1 a 5 estrelas")

    model_config = {"json_schema_extra": {"examples": [{"nota": 5}]}}


class AvaliacaoSaida(BaseModel):
    livro_id: int
    titulo: str
    autores: str
    nota: int


class AvaliacaoSalvaSaida(BaseModel):
    usuario_id: int
    livro_id: int
    nota: int
    situacao: Literal["criada", "atualizada"]


class PreferenciasEntrada(BaseModel):
    tags_favoritas: list[str] = Field(
        max_length=20,
        description="Tags de que o usuário gosta (substituem as anteriores). Lista vazia apaga todas.",
    )

    model_config = {"json_schema_extra": {"examples": [{"tags_favoritas": ["science fiction", "space", "dystopia"]}]}}


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


class UsuarioEntrada(BaseModel):
    nome: str = Field(min_length=1, max_length=100)
    tags_favoritas: list[str] = Field(default_factory=list, max_length=20)
    avaliacoes: list[AvaliacaoEntrada] = Field(
        default_factory=list, description="Avaliações iniciais (opcional)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [{
                "nome": "Eduardo",
                "tags_favoritas": ["fantasy", "magic"],
                "avaliacoes": [
                    {"livro_id": 4640799, "nota": 5},
                    {"livro_id": 1540236, "nota": 4},
                ],
            }]
        }
    }


class UsuarioSaida(BaseModel):
    usuario_id: int
    nome: str | None = Field(None, description="Vazio para os usuários que vieram da base")
    origem: Literal["base", "api"] = Field(description="'base' = veio do Book Genome; 'api' = criado pela API")
    tags_favoritas: list[str]
    num_avaliacoes: int
    criado_em: str


# ---------------------------------------------------------------------------
# Recomendações
# ---------------------------------------------------------------------------


class LivroReferencia(BaseModel):
    livro_id: int
    titulo: str


class Motivo(BaseModel):
    tags_em_comum: list[str] = Field(description="Tags do livro que combinam com o gosto do usuário")
    parecido_com: LivroReferencia | None = Field(
        None, description="O livro avaliado pelo usuário que mais se parece com a recomendação"
    )


class Recomendacao(LivroResumo):
    pontuacao: float
    motivo: Motivo


class RecomendacoesSaida(BaseModel):
    usuario_id: int
    estrategia: Literal["personalizada", "populares"] = Field(
        description="'populares' quando o usuário ainda não tem avaliações nem tags favoritas"
    )
    peso_conteudo: float
    recomendacoes: list[Recomendacao]


# ---------------------------------------------------------------------------
# Geral
# ---------------------------------------------------------------------------


class StatusSaida(BaseModel):
    status: str
    livros: int
    usuarios: int
    avaliacoes: int
    tags: int
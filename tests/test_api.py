"""
Testes de integração da API (app/main.py).

Aqui as peças trabalham juntas: FastAPI + modelo + banco SQLite, com os
arquivos gerados pelos scripts a partir da base sintética. Os pedidos são
feitos pelo TestClient do FastAPI, que simula um navegador ou o Swagger.

Cada teste recebe uma cópia nova do banco, então a ordem dos testes não
importa e um teste não "suja" o outro.

Na base sintética:
    * usuários da base: ids 10 a 69 (60 usuários)
    * livros: 60, com ids 1000, 1007, 1014... (3 gêneros de 20)
"""

import pytest
from fastapi.testclient import TestClient

import dados_sinteticos as ds

FANTASIA = ds.ids_do_genero("fantasia")
FICCAO = ds.ids_do_genero("ficcao")
ROMANCE = ds.ids_do_genero("romance")
USUARIO_BASE = ds.PRIMEIRO_USUARIO_ID  # usuário 10, gosta de fantasia
PRIMEIRO_ID_API = ds.PRIMEIRO_USUARIO_ID + ds.NUM_USUARIOS
LIVRO = FANTASIA[3]


def criar_usuario(cliente, **dados):
    corpo = {"nome": "Teste", **dados}
    r = cliente.post("/usuarios", json=corpo)
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Geral e documentação
# ---------------------------------------------------------------------------


def test_status(cliente, pasta_dados):
    r = cliente.get("/")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ok",
        "livros": 60,
        "usuarios": ds.NUM_USUARIOS,
        "avaliacoes": pasta_dados["resumo_base"]["avaliacoes_validas"],
        "tags": len(ds.TAGS),
    }


def test_tags(cliente):
    r = cliente.get("/tags")
    assert r.status_code == 200
    assert r.json() == ds.TAGS


def test_swagger_e_openapi(cliente):
    assert cliente.get("/docs").status_code == 200
    esquema = cliente.get("/openapi.json").json()
    assert esquema["info"]["title"] == "Sistema de Recomendação de Livros"
    caminhos = esquema["paths"]
    # Os endpoints pedidos no enunciado do trabalho
    assert "post" in caminhos["/usuarios"]
    assert "post" in caminhos["/livros"]
    assert "get" in caminhos["/usuarios/{usuario_id}/recomendacoes"]
    assert "put" in caminhos["/usuarios/{usuario_id}/avaliacoes/{livro_id}"]
    assert "put" in caminhos["/usuarios/{usuario_id}/preferencias"]
    # E os extras
    for caminho in ["/", "/tags", "/usuarios/{usuario_id}", "/usuarios/{usuario_id}/avaliacoes",
                    "/livros/busca", "/livros/populares", "/livros/{livro_id}",
                    "/livros/{livro_id}/parecidos"]:
        assert caminho in caminhos


def test_endpoint_inexistente(cliente):
    assert cliente.get("/nao-existe").status_code == 404


# ---------------------------------------------------------------------------
# Usuários
# ---------------------------------------------------------------------------


def test_criar_usuario_completo(cliente):
    r = cliente.post("/usuarios", json={
        "nome": "Ana",
        "tags_favoritas": ["magic"],
        "avaliacoes": [{"livro_id": FANTASIA[0], "nota": 5}, {"livro_id": ROMANCE[0], "nota": 1}],
    })
    assert r.status_code == 201
    u = r.json()
    assert u["usuario_id"] == PRIMEIRO_ID_API  # continua depois dos ids da base
    assert u["nome"] == "Ana"
    assert u["origem"] == "api"
    assert u["tags_favoritas"] == ["magic"]
    assert u["num_avaliacoes"] == 2
    assert u["criado_em"]


def test_criar_usuario_so_com_nome(cliente):
    u = criar_usuario(cliente, nome="Bia")
    assert u["tags_favoritas"] == [] and u["num_avaliacoes"] == 0


def test_ids_de_usuarios_novos_em_sequencia(cliente):
    a = criar_usuario(cliente)["usuario_id"]
    b = criar_usuario(cliente)["usuario_id"]
    assert b == a + 1


def test_criar_usuario_com_tag_invalida(cliente):
    r = cliente.post("/usuarios", json={"nome": "Ana", "tags_favoritas": ["nao existe"]})
    assert r.status_code == 400
    assert "nao existe" in r.json()["detail"]
    assert cliente.get("/").json()["usuarios"] == ds.NUM_USUARIOS  # nada foi gravado


def test_criar_usuario_com_livro_inexistente(cliente):
    r = cliente.post("/usuarios", json={"nome": "Ana", "avaliacoes": [
        {"livro_id": FANTASIA[0], "nota": 5}, {"livro_id": ds.LIVRO_INEXISTENTE, "nota": 5}]})
    assert r.status_code == 404
    assert str(ds.LIVRO_INEXISTENTE) in r.json()["detail"]
    assert cliente.get("/").json()["usuarios"] == ds.NUM_USUARIOS


@pytest.mark.parametrize(
    "corpo",
    [
        {},                                                      # sem nome
        {"nome": ""},                                            # nome vazio
        {"nome": "Ana", "avaliacoes": [{"livro_id": 1000, "nota": 6}]},
        {"nome": "Ana", "avaliacoes": [{"livro_id": 1000}]},     # sem nota
        {"nome": "Ana", "tags_favoritas": "magic"},              # não é lista
        {"nome": "Ana", "tags_favoritas": ["magic"] * 21},
    ],
)
def test_criar_usuario_dados_invalidos(cliente, corpo):
    assert cliente.post("/usuarios", json=corpo).status_code == 422


def test_ver_usuario_criado(cliente):
    criado = criar_usuario(cliente, nome="Carla", tags_favoritas=["space"])
    r = cliente.get(f"/usuarios/{criado['usuario_id']}")
    assert r.status_code == 200
    assert r.json() == criado


def test_ver_usuario_da_base(cliente):
    r = cliente.get(f"/usuarios/{USUARIO_BASE}")
    assert r.status_code == 200
    u = r.json()
    assert u["origem"] == "base"
    assert u["nome"] is None
    assert u["num_avaliacoes"] > 0


def test_ver_usuario_inexistente(cliente):
    r = cliente.get("/usuarios/999999")
    assert r.status_code == 404
    assert "999999" in r.json()["detail"]


def test_usuario_id_invalido(cliente):
    assert cliente.get("/usuarios/abc").status_code == 422


# ---------------------------------------------------------------------------
# Avaliações e preferências
# ---------------------------------------------------------------------------


def test_listar_avaliacoes_da_maior_para_a_menor(cliente):
    uid = criar_usuario(cliente, avaliacoes=[
        {"livro_id": FANTASIA[0], "nota": 2}, {"livro_id": FANTASIA[1], "nota": 5},
        {"livro_id": FANTASIA[2], "nota": 4}])["usuario_id"]
    r = cliente.get(f"/usuarios/{uid}/avaliacoes")
    assert r.status_code == 200
    assert [a["nota"] for a in r.json()] == [5, 4, 2]
    primeira = r.json()[0]
    assert primeira["livro_id"] == FANTASIA[1]
    assert primeira["titulo"] == "Livro sujo"  # o título já vem limpo
    assert set(primeira) == {"livro_id", "titulo", "autores", "nota"}


def test_listar_avaliacoes_vazia_e_usuario_inexistente(cliente):
    uid = criar_usuario(cliente)["usuario_id"]
    assert cliente.get(f"/usuarios/{uid}/avaliacoes").json() == []
    assert cliente.get("/usuarios/999999/avaliacoes").status_code == 404


def test_avaliar_livro_e_mudar_a_nota(cliente):
    uid = criar_usuario(cliente)["usuario_id"]
    url = f"/usuarios/{uid}/avaliacoes/{LIVRO}"

    r = cliente.put(url, json={"nota": 4})
    assert r.status_code == 200
    assert r.json() == {"usuario_id": uid, "livro_id": LIVRO, "nota": 4, "situacao": "criada"}

    r = cliente.put(url, json={"nota": 2})
    assert r.json()["situacao"] == "atualizada"
    assert cliente.get(f"/usuarios/{uid}/avaliacoes").json()[0]["nota"] == 2
    assert cliente.get(f"/usuarios/{uid}").json()["num_avaliacoes"] == 1


def test_usuario_da_base_tambem_pode_avaliar(cliente):
    antes = cliente.get(f"/usuarios/{USUARIO_BASE}").json()["num_avaliacoes"]
    livro_novo_para_ele = next(
        l for l in ROMANCE
        if l not in {a["livro_id"] for a in cliente.get(f"/usuarios/{USUARIO_BASE}/avaliacoes").json()})
    r = cliente.put(f"/usuarios/{USUARIO_BASE}/avaliacoes/{livro_novo_para_ele}", json={"nota": 5})
    assert r.json()["situacao"] == "criada"
    assert cliente.get(f"/usuarios/{USUARIO_BASE}").json()["num_avaliacoes"] == antes + 1


def test_avaliar_erros(cliente):
    uid = criar_usuario(cliente)["usuario_id"]
    assert cliente.put(f"/usuarios/999999/avaliacoes/{LIVRO}", json={"nota": 5}).status_code == 404
    assert cliente.put(f"/usuarios/{uid}/avaliacoes/{ds.LIVRO_INEXISTENTE}", json={"nota": 5}).status_code == 404
    for nota in (0, 6, "x"):
        assert cliente.put(f"/usuarios/{uid}/avaliacoes/{LIVRO}", json={"nota": nota}).status_code == 422
    assert cliente.put(f"/usuarios/{uid}/avaliacoes/{LIVRO}", json={}).status_code == 422


def test_apagar_avaliacao(cliente):
    uid = criar_usuario(cliente, avaliacoes=[{"livro_id": LIVRO, "nota": 5}])["usuario_id"]
    r = cliente.delete(f"/usuarios/{uid}/avaliacoes/{LIVRO}")
    assert r.status_code == 204
    assert r.content == b""
    assert cliente.get(f"/usuarios/{uid}/avaliacoes").json() == []
    # Apagar de novo: já não existe
    assert cliente.delete(f"/usuarios/{uid}/avaliacoes/{LIVRO}").status_code == 404


def test_apagar_avaliacao_de_usuario_inexistente(cliente):
    assert cliente.delete(f"/usuarios/999999/avaliacoes/{LIVRO}").status_code == 404


def test_atualizar_preferencias(cliente):
    uid = criar_usuario(cliente, tags_favoritas=["magic"])["usuario_id"]
    r = cliente.put(f"/usuarios/{uid}/preferencias",
                    json={"tags_favoritas": ["space", "aliens", "space"]})
    assert r.status_code == 200
    assert r.json()["tags_favoritas"] == ["space", "aliens"]  # sem repetidas, na ordem
    assert cliente.get(f"/usuarios/{uid}").json()["tags_favoritas"] == ["space", "aliens"]

    r = cliente.put(f"/usuarios/{uid}/preferencias", json={"tags_favoritas": []})
    assert r.json()["tags_favoritas"] == []


def test_atualizar_preferencias_erros(cliente):
    uid = criar_usuario(cliente, tags_favoritas=["magic"])["usuario_id"]
    r = cliente.put(f"/usuarios/{uid}/preferencias", json={"tags_favoritas": ["magic", "inventada"]})
    assert r.status_code == 400
    assert cliente.get(f"/usuarios/{uid}").json()["tags_favoritas"] == ["magic"]  # não mudou
    assert cliente.put("/usuarios/999999/preferencias", json={"tags_favoritas": []}).status_code == 404
    assert cliente.put(f"/usuarios/{uid}/preferencias", json={}).status_code == 422


# ---------------------------------------------------------------------------
# Recomendações
# ---------------------------------------------------------------------------


def recomendar(cliente, uid, **params):
    r = cliente.get(f"/usuarios/{uid}/recomendacoes", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_usuario_novo_sem_nada_recebe_populares(cliente):
    uid = criar_usuario(cliente)["usuario_id"]
    r = recomendar(cliente, uid)
    assert r["estrategia"] == "populares"
    assert r["usuario_id"] == uid
    assert len(r["recomendacoes"]) == 10
    populares = cliente.get("/livros/populares").json()
    assert [x["livro_id"] for x in r["recomendacoes"]] == [x["livro_id"] for x in populares]


def test_recomendacao_personalizada(cliente):
    uid = criar_usuario(cliente, avaliacoes=[
        {"livro_id": l, "nota": 5} for l in FICCAO[:4]])["usuario_id"]
    r = recomendar(cliente, uid)
    assert r["estrategia"] == "personalizada"
    assert r["peso_conteudo"] == 0.5
    ids = [x["livro_id"] for x in r["recomendacoes"]]
    assert set(ids) <= set(FICCAO)
    assert not set(ids) & set(FICCAO[:4])  # não recomenda o que já avaliou

    item = r["recomendacoes"][0]
    assert set(item) == {"livro_id", "titulo", "autores", "ano", "num_avaliacoes",
                         "media_avaliacoes", "url", "capa", "pontuacao", "motivo"}
    assert set(item["motivo"]["tags_em_comum"]) <= set(ds.GENEROS["ficcao"])
    assert item["motivo"]["parecido_com"]["livro_id"] in FICCAO[:4]


def test_recomendacao_para_usuario_da_base(cliente):
    # O usuário 10 gosta de fantasia (veja dados_sinteticos.py)
    r = recomendar(cliente, USUARIO_BASE)
    assert r["estrategia"] == "personalizada"
    ids = {x["livro_id"] for x in r["recomendacoes"]}
    avaliados = {a["livro_id"] for a in cliente.get(f"/usuarios/{USUARIO_BASE}/avaliacoes").json()}
    assert not ids & avaliados
    assert len(ids & set(FANTASIA)) >= 8


def test_so_tags_favoritas_ja_personaliza(cliente):
    uid = criar_usuario(cliente, tags_favoritas=["love", "wedding"])["usuario_id"]
    r = recomendar(cliente, uid)
    assert r["estrategia"] == "personalizada"
    assert {x["livro_id"] for x in r["recomendacoes"]} <= set(ROMANCE)


def test_parametros_n_e_peso_conteudo(cliente):
    uid = criar_usuario(cliente, avaliacoes=[{"livro_id": LIVRO, "nota": 5}])["usuario_id"]
    assert len(recomendar(cliente, uid, n=3)["recomendacoes"]) == 3
    assert len(recomendar(cliente, uid, n=50)["recomendacoes"]) == 50
    so_cf = recomendar(cliente, uid, peso_conteudo=0)
    so_conteudo = recomendar(cliente, uid, peso_conteudo=1)
    assert so_cf["peso_conteudo"] == 0 and so_conteudo["peso_conteudo"] == 1
    assert [x["pontuacao"] for x in so_cf["recomendacoes"]] != [x["pontuacao"] for x in so_conteudo["recomendacoes"]]


@pytest.mark.xfail(strict=True, reason=(
    "Bug conhecido em app/modelo.py: pedindo mais livros do que existem sem avaliar, "
    "os já avaliados voltam na lista com pontuação -inf (JSON inválido: -Infinity)."))
def test_pedir_mais_do_que_existe_nao_traz_livros_ja_avaliados(cliente):
    uid = criar_usuario(cliente, avaliacoes=[{"livro_id": LIVRO, "nota": 5}])["usuario_id"]
    ids = [x["livro_id"] for x in recomendar(cliente, uid, n=100)["recomendacoes"]]
    assert LIVRO not in ids
    assert len(ids) == 59  # só existem 59 livros que ele não avaliou


@pytest.mark.parametrize("params", [{"n": 0}, {"n": 101}, {"peso_conteudo": -0.1},
                                    {"peso_conteudo": 1.1}, {"n": "dez"}])
def test_parametros_invalidos(cliente, params):
    r = cliente.get(f"/usuarios/{USUARIO_BASE}/recomendacoes", params=params)
    assert r.status_code == 422


def test_recomendacao_de_usuario_inexistente(cliente):
    assert cliente.get("/usuarios/999999/recomendacoes").status_code == 404


def test_recomendacoes_mudam_quando_o_gosto_muda(cliente):
    """Requisito do trabalho: atualizar as preferências muda as recomendações,
    na hora, sem retreinar o modelo."""
    uid = criar_usuario(cliente)["usuario_id"]
    assert recomendar(cliente, uid)["estrategia"] == "populares"

    # Escolheu tags de ficção: passa a receber ficção
    cliente.put(f"/usuarios/{uid}/preferencias", json={"tags_favoritas": ["space"]})
    r = recomendar(cliente, uid)
    assert r["estrategia"] == "personalizada"
    assert {x["livro_id"] for x in r["recomendacoes"]} <= set(FICCAO)

    # Tirou as tags e avaliou bem livros de romance: passa a receber romance
    cliente.put(f"/usuarios/{uid}/preferencias", json={"tags_favoritas": []})
    for livro in ROMANCE[:4]:
        cliente.put(f"/usuarios/{uid}/avaliacoes/{livro}", json={"nota": 5})
    ids = {x["livro_id"] for x in recomendar(cliente, uid)["recomendacoes"]}
    assert ids <= set(ROMANCE)
    assert not ids & set(ROMANCE[:4])

    # Um livro avaliado sai das recomendações
    primeiro = recomendar(cliente, uid)["recomendacoes"][0]["livro_id"]
    cliente.put(f"/usuarios/{uid}/avaliacoes/{primeiro}", json={"nota": 4})
    assert primeiro not in {x["livro_id"] for x in recomendar(cliente, uid)["recomendacoes"]}


# ---------------------------------------------------------------------------
# Livros
# ---------------------------------------------------------------------------


def test_buscar_livros(cliente):
    r = cliente.get("/livros/busca", params={"texto": "FICCAO", "limite": 50})
    assert r.status_code == 200
    assert {x["livro_id"] for x in r.json()} == set(FICCAO)
    assert len(cliente.get("/livros/busca", params={"texto": "livro", "limite": 3}).json()) == 3
    assert cliente.get("/livros/busca", params={"texto": "zzz nada"}).json() == []


@pytest.mark.parametrize("params", [{}, {"texto": "a"}, {"texto": "livro", "limite": 0},
                                    {"texto": "livro", "limite": 51}])
def test_buscar_livros_parametros_invalidos(cliente, params):
    assert cliente.get("/livros/busca", params=params).status_code == 422


def test_livros_populares(cliente):
    r = cliente.get("/livros/populares", params={"n": 5})
    assert r.status_code == 200
    livros = r.json()
    assert len(livros) == 5
    assert "motivo" not in livros[0]  # o formato de saída não tem motivo
    pontos = [x["pontuacao"] for x in livros]
    assert pontos == sorted(pontos, reverse=True)
    assert cliente.get("/livros/populares", params={"n": 0}).status_code == 422


def test_ver_livro(cliente):
    r = cliente.get(f"/livros/{FANTASIA[0]}")
    assert r.status_code == 200
    livro = r.json()
    assert livro["livro_id"] == FANTASIA[0]
    assert livro["ano"] is None  # o ano 0 virou desconhecido
    assert livro["descricao"] == "Uma história de fantasia."
    assert len(livro["tags"]) == 10
    assert {t["tag"] for t in livro["tags"][:3]} == set(ds.GENEROS["fantasia"])


def test_ver_livro_sem_avaliacoes(cliente):
    livro = cliente.get(f"/livros/{ds.livro_id(ds.POS_SEM_AVALIACOES)}").json()
    assert livro["num_avaliacoes"] == 0
    assert livro["media_avaliacoes"] is None


def test_ver_livro_inexistente(cliente):
    r = cliente.get(f"/livros/{ds.LIVRO_INEXISTENTE}")
    assert r.status_code == 404
    assert cliente.get("/livros/abc").status_code == 422


def test_livros_parecidos(cliente):
    r = cliente.get(f"/livros/{ROMANCE[2]}/parecidos", params={"n": 5})
    assert r.status_code == 200
    ids = [x["livro_id"] for x in r.json()]
    assert len(ids) == 5 and ROMANCE[2] not in ids
    assert set(ids) <= set(ROMANCE)
    assert cliente.get(f"/livros/{ds.LIVRO_INEXISTENTE}/parecidos").status_code == 404
    assert cliente.get(f"/livros/{LIVRO}/parecidos", params={"peso_conteudo": 2}).status_code == 422


LIVRO_NOVO = {
    "titulo": "O Dragão de Brasília",
    "autores": "Eduardo Santos",
    "ano": 2026,
    # Livro de fantasia típico: alto nas tags de fantasia, zero nas outras
    "tags": {"dragons": 1.0, "magic": 1.0, "fantasy": 1.0, "space": 0.0, "science fiction": 0.0,
             "aliens": 0.0, "love": 0.0, "romance": 0.0, "wedding": 0.0},
}


def test_criar_livro(cliente):
    r = cliente.post("/livros", json=LIVRO_NOVO)
    assert r.status_code == 201
    livro = r.json()
    assert livro["livro_id"] == ds.livro_id(59) + 1
    assert livro["titulo"] == LIVRO_NOVO["titulo"]
    assert livro["num_avaliacoes"] == 0 and livro["media_avaliacoes"] is None
    assert livro["descricao"] == ""
    assert {t["tag"] for t in livro["tags"][:3]} == {"dragons", "magic", "fantasy"}

    # Já pode ser consultado, buscado e avaliado
    assert cliente.get(f"/livros/{livro['livro_id']}").status_code == 200
    assert cliente.get("/livros/busca", params={"texto": "dragão"}).json()[0]["livro_id"] == livro["livro_id"]
    assert cliente.get("/").json()["livros"] == 61
    uid = criar_usuario(cliente)["usuario_id"]
    assert cliente.put(f"/usuarios/{uid}/avaliacoes/{livro['livro_id']}", json={"nota": 5}).status_code == 200


def test_livro_novo_e_recomendado_na_hora(cliente):
    novo = cliente.post("/livros", json=LIVRO_NOVO).json()["livro_id"]
    uid = criar_usuario(cliente, avaliacoes=[{"livro_id": l, "nota": 5} for l in FANTASIA[:5]])["usuario_id"]
    ids = [x["livro_id"] for x in recomendar(cliente, uid, peso_conteudo=1, n=5)["recomendacoes"]]
    assert novo in ids


def test_livros_novos_recebem_ids_em_sequencia(cliente):
    a = cliente.post("/livros", json=LIVRO_NOVO).json()["livro_id"]
    b = cliente.post("/livros", json={**LIVRO_NOVO, "titulo": "Outro"}).json()["livro_id"]
    assert b == a + 1


def test_criar_livro_com_tag_invalida(cliente):
    r = cliente.post("/livros", json={**LIVRO_NOVO, "tags": {"magic": 1.0, "inventada": 1.0}})
    assert r.status_code == 400
    assert cliente.get("/").json()["livros"] == 60


def test_criar_livro_nota_de_tag_e_limitada_entre_0_e_1(cliente):
    r = cliente.post("/livros", json={**LIVRO_NOVO, "tags": {"magic": 7.0, "space": -3.0}})
    assert r.status_code == 201
    notas = {t["tag"]: t["nota"] for t in r.json()["tags"]}
    assert notas["magic"] == 1.0


@pytest.mark.parametrize("mudanca", [{"titulo": ""}, {"autores": ""}, {"tags": {}},
                                     {"ano": 3000}, {"tags": None}])
def test_criar_livro_dados_invalidos(cliente, mudanca):
    assert cliente.post("/livros", json={**LIVRO_NOVO, **mudanca}).status_code == 422


# ---------------------------------------------------------------------------
# Persistência: o que foi gravado continua depois de reiniciar a API
# ---------------------------------------------------------------------------


def test_dados_continuam_depois_de_reiniciar(configurar_api):
    with TestClient(configurar_api) as c:
        uid = criar_usuario(c, nome="Persistente", tags_favoritas=["magic"],
                            avaliacoes=[{"livro_id": LIVRO, "nota": 5}])["usuario_id"]
        livro = c.post("/livros", json=LIVRO_NOVO).json()["livro_id"]

    # Desligou e ligou de novo (como docker compose down / up)
    with TestClient(configurar_api) as c:
        u = c.get(f"/usuarios/{uid}").json()
        assert u["nome"] == "Persistente" and u["tags_favoritas"] == ["magic"]
        assert c.get(f"/usuarios/{uid}/avaliacoes").json()[0]["livro_id"] == LIVRO
        # O livro cadastrado volta para o modelo quando a API liga
        assert c.get(f"/livros/{livro}").json()["titulo"] == LIVRO_NOVO["titulo"]
        assert c.post("/livros", json=LIVRO_NOVO).json()["livro_id"] == livro + 1


# ---------------------------------------------------------------------------
# Inicialização: a API se recusa a ligar sem o modelo ou sem o banco
# ---------------------------------------------------------------------------


def test_api_nao_liga_sem_modelo(configurar_api, tmp_path, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "PASTA_MODELO", str(tmp_path / "vazia"))
    with pytest.raises(RuntimeError, match="Modelo não encontrado"):
        with TestClient(configurar_api):
            pass


def test_api_nao_liga_sem_banco(configurar_api, tmp_path, monkeypatch):
    from app import banco
    monkeypatch.setattr(banco, "CAMINHO_BANCO", str(tmp_path / "nao_existe.db"))
    with pytest.raises(RuntimeError, match="Banco não encontrado"):
        with TestClient(configurar_api):
            pass


# ---------------------------------------------------------------------------
# Roteiro do README (seção "Roteiro de teste no Swagger"), de ponta a ponta
# ---------------------------------------------------------------------------


def test_roteiro_do_readme(cliente):
    # 1 - Procura um livro pelo título e anota o livro_id
    achados = cliente.get("/livros/busca", params={"texto": "livro de fantasia"}).json()
    ids = [x["livro_id"] for x in achados[:3]]

    # 2 - Cria um usuário com algumas avaliações
    uid = criar_usuario(cliente, nome="Eduardo",
                        avaliacoes=[{"livro_id": l, "nota": 5} for l in ids])["usuario_id"]

    # 3 - Vê os livros recomendados e o motivo de cada um
    r = recomendar(cliente, uid)
    assert r["estrategia"] == "personalizada"
    assert all(x["motivo"]["tags_em_comum"] for x in r["recomendacoes"])

    # 4 - O usuário continua lá
    assert cliente.get(f"/usuarios/{uid}").json()["num_avaliacoes"] == 3

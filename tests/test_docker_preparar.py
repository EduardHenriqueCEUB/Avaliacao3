"""
Testes do docker/preparar.py (o serviço "preparar" do docker-compose).

Ele roda os passos de preparação em ordem e pula o que já foi feito. Aqui os
scripts de verdade são trocados por uma versão falsa, que só cria os
arquivos que o script real criaria. Assim dá para testar a ORDEM e as
DECISÕES (rodar ou pular) em milissegundos.
"""

import os

import pytest

from conftest import carregar_docker_preparar

preparar = carregar_docker_preparar()

# O que cada script cria (pasta, arquivos)
CRIA = {
    "scripts/baixar_dados.py": ("raw", preparar.ARQUIVOS_RAW),
    "scripts/preparar_dados.py": ("processed", preparar.ARQUIVOS_PROCESSED),
    "scripts/treinar_modelo.py": ("modelo", preparar.ARQUIVOS_MODELO),
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    dados = tmp_path / "data"
    pastas = {"raw": dados / "raw", "processed": dados / "processed", "modelo": dados / "modelo"}
    monkeypatch.setattr(preparar, "PASTA_DADOS", str(dados))
    monkeypatch.setattr(preparar, "PASTA_RAW", str(pastas["raw"]))
    monkeypatch.setattr(preparar, "PASTA_PROCESSED", str(pastas["processed"]))
    monkeypatch.setattr(preparar, "PASTA_MODELO", str(pastas["modelo"]))
    monkeypatch.setattr(preparar, "CAMINHO_BANCO", str(dados / "banco.db"))

    chamadas = []
    falhas = set()
    ambientes = {}

    def rodar_falso(script, env=None):
        chamadas.append(script)
        ambientes[script] = env
        if script in falhas:
            return False
        if script == "scripts/criar_banco.py":
            open(env["BANCO_PATH"], "w").close()
        else:
            pasta, arquivos = CRIA[script]
            os.makedirs(pastas[pasta], exist_ok=True)
            for nome in arquivos:
                open(os.path.join(pastas[pasta], nome), "w").close()
        return True

    monkeypatch.setattr(preparar, "rodar", rodar_falso)

    def criar(pasta, arquivos):
        os.makedirs(pastas[pasta], exist_ok=True)
        for nome in arquivos:
            open(os.path.join(pastas[pasta], nome), "w").close()

    return {"dados": dados, "chamadas": chamadas, "falhas": falhas, "criar": criar,
            "ambientes": ambientes}


def test_maquina_zerada_roda_tudo_na_ordem(ambiente):
    preparar.main()
    assert ambiente["chamadas"] == [
        "scripts/baixar_dados.py",
        "scripts/preparar_dados.py",
        "scripts/treinar_modelo.py",
        "scripts/criar_banco.py",
    ]
    assert preparar.banco_pronto()
    assert not os.path.exists(preparar.CAMINHO_BANCO + ".parcial")


def test_segunda_execucao_pula_tudo(ambiente):
    preparar.main()
    ambiente["chamadas"].clear()
    preparar.main()
    assert ambiente["chamadas"] == []


def test_com_dados_tratados_nao_precisa_baixar(ambiente):
    # Os dados originais não fazem falta se os tratados já existem
    ambiente["criar"]("processed", preparar.ARQUIVOS_PROCESSED)
    preparar.main()
    assert ambiente["chamadas"] == ["scripts/treinar_modelo.py", "scripts/criar_banco.py"]


def test_etapa_incompleta_e_refeita(ambiente):
    # Sem o resumo.json (o último arquivo gravado), o tratamento é considerado incompleto
    ambiente["criar"]("raw", preparar.ARQUIVOS_RAW)
    ambiente["criar"]("processed", ["livros.csv", "avaliacoes.csv"])
    preparar.main()
    assert ambiente["chamadas"][0] == "scripts/preparar_dados.py"


def test_banco_e_criado_com_nome_provisorio(ambiente):
    preparar.main()
    # O criar_banco.py grava num arquivo ".parcial", que só no fim vira
    # banco.db. Assim, se ele for interrompido, não fica um banco pela metade
    # com cara de banco pronto.
    env = ambiente["ambientes"]["scripts/criar_banco.py"]
    assert env == {"BANCO_PATH": preparar.CAMINHO_BANCO + ".parcial"}
    assert os.path.exists(preparar.CAMINHO_BANCO)


def test_sobra_de_execucao_interrompida_e_apagada(ambiente):
    os.makedirs(ambiente["dados"], exist_ok=True)
    with open(preparar.CAMINHO_BANCO + ".parcial", "w") as f:
        f.write("banco pela metade")
    preparar.main()
    assert os.path.getsize(preparar.CAMINHO_BANCO) == 0  # é o banco novo, não a sobra


@pytest.mark.parametrize(
    "script",
    ["scripts/baixar_dados.py", "scripts/preparar_dados.py",
     "scripts/treinar_modelo.py", "scripts/criar_banco.py"],
)
def test_falha_em_qualquer_etapa_para_com_erro(ambiente, script, capsys):
    ambiente["falhas"].add(script)
    with pytest.raises(SystemExit) as erro:
        preparar.main()
    assert erro.value.code == 1
    assert ambiente["chamadas"][-1] == script  # não segue para a próxima etapa
    assert "ERRO" in capsys.readouterr().err
    assert not preparar.banco_pronto()
    assert not os.path.exists(preparar.CAMINHO_BANCO + ".parcial")


def test_script_que_termina_sem_criar_os_arquivos_e_falha(ambiente, monkeypatch):
    monkeypatch.setattr(preparar, "rodar", lambda script, env=None: True)  # "deu certo", mas não criou nada
    with pytest.raises(SystemExit):
        preparar.main()


def test_rodar_de_verdade(tmp_path, monkeypatch):
    # O rodar() real (sem a troca da fixture): executa um script Python e
    # devolve True só se ele terminou sem erro
    (tmp_path / "ok.py").write_text(
        "import os, sys\nsys.exit(0 if os.environ.get('TESTE') == 'sim' else 3)\n")
    (tmp_path / "erro.py").write_text("raise SystemExit(1)\n")
    modulo = carregar_docker_preparar()
    monkeypatch.setattr(modulo, "PASTA_PROJETO", str(tmp_path))

    assert modulo.rodar("ok.py", env={"TESTE": "sim"}) is True
    assert modulo.rodar("ok.py") is False
    assert modulo.rodar("erro.py") is False

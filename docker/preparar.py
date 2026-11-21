"""
preparar.py  (Docker)

Prepara tudo o que a API precisa ANTES de ela ligar. É o que o serviço
"preparar" do docker-compose.yml executa.

A API (app/main.py) se recusa a ligar se o modelo ou o banco não existirem.
Por isso, num computador "zerado", alguém precisa rodar os passos 1 a 4 do
README antes. Aqui eles rodam automaticamente, nesta ordem:

    1 - scripts/baixar_dados.py     baixa a base do GroupLens  (~1,4 GB)
    2 - scripts/preparar_dados.py   trata os dados             (~20 s)
    3 - scripts/treinar_modelo.py   treina o colaborativo      (~10 s)
    4 - scripts/criar_banco.py      cria o banco SQLite        (~10 s)

Pode rodar quantas vezes quiser: cada etapa que já foi feita é pulada. Os
resultados ficam na pasta data/, que no Docker é um volume. Por isso, o
download e o treino só acontecem na primeira vez, e os usuários criados pela
API continuam existindo depois de desligar e ligar de novo.

Cuidados que este script toma:
    * Alguns scripts do projeto imprimem "ERRO" mas terminam "com sucesso"
      (código 0). Por isso, depois de cada etapa conferimos se os arquivos
      esperados realmente apareceram.
    * O criar_banco.py desliga a proteção do SQLite para gravar mais rápido.
      Se o container fosse interrompido no meio, sobraria um banco pela
      metade que pareceria pronto. Por isso o banco é criado com outro nome
      (banco.db.parcial) e só é renomeado quando termina inteiro.
"""

import os
import subprocess
import sys

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(PASTA_PROJETO, "data")
PASTA_RAW = os.path.join(PASTA_DADOS, "raw")
PASTA_PROCESSED = os.path.join(PASTA_DADOS, "processed")
PASTA_MODELO = os.path.join(PASTA_DADOS, "modelo")

# Mesma regra do app/banco.py: o caminho do banco pode vir de BANCO_PATH
CAMINHO_BANCO = os.environ.get("BANCO_PATH", os.path.join(PASTA_DADOS, "banco.db"))

ARQUIVOS_RAW = ["metadata.json", "ratings.json", "tags.json", "glmer.csv"]
# O resumo.json é o último que o preparar_dados.py grava: se ele existe, o resto também
ARQUIVOS_PROCESSED = ["livros.csv", "avaliacoes.csv", "tags.csv", "genome.npy", "resumo.json"]
# O info_treino.json é gravado depois do .npz, então indica que o .npz está completo
ARQUIVOS_MODELO = ["vizinhos_cf.npz", "info_treino.json"]


def existem(pasta, nomes):
    return all(os.path.exists(os.path.join(pasta, nome)) for nome in nomes)


def raw_pronto():
    return existem(PASTA_RAW, ARQUIVOS_RAW)


def processed_pronto():
    return existem(PASTA_PROCESSED, ARQUIVOS_PROCESSED)


def modelo_pronto():
    return existem(PASTA_MODELO, ARQUIVOS_MODELO)


def banco_pronto():
    return os.path.exists(CAMINHO_BANCO)


def rodar(script, env=None):
    """Roda um script do projeto e devolve True se terminou sem erro."""
    ambiente = dict(os.environ, PYTHONUNBUFFERED="1", **(env or {}))
    resultado = subprocess.run(
        [sys.executable, os.path.join(PASTA_PROJETO, script)],
        cwd=PASTA_PROJETO,
        env=ambiente,
    )
    return resultado.returncode == 0


def falhar(mensagem):
    print(f"\nERRO: {mensagem}", file=sys.stderr)
    sys.exit(1)


def etapa(numero, titulo):
    print(f"\n{'=' * 70}\n[{numero}/4] {titulo}\n{'=' * 70}", flush=True)


def main():
    os.makedirs(PASTA_DADOS, exist_ok=True)

    # 1 - Baixar. Só é preciso se faltam os arquivos originais E os já tratados
    # (se os tratados existem, os originais não fazem mais falta).
    etapa(1, "Base de dados (GroupLens)")
    if processed_pronto() or raw_pronto():
        print("Já disponível em data/. Pulando o download.")
    else:
        if not rodar("scripts/baixar_dados.py") or not raw_pronto():
            falhar(
                "não foi possível baixar a base. Verifique a internet ou use o plano B "
                "do DOCKER.md (colocar o book-genome.zip na pasta data/)."
            )

    # 2 - Tratar os dados
    etapa(2, "Tratamento dos dados")
    if processed_pronto():
        print("Dados tratados já existem em data/processed/. Pulando.")
    else:
        if not rodar("scripts/preparar_dados.py") or not processed_pronto():
            falhar("o tratamento dos dados não terminou. Veja as mensagens acima.")

    # 3 - Treinar o modelo
    etapa(3, "Treino do modelo (filtro colaborativo)")
    if modelo_pronto():
        print("Modelo já treinado em data/modelo/. Pulando.")
    else:
        if not rodar("scripts/treinar_modelo.py") or not modelo_pronto():
            falhar("o treino do modelo não terminou. Veja as mensagens acima.")

    # 4 - Criar o banco (com nome provisório, veja a explicação no topo do arquivo)
    etapa(4, "Banco de dados da API (SQLite)")
    if banco_pronto():
        print(f"Banco já existe em {CAMINHO_BANCO}. Pulando.")
    else:
        parcial = CAMINHO_BANCO + ".parcial"
        if os.path.exists(parcial):
            os.remove(parcial)  # sobra de uma execução interrompida
        ok = rodar("scripts/criar_banco.py", env={"BANCO_PATH": parcial})
        if not ok or not os.path.exists(parcial):
            if os.path.exists(parcial):
                os.remove(parcial)
            falhar("a criação do banco não terminou. Veja as mensagens acima.")
        os.replace(parcial, CAMINHO_BANCO)
        print(f"Banco pronto em {CAMINHO_BANCO}.")

    print("\nTudo pronto: a API já pode ligar.")


if __name__ == "__main__":
    main()

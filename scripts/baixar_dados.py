"""
baixar_dados.py

PASSO 1 do projeto: baixar a base Book Genome direto do site da GroupLens
e extrair SOMENTE os arquivos que o sistema de recomendação usa.

Por que este script existe:
    O zip oficial tem cerca de 1,4 GB e não pode ir para o GitHub.
    Em vez de guardar a base em algum lugar (Drive etc.), cada pessoa do
    grupo roda este script uma vez e a base aparece na pasta data/.
    A pasta data/ fica no .gitignore, então nunca sobe para o repositório.

Como rodar (a partir da pasta raiz do projeto):
    python scripts/baixar_dados.py

Se você JÁ baixou o book-genome.zip pelo navegador, coloque o arquivo
dentro da pasta data/ antes de rodar. O script percebe e pula o download.

Funciona em qualquer computador:
    O download e a extração são feitos em pedaços de 1 MB, então o script
    usa pouquíssima memória RAM, mesmo com um zip de 1,4 GB. Ele também
    confere o espaço em disco antes de começar e, se o download falhar,
    explica como baixar pelo navegador. Só usa bibliotecas que já vêm com
    o Python (nada para instalar).
"""

import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

# Endereço oficial do zip (página: https://grouplens.org/datasets/book-genome/).
# A variável de ambiente BOOK_GENOME_URL permite trocar o endereço sem mexer
# no código (útil para testes ou se o site mudar o link).
URL_ZIP = os.environ.get(
    "BOOK_GENOME_URL",
    "https://files.grouplens.org/datasets/book-genome/book-genome.zip",
)

# Pasta raiz do projeto = uma pasta acima de scripts/.
# Assim o script funciona não importa de onde ele seja chamado.
PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASTA_DADOS = os.path.join(PASTA_PROJETO, "data")
PASTA_RAW = os.path.join(PASTA_DADOS, "raw")
CAMINHO_ZIP = os.path.join(PASTA_DADOS, "book-genome.zip")

# Arquivos que vamos tirar de dentro do zip.
# Ficaram de fora de propósito:
#   reviews.json      -> 5,3 milhões de resenhas em texto (o maior arquivo, não usamos)
#   tagdl.csv         -> outra versão das notas de tags, a glmer.csv já basta
#   survey_answers.json, tag_count.json, processed/, predictions/ -> dados de pesquisa
#                        usados para CRIAR o Tag Genome, não precisamos deles
ARQUIVOS_NECESSARIOS = [
    "raw/metadata.json",   # informações dos livros: título, autores, ano, descrição...
    "raw/ratings.json",    # avaliações de 1 a 5 estrelas (usuário, livro, nota)
    "raw/tags.json",       # nome de cada uma das 727 tags
    "scores/glmer.csv",    # Tag Genome: o quanto cada tag descreve cada livro (0 a 1)
]

# Espaço livre mínimo no disco antes de começar (em GB).
# Baixando: o zip (1,4 GB) e os arquivos extraídos (0,6 GB) ficam no disco
# ao mesmo tempo por alguns minutos, por isso pedimos 2,5 GB com folga.
# Com o zip já na pasta: só precisamos de espaço para os arquivos extraídos.
ESPACO_MINIMO_DOWNLOAD_GB = 2.5
ESPACO_MINIMO_EXTRACAO_GB = 1.0

# Se True, apaga o zip depois de extrair (libera ~1,4 GB do seu disco).
# Se a extração der erro, o zip NÃO é apagado, para você não baixar de novo.
APAGAR_ZIP_DEPOIS = True


# ---------------------------------------------------------------------------
# Funções
# ---------------------------------------------------------------------------

def arquivos_ja_extraidos():
    """Retorna True se todos os arquivos necessários já estão em data/raw/."""
    for nome in ARQUIVOS_NECESSARIOS:
        destino = os.path.join(PASTA_RAW, os.path.basename(nome))
        if not os.path.exists(destino):
            return False
    return True


def checar_espaco_em_disco(minimo_gb):
    """Para o script com uma mensagem clara se o disco não tiver espaço suficiente.

    Sem essa checagem, o download poderia ir até a metade e falhar com um
    erro confuso do Windows. Assim quem rodar (colegas, professor) sabe na
    hora o que fazer.
    """
    livre_gb = shutil.disk_usage(PASTA_DADOS).free / (1024 ** 3)
    if livre_gb < minimo_gb:
        print(
            f"ERRO: espaço livre insuficiente no disco ({livre_gb:.1f} GB). "
            f"São necessários pelo menos {minimo_gb:.1f} GB. "
            "Libere espaço e rode o script de novo."
        )
        sys.exit(1)


def baixar_zip():
    """Baixa o zip em pedaços, mostrando o progresso na tela."""
    print(f"Baixando a base de: {URL_ZIP}")
    print("O arquivo tem cerca de 1,4 GB. Isso pode demorar alguns minutos.\n")

    # Baixamos primeiro para um arquivo ".parcial". Só renomeamos para o nome
    # final quando o download termina inteiro. Assim, se a internet cair no
    # meio, não fica um zip quebrado com cara de zip bom.
    caminho_parcial = CAMINHO_ZIP + ".parcial"

    with urllib.request.urlopen(URL_ZIP) as resposta:
        tamanho_total = int(resposta.headers.get("Content-Length", 0))
        baixado = 0
        inicio = time.time()

        with open(caminho_parcial, "wb") as arquivo:
            while True:
                pedaco = resposta.read(1024 * 1024)  # lê 1 MB por vez
                if not pedaco:
                    break
                arquivo.write(pedaco)
                baixado += len(pedaco)

                # Mostra o progresso na mesma linha (o "\r" volta para o início da linha)
                mb_baixados = baixado / (1024 * 1024)
                velocidade = mb_baixados / max(time.time() - inicio, 0.001)
                if tamanho_total:
                    porcentagem = baixado / tamanho_total * 100
                    mb_total = tamanho_total / (1024 * 1024)
                    print(
                        f"\r  {mb_baixados:,.0f} de {mb_total:,.0f} MB "
                        f"({porcentagem:5.1f}%)  {velocidade:,.1f} MB/s",
                        end="",
                    )
                else:
                    print(f"\r  {mb_baixados:,.0f} MB baixados", end="")

    print("\nDownload concluído.")
    os.replace(caminho_parcial, CAMINHO_ZIP)


def extrair_arquivos():
    """Abre o zip e copia para data/raw/ só os arquivos da lista."""
    print("\nExtraindo os arquivos necessários...")

    with zipfile.ZipFile(CAMINHO_ZIP) as zip_aberto:
        nomes_no_zip = zip_aberto.namelist()

        for nome_procurado in ARQUIVOS_NECESSARIOS:
            # Dentro do zip os arquivos podem estar dentro de uma pasta extra
            # (ex.: "book-genome/raw/ratings.json"). Por isso procuramos
            # qualquer nome que TERMINE com o caminho que queremos.
            encontrados = [n for n in nomes_no_zip if n.endswith(nome_procurado)]
            if not encontrados:
                raise FileNotFoundError(
                    f"Não encontrei '{nome_procurado}' dentro do zip. "
                    "O conteúdo da base pode ter mudado no site."
                )

            nome_no_zip = encontrados[0]
            destino = os.path.join(PASTA_RAW, os.path.basename(nome_procurado))

            # Copia em pedaços (copyfileobj) em vez de ler tudo de uma vez,
            # porque alguns arquivos têm centenas de MB e poderiam lotar a memória.
            with zip_aberto.open(nome_no_zip) as origem, open(destino, "wb") as saida:
                shutil.copyfileobj(origem, saida, length=1024 * 1024)

            tamanho_mb = os.path.getsize(destino) / (1024 * 1024)
            print(f"  ok  {nome_procurado}  ({tamanho_mb:,.1f} MB)")


def main():
    os.makedirs(PASTA_RAW, exist_ok=True)

    # 1 - Se os arquivos já estão lá, não faz nada (pode rodar quantas vezes quiser)
    if arquivos_ja_extraidos():
        print("Os arquivos da base já estão em data/raw/. Nada a fazer.")
        return

    # 2 - Baixa o zip, a não ser que ele já esteja na pasta data/
    if os.path.exists(CAMINHO_ZIP):
        print("Encontrei o book-genome.zip na pasta data/. Pulando o download.")
        checar_espaco_em_disco(ESPACO_MINIMO_EXTRACAO_GB)
    else:
        checar_espaco_em_disco(ESPACO_MINIMO_DOWNLOAD_GB)
        try:
            baixar_zip()
        except (urllib.error.URLError, OSError) as erro:
            # Qualquer falha de rede cai aqui: internet fora do ar, site fora
            # do ar ou erro de certificado SSL (comum no Python do macOS).
            # Apagamos o arquivo pela metade e explicamos o plano B.
            caminho_parcial = CAMINHO_ZIP + ".parcial"
            if os.path.exists(caminho_parcial):
                os.remove(caminho_parcial)
            print(f"\n\nERRO no download: {erro}")
            print(
                "\nPlano B: baixe o zip pelo navegador neste link:\n"
                f"  {URL_ZIP}\n"
                "Coloque o arquivo book-genome.zip dentro da pasta data/ "
                "e rode este script de novo. Ele vai pular o download."
            )
            sys.exit(1)

    # 3 - Extrai só o que interessa
    try:
        extrair_arquivos()
    except zipfile.BadZipFile:
        print(
            "\nERRO: o zip está corrompido (download incompleto?). "
            "Apague data/book-genome.zip e rode o script de novo."
        )
        sys.exit(1)

    # 4 - Libera espaço em disco
    if APAGAR_ZIP_DEPOIS:
        os.remove(CAMINHO_ZIP)
        print("\nZip apagado para liberar espaço em disco.")

    print("\nPronto! Base disponível em data/raw/.")


if __name__ == "__main__":
    main()
# Containerização com Docker

Parte 4 do trabalho (Containerização com Docker). Com o Docker, o projeto roda com **um único comando**,
sem instalar Python, criar o ambiente virtual nem rodar os scripts um por um.

#####

## O que é preciso ter

* **Docker Desktop** instalado e aberto (Windows, macOS) ou Docker Engine com o plugin Compose (Linux).
  Para conferir, rode `docker compose version` no terminal.
* **Memória:** o passo mais pesado (tratamento dos dados) usa cerca de 1 GB. O Docker Desktop no Windows
  costuma usar metade da RAM do computador, o que já basta. Se aparecer `exited with code 137`, o Docker ficou
  sem memória: aumente o limite em *Settings → Resources*.
* **Disco:** cerca de 3 GB livres durante o download (depois ficam uns 800 MB no volume, fora a imagem).
* **Internet**, só na primeira vez, para baixar a base (1,4 GB).
* Não precisa instalar Python nem as bibliotecas: elas já vêm dentro da imagem (Python 3.14, as mesmas versões do
  `requirements.txt`).

#####

## Como executar

Na pasta raiz do projeto:

```
docker compose up --build
```

Na **primeira vez** isso leva alguns minutos (principalmente o download da base). O terminal mostra cada etapa:

```
[1/4] Base de dados (GroupLens)
[2/4] Tratamento dos dados
[3/4] Treino do modelo (filtro colaborativo)
[4/4] Banco de dados da API (SQLite)
Tudo pronto: a API já pode ligar.
```

Depois disso a API liga. Deu certo quando aparecer `Application startup complete.`

Abra a documentação interativa (Swagger UI) no navegador:

```
http://localhost:8000/docs
```

Para desligar, aperte `Ctrl + C` no terminal (ou, se rodou com `-d`, use `docker compose down`).

**Nas próximas vezes** é só rodar o mesmo comando de novo. Os passos já feitos são pulados e a API liga em segundos.

#####

## Comandos úteis

| O que fazer | Comando |
|---|---|
| Ligar e deixar rodando em segundo plano | `docker compose up -d` |
| Ver o que está acontecendo | `docker compose logs -f api` |
| Ver o andamento da preparação | `docker compose logs -f preparar` |
| Ver se a API está saudável | `docker compose ps` (a coluna *STATUS* deve mostrar `healthy`) |
| Desligar (os dados são mantidos) | `docker compose down` |
| Apagar **tudo** e começar do zero (inclusive os usuários criados) | `docker compose down -v` |
| Medir a qualidade do modelo (passo 6 do README) | `docker compose run --rm api python scripts/avaliar_modelo.py` |
| Refazer a imagem depois de mudar o código | `docker compose up --build` |

> Depois de mudar qualquer arquivo em `app/` ou `scripts/`, use `--build`. Sem ele, o Docker reaproveita a imagem antiga.

#####

## Usar a pasta `data/` do seu computador (opcional)

Por padrão, os dados ficam num **volume do Docker**, e não na pasta `data/` do projeto. Se você quiser usar a sua
pasta `data/` (por exemplo, porque já rodou os scripts sem Docker e não quer baixar 1,4 GB de novo), use o arquivo extra:

```
docker compose -f docker-compose.yml -f docker-compose.local-data.yml up --build
```

Isso também serve de **plano B se o download falhar**: baixe o `book-genome.zip` pelo navegador, coloque na pasta
`data/` e rode o comando acima. O script percebe o zip e pula o download.

#####

## Como funciona

```
Dockerfile                   receita da imagem (Python 3.14 + bibliotecas + código)
docker-compose.yml           os 2 serviços e o volume de dados
docker-compose.local-data.yml  (opcional) usa a pasta ./data do computador
docker/preparar.py           roda os passos 1 a 4 do README, pulando o que já foi feito
.dockerignore                o que NÃO entra na imagem (principalmente a pasta data/)
```

São **dois serviços** que usam a mesma imagem:

* **`preparar`** roda uma vez e termina: baixa a base, trata os dados, treina o modelo e cria o banco (o
  `docker/preparar.py` chama os mesmos scripts do README, na mesma ordem).
* **`api`** só liga depois que o `preparar` termina com sucesso. Isso é necessário porque a API se recusa a ligar sem
  o modelo e o banco (`app/main.py`).

Os dados ficam no volume `dados`, montado em `/app/data` dentro do container.

#####

## Decisões de design

* **A base de dados não entra na imagem.** Ela tem 1,4 GB e não deve ir para o GitHub (o mesmo motivo de `data/` estar
  no `.gitignore`). Assim a imagem fica pequena e a base é baixada uma vez só, para o volume.

* **Volume do Docker em vez de pasta do computador.** O banco da API é um arquivo SQLite, que pode ficar lento (e ter problemas
  de travamento) quando está numa pasta compartilhada do Windows com o container. No volume, ele fica no sistema de
  arquivos do próprio Docker. O volume sobrevive a `docker compose down`, então os usuários criados pela API não
  se perdem. (Quem preferir a pasta do computador usa o `docker-compose.local-data.yml`.)

* **`python:3.14-slim`, e não `alpine`.** O numpy, o pandas, o scikit-learn e o scipy desta versão têm pacotes
  prontos para Debian/Ubuntu. No Alpine eles seriam compilados do zero (muito lento e frágil).

* **Dependências antes do código no Dockerfile.** O Docker guarda cada passo em cache. Assim, mudar um arquivo de
  `app/` não reinstala as bibliotecas.

* **Usuário comum, não root.** Boa prática de segurança: se alguém invadir a API, não tem poderes de administrador
  dentro do container.

* **`preparar.py` confere os arquivos gerados.** Alguns scripts do projeto imprimem "ERRO" mas terminam como se
  tivessem dado certo. Por isso, depois de cada etapa, o `preparar.py` verifica se os arquivos esperados
  realmente existem, e para com uma mensagem clara se não existirem.

* **O banco é criado com outro nome e renomeado no fim.** O `criar_banco.py` desliga as proteções do SQLite para
  gravar mais rápido. Se o container fosse interrompido no meio, sobraria um banco pela metade que pareceria
  pronto. Gravando em `banco.db.parcial` e renomeando só no fim, isso não acontece.

* **O healthcheck usa `GET /tags`.** O `GET /` conta 5 milhões de linhas no banco a cada chamada; seria pesado
  rodá-lo a cada 15 segundos.

* **O código dos colegas não foi alterado.** Tudo do Docker fica em arquivos novos. O projeto continua rodando
  sem Docker, como descrito no README.

#####

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `port is already allocated` / porta 8000 ocupada | Em `docker-compose.yml`, troque `"8000:8000"` por `"8001:8000"` e abra `http://localhost:8001/docs` |
| `exited with code 137` | Falta de memória. Aumente o limite no Docker Desktop (*Settings → Resources*) |
| O download falhou | Use o plano B (zip na pasta `data/` + `docker-compose.local-data.yml`) |
| `Cannot connect to the Docker daemon` | O Docker Desktop não está aberto. Abra e espere ficar verde |
| Mudei o código e nada mudou | Rode com `--build` |
| Quero começar do zero | `docker compose down -v` e depois `docker compose up --build` |
| Linux: erro de permissão com `docker-compose.local-data.yml` | A pasta `data/` precisa pertencer ao usuário de id 1000 (`sudo chown -R 1000:1000 data`) |

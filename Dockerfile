# ---------------------------------------------------------------------------
# Imagem da API de recomendação de livros
#
# Python 3.14 = a mesma versão do README. Use "slim" (Debian) e NÃO "alpine":
# o numpy/pandas/scikit-learn/scipy desta versão só têm pacotes prontos para
# Debian/Ubuntu (glibc). No Alpine, eles seriam compilados do zero (muito lento).
# ---------------------------------------------------------------------------
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Bibliotecas primeiro: esta camada só é refeita se o requirements.txt mudar
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2) Código (a pasta data/ NÃO entra na imagem: ela é um volume, veja o compose)
COPY app/ ./app/
COPY scripts/ ./scripts/
COPY docker/ ./docker/

# 3) Usuário comum em vez de root. A pasta data/ é criada aqui, já com o dono
#    certo, para o volume do Docker nascer gravável.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Escuta em 0.0.0.0 (e não em 127.0.0.1), senão a porta não fica acessível de fora do container
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

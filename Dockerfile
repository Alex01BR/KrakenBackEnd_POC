# O comando FROM especifica a imagem base que será usada para construir a nova imagem Docker.
# Neste caso, estamos usando a imagem oficial do FastAPI com Uvicorn e Gunicorn
FROM tiangolo/uvicorn-gunicorn-fastapi:python3.8

# Configura o Python para reconhecer o diretório /app como package
ENV PYTHONPATH="${PYTHONPATH}:/app"

# Copia o arquivo de dependências primeiro (para aproveitar o cache do Docker)
COPY ./app/requirements.txt /app/requirements.txt

# Instala as dependências Python
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copia todos os arquivos da pasta app local para o diretório /app do container
COPY ./app /app

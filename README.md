# Kraken API - Backend

API simples para gerenciamento de usuários com FastAPI, PostgreSQL, Docker e Traefik.

## Funcionalidades

- **POST /users/** - Criar novos usuários
- **GET /users/** - Listar todos os usuários
- **GET /users/{id}** - Buscar usuário por ID
- **GET /health** - Verificar status da API

## Estrutura do Usuário

Cada usuário pode ter:
- **nome** (obrigatório)
- **senha** (obrigatório - armazenada criptografada)
- **idade** (opcional)
- **email** (opcional)

## Como usar

### 1. Subir a aplicação

```bash
# Criar a rede do Traefik (se não existir)
docker network create traefik-public

# Subir o Traefik
docker-compose -f docker-compose.traefik.yml up -d

# Subir a aplicação
docker-compose up -d
```

### 2. Testar a API

#### Criar um usuário (POST)
```bash
curl -X POST "http://13.221.236.143/users/" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "João",
    "password": "123456",
    "age": 25,
    "email": "joao@email.com"
  }'
```

#### Listar usuários (GET)
```bash
curl "http://13.221.236.143/users/"
```

#### Buscar usuário por ID (GET)
```bash
curl "http://13.221.236.143/users/1"
```

### 3. Documentação automática

Acesse a documentação interativa da API:
- **Swagger UI**: http://13.221.236.143/docs
- **ReDoc**: http://13.221.236.143/redoc

## Estrutura do Projeto

```
app/
├── __init__.py          # Torna app um pacote Python
├── main.py              # Aplicação principal FastAPI
├── database.py          # Configuração do banco PostgreSQL
├── models.py            # Modelos do banco de dados
├── schemas.py           # Modelos de entrada/saída da API
├── crud.py              # Operações do banco de dados
└── requirements.txt     # Dependências Python
```

## Tecnologias

- **FastAPI** - Framework web moderno e rápido
- **PostgreSQL** - Banco de dados relacional
- **SQLAlchemy** - ORM para Python
- **Docker** - Containerização
- **Traefik** - Proxy reverso e balanceador de carga
- **Pydantic** - Validação de dados

## Desenvolvimento

Para adicionar novos campos ao usuário:

1. Edite `app/models.py` - adicione colunas na tabela
2. Edite `app/schemas.py` - adicione campos nos modelos de entrada/saída
3. Edite `app/crud.py` - atualize as funções se necessário

A estrutura está preparada para expansão fácil!

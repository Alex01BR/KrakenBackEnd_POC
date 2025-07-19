"""
API Principal - Kraken Backend
API simples para gerenciar usuários com POST e GET
"""

from fastapi import FastAPI, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import List

# Importa nossos módulos
import crud
import models
import schemas
from database import get_db, create_tables

# Cria a aplicação FastAPI
app = FastAPI(
    title="Kraken API", 
    description="API para gerenciamento de usuários",
    version="1.0.0"
)

# Evento que roda quando a aplicação inicia
@app.on_event("startup")
async def startup_event():
    """
    Cria as tabelas do banco quando a aplicação inicia
    """
    create_tables()

# ENDPOINTS DA API

@app.get("/")
def read_main():
    """
    Endpoint raiz - mantém a mensagem original
    """
    return {"message": "Hello, World of Fast API with Traefik!"}

@app.post("/users/", response_model=schemas.UserResponse)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """
    POST - Criar um novo usuário
    
    Recebe: nome, senha, idade (opcional), email (opcional)
    Retorna: dados do usuário criado (sem a senha)
    """
    # Verifica se já existe um usuário com esse nome
    existing_user = crud.get_user_by_name(db, name=user.name)
    if existing_user:
        raise HTTPException(
            status_code=400, 
            detail="Já existe um usuário com este nome"
        )
    
    # Cria o usuário
    return crud.create_user(db=db, user=user)

@app.get("/users/", response_model=List[schemas.UserResponse])
def get_users(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """
    GET - Listar todos os usuários
    
    Parâmetros opcionais:
    - skip: quantos usuários pular (para paginação)
    - limit: quantos usuários retornar (máximo)
    """
    users = crud.get_users(db, skip=skip, limit=limit)
    return users

@app.get("/users/{user_id}", response_model=schemas.UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    """
    GET - Buscar um usuário específico pelo ID
    """
    user = crud.get_user_by_id(db, user_id=user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado")
    return user

@app.get("/health")
def health_check():
    """
    Endpoint para verificar se a API está funcionando
    """
    from datetime import datetime
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "message": "API Kraken funcionando!"
    }

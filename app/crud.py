"""
Operações CRUD (Create, Read, Update, Delete) para usuários
Funções que interagem diretamente com o banco de dados
"""

from sqlalchemy.orm import Session
import models
import schemas
import hashlib

def hash_password(password: str) -> str:
    """
    Criptografa a senha usando SHA256
    """
    return hashlib.sha256(password.encode()).hexdigest()

def create_user(db: Session, user: schemas.UserCreate):
    """
    Cria um novo usuário no banco de dados
    """
    # Criptografa a senha
    password_hash = hash_password(user.password)
    
    # Cria o objeto do usuário
    db_user = models.User(
        name=user.name,
        password_hash=password_hash,
        age=user.age,
        email=user.email
    )
    
    # Salva no banco
    db.add(db_user)
    db.commit()
    db.refresh(db_user)  # Atualiza o objeto com dados do banco (como ID)
    
    return db_user

def get_user_by_id(db: Session, user_id: int):
    """
    Busca um usuário pelo ID
    """
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_name(db: Session, name: str):
    """
    Busca um usuário pelo nome
    """
    return db.query(models.User).filter(models.User.name == name).first()

def get_users(db: Session, skip: int = 0, limit: int = 100):
    """
    Lista usuários com paginação
    """
    return db.query(models.User).offset(skip).limit(limit).all()

def verify_password(password: str, password_hash: str) -> bool:
    """
    Verifica se a senha está correta
    """
    return hash_password(password) == password_hash

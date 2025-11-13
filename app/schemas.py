"""
Modelos de dados para a API
Define como os dados entram e saem da API
"""

from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from typing import List

class UserCreate(BaseModel):
    """
    Dados necessários para criar um usuário
    """
    name: str  # Nome obrigatório
    password: str  # Senha obrigatória
    age: Optional[int] = None  # Idade opcional
    email: Optional[str] = None  # Email opcional

class UserResponse(BaseModel):
    """
    Dados que a API retorna sobre um usuário (sem a senha)
    """
    id: int
    name: str
    age: Optional[int]
    email: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True  # Permite trabalhar com objetos do banco


class Item(BaseModel):
    id: int
    name: str
    icon: Optional[str] = None
    category: Optional[str] = None
    expirationDate: Optional[datetime] = None
    quantity: int = 1


class SyncRequest(BaseModel):
    items: List[Item]
    pushToken: str


class SyncResponse(BaseModel):
    ok: bool
    message: Optional[str] = None
    saved_count: Optional[int] = 0

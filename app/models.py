from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime
from .database import Base

class User(Base):
    """
    Modelo de usuário no banco de dados
    Estrutura preparada para adicionar mais campos no futuro
    """
    __tablename__ = "users"
    
    # Campos obrigatórios
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Nome do usuário
    password_hash = Column(String, nullable=False)  # Senha criptografada
    
    # Campos opcionais que podem ser expandidos
    age = Column(Integer, nullable=True)  # Idade do usuário
    email = Column(String, nullable=True)  # Email do usuário
    
    # Campo de controle
    created_at = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<User(id={self.id}, name='{self.name}')>"

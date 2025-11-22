from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, BigInteger, Float
from datetime import datetime
from database import Base
from sqlalchemy.orm import relationship

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


class Device(Base):
    """
    Representa um dispositivo/expo push token com configurações personalizadas de notificação
    """
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, index=True)
    push_token = Column(String, unique=True, nullable=False, index=True)
    user_name = Column(String, nullable=True)  # Nome do usuário do dispositivo
    alert_days = Column(Float, default=7)  # Dias de antecedência para enviar notificação (padrão: 7 dias; suporta frações para minutos)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relacionamento com itens da despensa
    items = relationship("PantryItem", back_populates="device")

    def __repr__(self):
        return f"<Device(id={self.id}, user_name='{self.user_name}', alert_days={self.alert_days}, token='{self.push_token[:20]}...')>"


class PantryItem(Base):
    """
    Item armazenado na despensa/pantry associado a um Device (ou usuário futuramente)
    """
    __tablename__ = "pantry_items"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(BigInteger, nullable=False, index=True)  # ID vindo do app (ex: 1763059063201)
    name = Column(String, nullable=False)
    icon = Column(String, nullable=True)
    category = Column(String, nullable=True)
    expiration_date = Column(DateTime, nullable=True)
    quantity = Column(Integer, default=1)

    device_id = Column(Integer, ForeignKey("devices.id"), nullable=False)
    device = relationship("Device", back_populates="items")

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<PantryItem(id={self.id}, external_id={self.external_id}, name='{self.name}')>"

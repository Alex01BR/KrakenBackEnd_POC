"""
Operações CRUD (Create, Read, Update, Delete) para usuários
Funções que interagem diretamente com o banco de dados
"""

from sqlalchemy.orm import Session
import models
import schemas
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import and_

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


def get_or_create_device(db: Session, push_token: str):
    """Retorna o Device com esse push_token, criando se necessário"""
    device = db.query(models.Device).filter(models.Device.push_token == push_token).first()
    if device:
        return device

    device = models.Device(push_token=push_token)
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def upsert_pantry_item(db: Session, device: models.Device, item: schemas.Item):
    """Cria ou atualiza um PantryItem baseado em `external_id` + device"""
    existing = db.query(models.PantryItem).filter(
        and_(
            models.PantryItem.external_id == item.id,
            models.PantryItem.device_id == device.id,
        )
    ).first()

    exp_date = None
    if item.expirationDate:
        # Pydantic já transforma em datetime; manter apenas se for datetime
        exp_date = item.expirationDate

    if existing:
        existing.name = item.name
        existing.icon = item.icon
        existing.category = item.category
        existing.expiration_date = exp_date
        existing.quantity = item.quantity
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    new_item = models.PantryItem(
        external_id=item.id,
        name=item.name,
        icon=item.icon,
        category=item.category,
        expiration_date=exp_date,
        quantity=item.quantity,
        device_id=device.id,
    )
    db.add(new_item)
    db.commit()
    db.refresh(new_item)
    return new_item


def save_items_for_device(db: Session, push_token: str, items: list):
    device = get_or_create_device(db, push_token)
    saved = 0
    for it in items:
        upsert_pantry_item(db, device, it)
        saved += 1
    return device, saved


def get_devices_with_expiring_items(db: Session, within_days: int = 1):
    """Retorna lista de (Device, [PantryItem,...]) com itens expirando em `within_days`"""
    cutoff = datetime.utcnow() + timedelta(days=within_days)
    devices = db.query(models.Device).all()
    result = []
    for d in devices:
        items = [i for i in d.items if i.expiration_date is not None and i.expiration_date <= cutoff]
        if items:
            result.append((d, items))
    return result

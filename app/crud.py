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


def get_or_create_device(db: Session, push_token: str, user_name: str = None, alert_days: float = None):
    """Retorna o Device com esse push_token, criando se necessário. 
    Atualiza user_name e alert_days APENAS se fornecidos (não sobrescreve com padrões).
    """
    device = db.query(models.Device).filter(models.Device.push_token == push_token).first()
    if device:
        # Atualiza APENAS se foram fornecidos (não None)
        if user_name is not None:
            device.user_name = user_name
        if alert_days is not None:
            device.alert_days = alert_days
        db.add(device)
        db.commit()
        db.refresh(device)
        return device

    # Ao criar novo device, usar padrões se não fornecidos
    device = models.Device(
        push_token=push_token, 
        user_name=user_name,
        alert_days=alert_days if alert_days is not None else 7  # Padrão: 7 dias para novo device
    )
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


def save_items_for_device(db: Session, push_token: str, items: list, user_name: str = None, alert_days: float = None):
    """Sincroniza a lista completa enviada pelo dispositivo.

    Estratégia elegante e atômica:
    - Busca todos os itens existentes do device em memória
    - Constrói mapeamentos (external_id -> objeto) para DB e payload
    - Atualiza objetos existentes em memória e cria novos objetos para novos IDs
    - Calcula quais IDs devem ser removidos (existentes - recebidos)
    - Executa deleções em lote
    - Faz um único commit ao final para garantir atomicidade

    Retorna: (device, saved_count, deleted_count, deleted_ids)
    """
    import logging
    logger = logging.getLogger("crud")

    device = get_or_create_device(db, push_token, user_name=user_name, alert_days=alert_days)

    # Carrega itens existentes do DB para este device
    db_items = db.query(models.PantryItem).filter(models.PantryItem.device_id == device.id).all()
    existing_map = {}
    for obj in db_items:
        try:
            existing_map[int(obj.external_id)] = obj
        except Exception:
            existing_map[obj.external_id] = obj

    # Normaliza e mapeia os itens recebidos
    incoming_map = {}
    for it in items:
        try:
            ext_id = int(it.id)
        except Exception:
            ext_id = it.id
        incoming_map[ext_id] = it

    logger.info(f"[CRUD SYNC] Device {device.id} - ANTES DA SINCRONIZAÇÃO:")
    logger.info(f"[CRUD SYNC]   - IDs no DB: {sorted(existing_map.keys())}")
    logger.info(f"[CRUD SYNC]   - IDs recebidos do app: {sorted(incoming_map.keys())}")

    saved = 0
    created = 0
    updated = 0

    # Atualiza existentes e cria novos (em memória)
    for ext_id, incoming in incoming_map.items():
        if ext_id in existing_map:
            obj = existing_map[ext_id]
            obj.name = incoming.name
            obj.icon = incoming.icon
            obj.category = incoming.category
            obj.quantity = incoming.quantity
            obj.expiration_date = incoming.expirationDate if incoming.expirationDate else None
            db.add(obj)
            updated += 1
            logger.info(f"[CRUD SYNC]   - ✏️ ATUALIZADO: ID {ext_id} ({incoming.name})")
        else:
            new_item = models.PantryItem(
                external_id=ext_id,
                name=incoming.name,
                icon=incoming.icon,
                category=incoming.category,
                expiration_date=incoming.expirationDate if incoming.expirationDate else None,
                quantity=incoming.quantity,
                device_id=device.id,
            )
            db.add(new_item)
            created += 1
            logger.info(f"[CRUD SYNC]   - ✅ CRIADO: ID {ext_id} ({incoming.name})")
        saved += 1

    # IDs a deletar: existentes no DB mas que não vieram no payload
    existing_ids = set(existing_map.keys())
    incoming_ids = set(incoming_map.keys())
    to_delete = existing_ids - incoming_ids

    logger.info(f"[CRUD SYNC]   - IDs que estavam no DB: {sorted(existing_ids)}")
    logger.info(f"[CRUD SYNC]   - IDs que vieram no payload: {sorted(incoming_ids)}")
    logger.info(f"[CRUD SYNC]   - IDs a DELETAR (no DB mas não no payload): {sorted(to_delete)}")

    deleted_ids = []
    deleted_count = 0
    if to_delete:
        # Buscar objetos a deletar para coletar seus external_ids e então deletar
        objs_to_delete = db.query(models.PantryItem).filter(
            models.PantryItem.device_id == device.id,
            models.PantryItem.external_id.in_(list(to_delete))
        ).all()
        deleted_ids = [int(o.external_id) if hasattr(o.external_id, '__int__') else o.external_id for o in objs_to_delete]
        for o in objs_to_delete:
            logger.info(f"[CRUD SYNC]   - ❌ DELETADO: ID {o.external_id} ({o.name})")
            db.delete(o)
        deleted_count = len(objs_to_delete)

    # Commit único
    db.commit()

    logger.info(f"[CRUD SYNC] RESULTADO FINAL: created={created}, updated={updated}, deleted={deleted_count}")
    logger.info(f"[CRUD SYNC] Device {device.id} - IDs mantidos: {sorted(incoming_ids)}")

    return device, saved, deleted_count, deleted_ids


def get_devices_with_expiring_items(db: Session, within_days: int = 7):
    """Retorna lista de (Device, [PantryItem,...]) com itens expirando em até `within_days` dias (não incluindo já vencidos)"""
    now = datetime.utcnow()
    cutoff = now + timedelta(days=within_days)
    devices = db.query(models.Device).all()
    result = []
    for d in devices:
        # Filtra itens que estão entre agora e dentro de within_days (não vencidos e vencendo em breve)
        items = [i for i in d.items if i.expiration_date is not None and now <= i.expiration_date <= cutoff]
        if items:
            # Ordena por data de vencimento (mais próximos primeiro)
            items.sort(key=lambda x: x.expiration_date)
            result.append((d, items))
    return result

"""
API Principal - Kraken Backend
API simples para gerenciar usuários com POST e GET
"""

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List
from pydantic import ValidationError

# Importa nossos módulos
import crud
import models
import schemas
from database import get_db, create_tables
from scheduler import get_scheduler, shutdown_scheduler

from datetime import datetime
import notifications
from sqlalchemy.orm import Session as DBSession
import logging
import threading

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("kraken_api")

# Per-device locks para evitar execução paralela do mesmo job
device_locks = {}
device_locks_lock = threading.Lock()

def get_device_lock(device_id: int):
    """Retorna o lock para um device específico (thread-safe)"""
    global device_locks
    with device_locks_lock:
        if device_id not in device_locks:
            device_locks[device_id] = threading.Lock()
        return device_locks[device_id]

# Cria a aplicação FastAPI
app = FastAPI(
    title="Kraken API", 
    description="API para gerenciamento de usuários",
    version="1.0.0"
)

# Handler customizado para erros de validação Pydantic
@app.exception_handler(ValidationError)
async def validation_exception_handler(request: Request, exc: ValidationError):
    logger.error(f"❌ [VALIDATION ERROR] Erro ao validar payload: {exc}")
    logger.error(f"    Errors: {exc.errors()}")
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Validation error",
            "errors": exc.errors()
        },
    )

# Evento que roda quando a aplicação inicia
@app.on_event("startup")
async def startup_event():
    """
    Cria as tabelas do banco quando a aplicação inicia e inicializa o scheduler SINGLETON
    """
    logger.info("🚀 Iniciando aplicação Kraken API...")
    create_tables()
    logger.info("✅ Tabelas do banco criadas/verificadas")
    
    try:
        # Usar scheduler SINGLETON (apenas 1 por aplicação)
        scheduler = get_scheduler()
        
        # Se já está rodando, apenas usar a instância existente
        if scheduler.running:
            logger.info("✅ Scheduler já estava rodando em outro worker, usando instância singleton")
            app.state.scheduler = scheduler
            return
        
        logger.info("🔄 Configurando jobs do scheduler singleton...")

        def create_device_notification_job(device_id: int, alert_days: float, user_name: str = None):
            """Cria uma função de job específica para um device"""
            # Usar lock por device para evitar execução paralela
            device_lock = get_device_lock(device_id)
            
            def job_send_notification_for_device():
                # Tenta adquirir o lock SEM BLOQUEAR
                if not device_lock.acquire(blocking=False):
                    logger.debug(f"⚠️ [JOB DEVICE {device_id}] Job já está em execução, pulando esta rodada")
                    return
                
                try:
                    logger.info(f"⏰ [JOB DEVICE {device_id}] Iniciando verificação para device {device_id} ({user_name or 'sem nome'}) | alert_days: {alert_days}")
                    
                    db = next(get_db())
                    try:
                        device = db.query(models.Device).filter(models.Device.id == device_id).first()
                        if not device:
                            logger.warning(f"⚠️ [JOB DEVICE {device_id}] Device não encontrado")
                            return
                        
                        # Busca itens que expiram dentro de alert_days
                        # Use a fixed notification window of 7 days for alerts
                        pairs = crud.get_devices_with_expiring_items(db, within_days=7)
                        device_pairs = [(d, items) for d, items in pairs if d.id == device_id]
                        
                        if device_pairs:
                            for _, items in device_pairs:
                                logger.info(f"  📦 Encontrados {len(items)} item(ns) próximos do vencimento para {device.user_name or 'device'}")
                                for item in items:
                                    logger.info(f"      - {item.name} | Vence em: {item.expiration_date}")
                                
                                # Monta mensagem
                                title = "⚠️ Itens próximos do vencimento"
                                item_names = ", ".join([it.name for it in items[:3]])
                                if len(items) > 3:
                                    body = f"{item_names} e mais {len(items) - 3}. Confira seus itens!"
                                else:
                                    body = f"{item_names}. Verifique a validade!"
                                
                                # Envia notificação
                                logger.info(f"📤 [JOB DEVICE {device_id}] Enviando notificação para {device.push_token[:20]}...")
                                result = notifications.send_expo_push(device.push_token, title, body, {})
                                if result.get('ok'):
                                    logger.info(f"✅ [JOB DEVICE {device_id}] Notificação enviada com sucesso!")
                                else:
                                    logger.error(f"❌ [JOB DEVICE {device_id}] Erro ao enviar: {result}")
                        else:
                            logger.debug(f"ℹ️ [JOB DEVICE {device_id}] Nenhum item próximo do vencimento")
                    except Exception as e:
                        logger.error(f"❌ [JOB DEVICE {device_id}] Erro ao processar device: {e}", exc_info=True)
                    finally:
                        db.close()
                finally:
                    device_lock.release()
            
            return job_send_notification_for_device

        # Carrega devices existentes e cria jobs para cada um
        db = next(get_db())
        try:
            devices = db.query(models.Device).all()
            logger.info(f"📱 Carregando {len(devices)} device(s) para agendamento...")
            
            for device in devices:
                alert_days = device.alert_days if device.alert_days else 7
                
                # Converter para minutos se for < 1 dia
                if alert_days < 1:
                    interval_minutes = alert_days * 24 * 60
                    job_func = create_device_notification_job(device.id, alert_days, device.user_name)
                    job_id = f"device_{device.id}"
                    scheduler.add_job(job_func, 'interval', minutes=interval_minutes, id=job_id, max_instances=1, replace_existing=True)
                    logger.info(f"  ✅ Job criado para Device {device.id} ({device.user_name or 'sem nome'}) - intervalo: {interval_minutes:.2f} minuto(s)")
                else:
                    job_func = create_device_notification_job(device.id, alert_days, device.user_name)
                    job_id = f"device_{device.id}"
                    scheduler.add_job(job_func, 'interval', days=alert_days, id=job_id, max_instances=1, replace_existing=True)
                    logger.info(f"  ✅ Job criado para Device {device.id} ({device.user_name or 'sem nome'}) - intervalo: {alert_days} dia(s)")
        finally:
            db.close()
        
        # Inicia o scheduler (idempotente - se já está rodando, não faz nada)
        if not scheduler.running:
            scheduler.start()
        
        app.state.scheduler = scheduler
        logger.info("✅ Agendador iniciado - Jobs por device configurados com alert_days específicos")
    except Exception as e:
        logger.error(f"❌ Não foi possível iniciar o agendador: {e}", exc_info=True)


@app.on_event("shutdown")
def shutdown_event():
    logger.warning("⛔ Encerrando aplicação Kraken API...")
    shutdown_scheduler()
    logger.info("✅ Scheduler finalizado")

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
    return {
        "status": "healthy", 
        "timestamp": datetime.utcnow(),
        "message": "API Kraken funcionando!"
    }


def register_device_job(device_id: int, alert_days: float, user_name: str = None):
    """Registra ou atualiza o job de notificação para um device específico"""
    scheduler = getattr(app.state, 'scheduler', None)
    if not scheduler:
        logger.warning(f"⚠️ Scheduler não está ativo, não foi possível registrar job para device {device_id}")
        return
    
    try:
        # Converter alert_days para o melhor formato para APScheduler
        if alert_days < 1:
            interval_minutes = alert_days * 24 * 60
            interval_type = 'minutes'
            interval_value = interval_minutes
            interval_display = f"{interval_minutes:.2f} minuto(s)"
        else:
            interval_type = 'days'
            interval_value = alert_days
            interval_display = f"{alert_days} dia(s)"
        
        # Criar job function
        def create_device_notification_job(device_id: int, alert_days: float, user_name: str = None):
            """Cria uma função de job específica para um device"""
            device_lock = get_device_lock(device_id)
            
            def job_send_notification_for_device():
                if not device_lock.acquire(blocking=False):
                    logger.debug(f"⚠️ [JOB DEVICE {device_id}] Job já está em execução, pulando esta rodada")
                    return
                
                try:
                    logger.info(f"⏰ [JOB DEVICE {device_id}] Iniciando verificação para device {device_id} ({user_name or 'sem nome'}) | alert_days: {alert_days}")
                    
                    db = next(get_db())
                    try:
                        device = db.query(models.Device).filter(models.Device.id == device_id).first()
                        if not device:
                            logger.warning(f"⚠️ [JOB DEVICE {device_id}] Device não encontrado")
                            return
                        
                        # Use a fixed notification window of 7 days for alerts
                        pairs = crud.get_devices_with_expiring_items(db, within_days=7)
                        device_pairs = [(d, items) for d, items in pairs if d.id == device_id]
                        
                        if device_pairs:
                            for _, items in device_pairs:
                                logger.info(f"  📦 Encontrados {len(items)} item(ns) próximos do vencimento para {device.user_name or 'device'}")
                                for item in items:
                                    logger.info(f"      - {item.name} | Vence em: {item.expiration_date}")
                                
                                title = "⚠️ Itens próximos do vencimento"
                                item_names = ", ".join([it.name for it in items[:3]])
                                if len(items) > 3:
                                    body = f"{item_names} e mais {len(items) - 3}. Confira seus itens!"
                                else:
                                    body = f"{item_names}. Verifique a validade!"
                                
                                logger.info(f"📤 [JOB DEVICE {device_id}] Enviando notificação para {device.push_token[:20]}...")
                                result = notifications.send_expo_push(device.push_token, title, body, {})
                                if result.get('ok'):
                                    logger.info(f"✅ [JOB DEVICE {device_id}] Notificação enviada com sucesso!")
                                else:
                                    logger.error(f"❌ [JOB DEVICE {device_id}] Erro ao enviar: {result}")
                        else:
                            logger.debug(f"ℹ️ [JOB DEVICE {device_id}] Nenhum item próximo do vencimento")
                    except Exception as e:
                        logger.error(f"❌ [JOB DEVICE {device_id}] Erro ao processar device: {e}", exc_info=True)
                    finally:
                        db.close()
                finally:
                    device_lock.release()
            
            return job_send_notification_for_device

        job_func = create_device_notification_job(device_id, alert_days, user_name)
        job_id = f"device_{device_id}"
        
        # Registra job com intervalo dinâmico
        if interval_type == 'minutes':
            scheduler.add_job(job_func, 'interval', minutes=interval_value, id=job_id, max_instances=1, replace_existing=True)
        else:
            scheduler.add_job(job_func, 'interval', days=interval_value, id=job_id, max_instances=1, replace_existing=True)
        
        logger.info(f"📌 [JOB REGISTRY] Job registrado para Device {device_id} ({user_name or 'sem nome'}) - intervalo: {interval_display}")
    except Exception as e:
        logger.error(f"❌ [JOB REGISTRY] Erro ao registrar job para device {device_id}: {e}", exc_info=True)

@app.post("/sync", response_model=schemas.SyncResponse)
def sync_items(payload: schemas.SyncRequest, db: Session = Depends(get_db)):
    """
    Recebe `items`, `pushToken`, `userName` (opcional), e `alertDays` (opcional) do aplicativo (Expo) e persiste por dispositivo.

    Corpo esperado: { items: [...], pushToken: "ExponentPushToken[...]", userName: "João", alertDays: 7 }
    """
    logger.info(f"📥 [SYNC] Recebido sincronização | Token: {payload.pushToken[:20]}... | Usuario: {payload.userName} | alertDays: {payload.alertDays} | {len(payload.items)} item(ns)")
    try:
        device, saved, deleted_count, deleted_ids = crud.save_items_for_device(
            db, 
            payload.pushToken, 
            payload.items, 
            user_name=payload.userName, 
            alert_days=payload.alertDays
        )
        logger.info(f"✅ [SYNC] {saved} item(ns) salvos para device ID {device.id} (user: {device.user_name}, alert_days: {device.alert_days}) | {deleted_count} item(ns) excluídos")
        
        # Registra ou atualiza o job de notificação para este device
        alert_days = device.alert_days if device.alert_days else 7
        register_device_job(device.id, alert_days, device.user_name)
        
        return {"ok": True, "message": "Items sincronizados com sucesso", "saved_count": saved, "deleted_count": deleted_count, "deleted_ids": deleted_ids}
    except Exception as e:
        logger.error(f"❌ [SYNC] Erro ao salvar items: {e}", exc_info=True)
        return {"ok": False, "message": str(e), "saved_count": 0, "deleted_count": 0, "deleted_ids": []}

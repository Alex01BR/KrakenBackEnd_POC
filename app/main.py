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

from apscheduler.schedulers.background import BackgroundScheduler
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

# Lock para evitar execução simultânea do job
job_lock = threading.Lock()
job_running = False

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
    global job_running
    
    logger.info("🚀 Iniciando aplicação Kraken API...")
    create_tables()
    logger.info("✅ Tabelas do banco criadas/verificadas")
    
    # Verificar se agendador já existe (evitar duplicação em reload)
    if hasattr(app.state, 'scheduler') and app.state.scheduler:
        logger.warning("⚠️ Agendador já estava ativo, limpando...")
        try:
            app.state.scheduler.shutdown()
        except:
            pass
    
    # Agendador para enviar notificações a cada 5 minutos
    try:
        scheduler = BackgroundScheduler()

        def job_send_notifications():
            global job_running
            
            # Usar lock para evitar execução simultânea
            if not job_lock.acquire(blocking=False):
                logger.warning("⚠️ [JOB SCHEDULER] Job já está em execução, pulando esta rodada")
                return
            
            try:
                job_running = True
                logger.info("=" * 80)
                logger.info("⏰ [JOB SCHEDULER] Iniciando verificação de itens com vencimento próximo...")
                db = next(get_db())
                try:
                    pairs = crud.get_devices_with_expiring_items(db, within_days=7)
                    
                    if not pairs:
                        logger.info("ℹ️ [JOB SCHEDULER] Nenhum dispositivo com itens próximos do vencimento encontrado")
                        return
                    
                    logger.info(f"📱 [JOB SCHEDULER] Encontrados {len(pairs)} dispositivo(s) com itens vencendo...")
                    
                    messages = []
                    for device_idx, (device, items) in enumerate(pairs, 1):
                        logger.info(f"  [{device_idx}] Device ID {device.id} | Token: {device.push_token[:20]}... | {len(items)} item(ns)")
                        for item in items:
                            logger.info(f"      - {item.name} | Vence em: {item.expiration_date}")
                        
                        # Monta mensagem com detalhes dos itens expirando
                        title = "⚠️ Itens próximos do vencimento"
                        item_names = ", ".join([it.name for it in items[:3]])  # Até 3 itens no resumo
                        if len(items) > 3:
                            body = f"{item_names} e mais {len(items) - 3}. Confira seus itens!"
                        else:
                            body = f"{item_names}. Verifique a validade!"
                        messages.append({"to": device.push_token, "title": title, "body": body})
                    
                    if messages:
                        logger.info(f"📤 [JOB SCHEDULER] Enviando {len(messages)} notificação(ões) via Expo Push...")
                        results = notifications.send_many_expo_push(messages)
                        logger.info(f"✅ [JOB SCHEDULER] Envio concluído!")
                    else:
                        logger.info("ℹ️ [JOB SCHEDULER] Nenhuma mensagem para enviar")
                        
                except Exception as e:
                    logger.error(f"❌ [JOB SCHEDULER] Erro ao enviar notificações: {e}", exc_info=True)
                finally:
                    db.close()
                logger.info("=" * 80)
            finally:
                job_running = False
                job_lock.release()

        # Agenda para rodar a cada 5 minutos
        scheduler.add_job(job_send_notifications, 'interval', minutes=5, max_instances=1)
        scheduler.start()
        app.state.scheduler = scheduler
        logger.info("✅ Agendador iniciado - Job de notificações rodará a cada 5 minutos")
    except Exception as e:
        logger.error(f"❌ Não foi possível iniciar o agendador: {e}", exc_info=True)


@app.on_event("shutdown")
def shutdown_event():
    logger.warning("⛔ Encerrando aplicação Kraken API...")
    sched = getattr(app.state, 'scheduler', None)
    if sched:
        sched.shutdown()
        logger.info("✅ Agendador finalizado")

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


@app.post("/sync", response_model=schemas.SyncResponse)
def sync_items(payload: schemas.SyncRequest, db: Session = Depends(get_db)):
    """
    Recebe `items` e `pushToken` do aplicativo (Expo) e persiste por dispositivo.

    Corpo esperado: { items: [...], pushToken: "ExponentPushToken[...]" }
    """
    logger.info(f"📥 [SYNC] Recebido sincronização | Token: {payload.pushToken[:20]}... | {len(payload.items)} item(ns)")
    try:
        device, saved = crud.save_items_for_device(db, payload.pushToken, payload.items)
        logger.info(f"✅ [SYNC] {saved} item(ns) salvos para device ID {device.id}")
        return {"ok": True, "message": "Items salvos com sucesso", "saved_count": saved}
    except Exception as e:
        logger.error(f"❌ [SYNC] Erro ao salvar items: {e}", exc_info=True)
        return {"ok": False, "message": str(e), "saved_count": 0}

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
    # Agendador diário para enviar notificações
    try:
        scheduler = BackgroundScheduler()

        def job_send_notifications():
            # Esse job roda e envia notificações para dispositivos com itens expirando
            db = next(get_db())
            try:
                pairs = crud.get_devices_with_expiring_items(db, within_days=1)
                messages = []
                for device, items in pairs:
                    # Monta mensagem simples
                    title = "Itens próximos da validade"
                    body = f"Você tem {len(items)} item(ns) expirando em breve."
                    messages.append({"to": device.push_token, "title": title, "body": body})
                if messages:
                    notifications.send_many_expo_push(messages)
            finally:
                db.close()

        # Agenda para rodar todo dia às 09:00 UTC
        scheduler.add_job(job_send_notifications, 'cron', hour=9, minute=0)
        scheduler.start()
        app.state.scheduler = scheduler
    except Exception as e:
        print(f"Não foi possível iniciar o agendador: {e}")


@app.on_event("shutdown")
def shutdown_event():
    sched = getattr(app.state, 'scheduler', None)
    if sched:
        sched.shutdown()

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
    try:
        device, saved = crud.save_items_for_device(db, payload.pushToken, payload.items)
        return {"ok": True, "message": "Items salvos com sucesso", "saved_count": saved}
    except Exception as e:
        return {"ok": False, "message": str(e), "saved_count": 0}

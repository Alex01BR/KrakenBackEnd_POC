"""
Scheduler Singleton - Garante que apenas uma instância do scheduler existe
"""
from apscheduler.schedulers.background import BackgroundScheduler
import logging
import threading

logger = logging.getLogger("kraken_api")

# Singleton lock
_scheduler_lock = threading.Lock()
_scheduler_instance = None

def get_scheduler():
    """
    Retorna a instância única do scheduler.
    Se não existir, cria uma nova.
    """
    global _scheduler_instance
    
    if _scheduler_instance is None:
        with _scheduler_lock:
            # Double-check locking pattern
            if _scheduler_instance is None:
                logger.info("🔧 Criando nova instância de scheduler (SINGLETON)")
                _scheduler_instance = BackgroundScheduler()
    
    return _scheduler_instance

def shutdown_scheduler():
    """
    Encerra o scheduler singleton
    """
    global _scheduler_instance
    
    if _scheduler_instance is not None:
        with _scheduler_lock:
            if _scheduler_instance is not None and _scheduler_instance.running:
                logger.info("🛑 Encerrando scheduler singleton...")
                _scheduler_instance.shutdown()
                _scheduler_instance = None

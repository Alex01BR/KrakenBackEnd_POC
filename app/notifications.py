import requests
from typing import List, Dict
import logging
from datetime import datetime

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("notifications")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


def send_expo_push(push_token: str, title: str, body: str, data: Dict = None) -> Dict:
    """Envia uma notificação para um único expo push token."""
    payload = {
        "to": push_token,
        "title": title,
        "body": body,
    }
    if data is not None:
        payload["data"] = data

    try:
        logger.info(f"[ENVIANDO] Push para token: {push_token[:20]}... | Título: '{title}' | Corpo: '{body}'")
        logger.debug(f"[PAYLOAD] {payload}")
        
        resp = requests.post(EXPO_PUSH_URL, json=payload, timeout=10)
        status_code = resp.status_code
        response_data = resp.json()
        
        if status_code == 200:
            logger.info(f"[SUCESSO] Token {push_token[:20]}... | Status: {status_code} | Resposta: {response_data}")
            return {"ok": True, "status_code": status_code, "response": response_data}
        else:
            logger.warning(f"[ERRO HTTP] Token {push_token[:20]}... | Status: {status_code} | Resposta: {response_data}")
            return {"ok": False, "status_code": status_code, "response": response_data}
    except requests.exceptions.Timeout:
        logger.error(f"[TIMEOUT] Token {push_token[:20]}... | Erro: Timeout na requisição (10s)")
        return {"ok": False, "error": "Timeout na requisição"}
    except requests.exceptions.ConnectionError as e:
        logger.error(f"[CONEXÃO] Token {push_token[:20]}... | Erro: {str(e)}")
        return {"ok": False, "error": f"Erro de conexão: {str(e)}"}
    except Exception as e:
        logger.error(f"[EXCEÇÃO] Token {push_token[:20]}... | Erro: {str(e)}", exc_info=True)
        return {"ok": False, "error": str(e)}


def send_many_expo_push(messages: List[Dict]) -> List[Dict]:
    """Envia várias mensagens (cada mensagem é dict compatível com o endpoint)."""
    logger.info(f"[LOTE] Iniciando envio de {len(messages)} notificação(ões)...")
    results = []
    success_count = 0
    error_count = 0
    
    for idx, m in enumerate(messages, 1):
        token = m.get("to") or m.get("pushToken")
        title = m.get("title")
        body = m.get("body")
        data = m.get("data")
        
        logger.info(f"[{idx}/{len(messages)}] Processando mensagem para token: {token[:20]}...")
        result = send_expo_push(token, title, body, data)
        results.append(result)
        
        if result.get("ok"):
            success_count += 1
        else:
            error_count += 1
    
    logger.info(f"[RESUMO LOTE] Total: {len(messages)} | Sucesso: {success_count} | Erros: {error_count}")
    return results

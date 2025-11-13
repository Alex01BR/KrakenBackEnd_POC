import requests
from typing import List, Dict

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
        resp = requests.post(EXPO_PUSH_URL, json=payload, timeout=10)
        return {"ok": resp.status_code == 200, "status_code": resp.status_code, "response": resp.json()}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_many_expo_push(messages: List[Dict]) -> List[Dict]:
    """Envia várias mensagens (cada mensagem é dict compatível com o endpoint)."""
    results = []
    for m in messages:
        token = m.get("to") or m.get("pushToken")
        title = m.get("title")
        body = m.get("body")
        data = m.get("data")
        results.append(send_expo_push(token, title, body, data))
    return results

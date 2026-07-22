import os
import time
import requests
from datetime import datetime

# Configurações do Telegram e da API-Football
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY")

def enviar_mensagem(texto):
    """Envia alertas formatados para o Telegram"""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")

def buscar_jogos_ao_vivo():
    """Consulta partidas ao vivo na API-Football"""
    if not API_FOOTBALL_KEY:
        print("Erro: API_FOOTBALL_KEY não configurada.")
        return

    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY
    }
    
    try:
        resposta = requests.get(url, headers=headers, timeout=15)
        if resposta.status_code == 200:
            dados = resposta.json().get("response", [])
            print(f"Partidas ao vivo encontradas: {len(dados)}")
            
            # Exemplo de varredura nas partidas ativas
            for item in dados:
                liga = item.get("league", {}).get("name", "Liga Desconhecida")
                casa = item.get("teams", {}).get("home", {}).get("name", "Casa")
                fora = item.get("teams", {}).get("away", {}).get("name", "Fora")
                minuto = item.get("fixture", {}).get("status", {}).get("elapsed", 0)
                gols_casa = item.get("goals", {}).get("home", 0)
                gols_fora = item.get("goals", {}).get("away", 0)
                
                # Exemplo de filtro ou log no console do Render
                print(f"[{liga}] {casa} {gols_casa} x {gols_fora} {fora} (Minuto: {minuto}')")
                
                # Aqui no futuro encaixaremos a sua regra de escanteios HT ou pressão!
                
        else:
            print(f"Erro na API: Status {resposta.status_code}")
            
    except Exception as e:
        print(f"Erro na requisição: {e}")

if __name__ == "__main__":
    print("Bot de monitoramento via API-Football iniciado...")
    enviar_mensagem("🤖 *Robô conectado à API-Football iniciado com sucesso!* 🚀")
    
    while True:
        buscar_jogos_ao_vivo()
        # Aguarda 3 minutos antes da próxima varredura para poupar cotas do plano gratuito
        time.sleep(180)

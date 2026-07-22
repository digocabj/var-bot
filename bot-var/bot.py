import os
import time
import requests

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

def buscar_eventos_partida(fixture_id):
    """Busca os eventos detalhados de uma partida (para rastrear VAR, cartões, etc.)"""
    url = f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    
    try:
        resposta = requests.get(url, headers=headers, timeout=10)
        if resposta.status_code == 200:
            return resposta.json().get("response", [])
    except Exception as e:
        print(f"Erro ao buscar eventos do jogo {fixture_id}: {e}")
    return []

def monitorar_jogos():
    """Varre jogos ao vivo e analisa interrupções e paralisações"""
    if not API_FOOTBALL_KEY:
        print("Erro: API_FOOTBALL_KEY não configurada.")
        return

    url = "https://v3.football.api-sports.io/fixtures?live=all"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    
    try:
        resposta = requests.get(url, headers=headers, timeout=15)
        if resposta.status_code == 200:
            dados = resposta.json().get("response", [])
            print(f"Analisando {len(dados)} partidas ao vivo...")
            
            for item in dados:
                fixture_id = item.get("fixture", {}).get("id")
                liga = item.get("league", {}).get("name", "Liga")
                casa = item.get("teams", {}).get("home", {}).get("name", "Casa")
                fora = item.get("teams", {}).get("away", {}).get("name", "Fora")
                minuto = item.get("fixture", {}).get("status", {}).get("elapsed", 0)
                
                # Exemplo: focar na reta final do primeiro tempo (35' a 45') ou do segundo tempo
                if minuto >= 35:
                    eventos = buscar_eventos_partida(fixture_id)
                    
                    # Contabiliza quantas interrupções/eventos relevantes ocorreram
                    contador_var = sum(1 for ev in eventos if "var" in ev.get("detail", "").lower())
                    contador_cartoes = sum(1 for ev in eventos if ev.get("type") == "Card")
                    
                    # Se houver movimentação intensa (ex: VAR acionado ou muitos cartões/paralisações)
                    if contador_var > 0 or contador_cartoes >= 2:
                        mensagem = (
                            f"🚨 *ALERTA DE JOGO PARADO!* 🚨\n\n"
                            f"🏆 *Liga:* {liga}\n"
                            f"⚽ *Confronto:* {casa} x {fora}\n"
                            f"⏱ *Minuto:* {minuto}'\n"
                            f"📺 *Eventos VAR:* {contador_var}\n"
                            f" *Cartões/Paralisações:* {contador_cartoes}\n\n"
                            f"_Cenário ideal para olho em acréscimos e pressão final!_"
                        )
                        enviar_mensagem(mensagem)
                        print(f"Alerta enviado para: {casa} vs {fora}")
                        
        else:
            print(f"Erro na API: Status {resposta.status_code}")
            
    except Exception as e:
        print(f"Erro na requisição: {e}")

if __name__ == "__main__":
    print("Bot de interrupções e VAR iniciado...")
    enviar_mensagem("🤖 *Robô de monitoramento de interrupções (VAR/Paralisações) ativado!* ⚽")
    
    while True:
        monitorar_jogos()
        # Aguarda 3 minutos entre as varreduras
        time.sleep(180)

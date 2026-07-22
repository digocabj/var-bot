import os
import time
import requests
from datetime import datetime

# Configurações do Telegram pegando das variáveis de ambiente do Render
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def enviar_mensagem(texto):
    """Função para disparar alertas no Telegram"""
    if not TOKEN or not CHAT_ID:
        print("Erro: TELEGRAM_TOKEN ou TELEGRAM_CHAT_ID não configurados.")
        return
    
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": texto,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Mensagem enviada com sucesso!")
        else:
            print(f"Erro ao enviar mensagem: {response.text}")
    except Exception as e:
        print(f"Erro na requisição: {e}")

def monitorar_partidas():
    """Função principal de monitoramento"""
    hora_atual = datetime.now().strftime("%d/%m/%Y %H:%M")
    
    # Mensagem de teste/status inicial
    mensagem = (
        f"🤖 *Bot de VAR / Análise Ativo!*\n"
        f"⏱️ Horário da verificação: {hora_atual}\n"
        f"🟢 Sistema rodando e conectado com sucesso."
    )
    enviar_mensagem(mensagem)

if __name__ == "__main__":
    print("Bot iniciado...")
    # Executa o monitoramento inicial ao ligar
    monitorar_partidas()
    
    # Loop para manter o robô rodando (exemplo checando a cada 5 minutos)
    while True:
        # Aqui depois vamos encaixar a chamada para a API (Packball / FootyStats)
        time.sleep(300) # 300 segundos = 5 minutos

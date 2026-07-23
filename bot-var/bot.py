import requests

# Suas credenciais atuais
TELEGRAM_BOT_TOKEN = "889617524:AAHOeemjzfZILLzw5oi5hsP5ThCroBek"
TELEGRAM_CHAT_ID = "675279616"

# Mensagem de teste direta
url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": "Teste de mensagem do bot-var! Se você leu isso, a conexão está funcionando."
}

response = requests.post(url, json=payload)
print("Resposta do Telegram:", response.json())

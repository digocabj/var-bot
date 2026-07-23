import time
import requests
import pandas as pd
from telegram import Bot

# --- CONFIGURAÇÕES ---
TELEGRAM_BOT_TOKEN = "8896171524:AAHOeemjzfzILlzw5yoi5hsz8P5ThCroBek"
TELEGRAM_CHAT_ID = "675279616"
# Sua chave oficial da API-Sports que usamos nos testes anteriores:
API_FOOTBALL_KEY = "80ad3bfb17e12e4244133f4d13b13cea"

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# Dicionário para controlar para não mandar alerta repetido do mesmo jogo
alertas_enviados = set()

def carregar_ids_excel():
    # Lê a sua planilha (certifique-se que a coluna com os IDs chama 'api_football_id')
    df = pd.read_excel("sua_lista_de_times.xlsx")
    return df['api_football_id'].dropna().astype(int).tolist()

def buscar_estatisticas_detalhadas(fixture_id):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY
    }
    response = requests.get(url, headers=headers, params={"fixture": fixture_id})
    return response.json().get('response', [])

def rodar_varredura():
    print("🔄 Varredura iniciada...")
    ids_monitorados = carregar_ids_excel()
    
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        "x-apisports-key": API_FOOTBALL_KEY
    }
    
    # Puxa todos os jogos ao vivo do dia na API oficial
    response = requests.get(url, headers=headers, params={"live": "all"})
    dados = response.json()
    
    for match in dados.get('response', []):
        fixture_id = match['fixture']['id']
        home_id = match['teams']['home']['id']
        
        # 1. O time da casa está na sua lista?
        if home_id in ids_monitorados:
            elapsed = match['fixture']['status']['elapsed']
            
            # 2. Está entre o minuto 1 e 35 do 1º tempo?
            if elapsed is not None and 1 <= elapsed <= 35:
                home_goals = match['goals']['home'] or 0
                away_goals = match['goals']['away'] or 0
                
                # 3. O mandante está empatando ou perdendo?
                if home_goals <= away_goals:
                    
                    # Puxa as estatísticas para validar a posse de bola (> 60%) e inputs adicionais
                    stats = buscar_estatisticas_detalhadas(fixture_id)
                    if stats and len(stats) >= 2:
                        # Identifica de forma segura qual bloco pertence ao mandante
                        home_stats = None
                        for team_stat in stats:
                            if team_stat['team']['id'] == home_id:
                                home_stats = team_stat['statistics']
                                break
                        
                        if not home_stats:
                            continue

                        possession = 0
                        corners = 0
                        shots_on_goal = 0
                        total_shots = 0

                        for stat in home_stats:
                            stype = stat['type']
                            val = stat['value']
                            
                            if stype == 'Ball Possession' and val:
                                possession = int(str(val).replace('%', ''))
                            elif stype == 'Corner Kicks' and val is not None:
                                corners = int(val)
                            elif stype == 'Shots on Goal' and val is not None:
                                shots_on_goal = int(val)
                            elif stype == 'Total Shots' and val is not None:
                                total_shots = int(val)
                    
                        if possession >= 60:
                            # Chave única para evitar spam do mesmo jogo no mesmo minuto/condição
                            alerta_key = f"{fixture_id}_{elapsed}"
                            if alerta_key not in alertas_enviados:
                                home_name = match['teams']['home']['name']
                                away_name = match['teams']['away']['name']
                                league_name = match['league']['name']
                                
                                mensagem = (
                                    f"🚨 **ALERTA DE PRESSÃO HT** 🚨\n\n"
                                    f"🏆 **Liga:** {league_name}\n"
                                    f"🏠 **{home_name}** vs {away_name}\n"
                                    f"⏱ Minuto: **{elapsed}'**\n"
                                    f"⚽ Placar: **{home_goals} - {away_goals}**\n\n"
                                    f"📊 **Estatísticas do Mandante:**\n"
                                    f"• Posse de Bola: **{possession}%**\n"
                                    f"• Escanteios: **{corners}**\n"
                                    f"• Chutes a Gol: **{shots_on_goal}**\n"
                                    f"• Finalizações Totais: **{total_shots}**\n\n"
                                    f"🔥 *Condições batidas! Hora de olhar o mercado de cantos.*"
                                )
                                
                                bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=mensagem, parse_mode="Markdown")
                                alertas_enviados.add(alerta_key)

if __name__ == "__main__":
    print("🤖 Robô do Telegram ligado e monitorando via API oficial...")
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"Erro na varredura: {e}")
        
        # Aguarda 60 segundos para a próxima checagem
        time.sleep(60)

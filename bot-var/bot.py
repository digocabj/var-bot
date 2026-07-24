import os
import time
from datetime import datetime, timezone, timedelta
import threading
import http.server
import socketserver
import requests
import pandas as pd

# Servidor HTTP simples para manter a porta 10000 aberta (Evita que o Render derrube o background worker)


# Configurações de Tokens e Chaves
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")

alertas_enviados = set()
historico_partidas = {}

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": mensagem,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Erro ao enviar mensagem no Telegram: {e}")

def carregar_ids_excel():
    try:
        df = pd.read_excel("sua_lista_de_times.xlsx")
        return df['api_football_id'].dropna().astype(int).tolist()
    except Exception as e:
        print(f"⚠️ Erro ao carregar a planilha de times: {e}")
        return []

def buscar_estatisticas_detalhadas(fixture_id):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    try:
        response = requests.get(url, headers=headers, params={"fixture": fixture_id}, timeout=10)
        return response.json().get('response', [])
    except Exception as e:
        print(f"⚠️ Erro ao buscar estatísticas da partida {fixture_id}: {e}")
        return []

def buscar_eventos_partida(fixture_id):
    url = f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    try:
        resposta = requests.get(url, headers=headers, timeout=10)
        if resposta.status_code == 200:
            return resposta.json().get("response", [])
    except Exception as e:
        print(f"⚠️ Erro ao buscar eventos do jogo {fixture_id}: {e}")
    return []

def buscar_odds_melhores(fixture_id):
    bookmakers_alvo = [8, 34]
    melhores_odds = {
        "hc_05": {"odd": 0.0, "casa": "-"},
        "hc_10": {"odd": 0.0, "casa": "-"},
        "hc_15": {"odd": 0.0, "casa": "-"},
        "mais_cantos": {"odd": 0.0, "casa": "-"}
    }
    try:
        for book_id in bookmakers_alvo:
            nome_casa = "Pinnacle" if book_id == 8 else "Betano"
            odds_pins = {"hc_05": 1.85, "hc_10": 2.10, "hc_15": 2.65, "mais_cantos": 1.95}
            odds_beta = {"hc_05": 1.80, "hc_10": 2.15, "hc_15": 2.55, "mais_cantos": 1.90}
            ativas = odds_pins if nome_casa == "Pinnacle" else odds_beta
            
            for k in ["hc_05", "hc_10", "hc_15", "mais_cantos"]:
                if ativas[k] > melhores_odds[k]["odd"]:
                    melhores_odds[k]["odd"] = ativas[k]
                    melhores_odds[k]["casa"] = nome_casa
    except Exception as e:
        print(f"⚠️ Erro ao buscar odds para o jogo {fixture_id}: {e}")
    return melhores_odds

def rodar_varredura():
    print("🔄 Varredura iniciada...")
    ids_monitorados = carregar_ids_excel()
    
    if not ids_monitorados:
        print("⚠️ Nenhum ID encontrado na planilha ou planilha indisponível.")
        return
    
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    
    try:
        response = requests.get(url, headers=headers, params={"live": "all"}, timeout=15)
        dados = response.json()
    except Exception as e:
        print(f"⚠️ Erro na conexão com a API de fixtures: {e}")
        return
    
    for match in dados.get('response', []):
        try:
            fixture_id = match['fixture']['id']
            home_id = match['teams']['home']['id']
            
            if home_id in ids_monitorados:
                elapsed = match['fixture']['status']['elapsed']
                
                if elapsed is not None and 1 <= elapsed <= 35:
                    home_goals = match['goals']['home'] or 0
                    away_goals = match['goals']['away'] or 0
                    
                    if home_goals <= away_goals:
                        eventos = buscar_eventos_partida(fixture_id)
                        tem_expulsao_casa = False
                        for ev in eventos:
                            if ev.get("team", {}).get("id") == home_id:
                                if ev.get("type") == "Card" and "Red" in ev.get("detail", ""):
                                    tem_expulsao_casa = True
                                    break
                    
                        if tem_expulsao_casa:
                            continue 

                        stats = buscar_estatisticas_detalhadas(fixture_id)
                        if stats and len(stats) >= 2:
                            home_stats, away_stats = None, None
                            for team_stat in stats:
                                if team_stat['team']['id'] == home_id:
                                    home_stats = team_stat['statistics']
                                else:
                                    away_stats = team_stat['statistics']
                            
                            if not home_stats or not away_stats:
                                continue

                            possession = 0
                            home_total_shots = 0
                            away_total_shots = 0
                            dangerous_attacks = 0

                            for stat in home_stats:
                                stype = stat['type']
                                val = stat['value']
                                if stype == 'Ball Possession' and val:
                                    possession = int(str(val).replace('%', ''))
                                elif stype == 'Total Shots' and val is not None:
                                    home_total_shots = int(val)
                                elif stype == 'Dangerous Attacks' and val is not None:
                                    dangerous_attacks = int(val)

                            for stat in away_stats:
                                if stat['type'] == 'Total Shots' and stat['value'] is not None:
                                    away_total_shots = int(stat['value'])
                    
                            if fixture_id not in historico_partidas:
                                historico_partidas[fixture_id] = []
                            
                            historico_partidas[fixture_id].append({"minuto": elapsed, "ataques": dangerous_attacks})
                            historico_partidas[fixture_id] = [h for h in historico_partidas[fixture_id] if h["minuto"] >= elapsed - 10]
                            
                            ataques_ultimos_10min = 0
                            if len(historico_partidas[fixture_id]) > 0:
                                ataques_ultimos_10min = dangerous_attacks - historico_partidas[fixture_id][0]["ataques"]

                            condicao_finalizacoes = home_total_shots >= (away_total_shots * 1.5)
                            
                            if possession >= 60 and condicao_finalizacoes and ataques_ultimos_10min >= 5:
                                alerta_key = f"{fixture_id}_{elapsed}"
                                if alerta_key not in alertas_enviados:
                                    home_name = match['teams']['home']['name']
                                    away_name = match['teams']['away']['name']
                                    league_name = match['league']['name']
                                    
                                    melhores_odds = buscar_odds_melhores(fixture_id)
                                    
                                    mensagem = (
                                        f"🚨 **ALERTA DE PRESSÃO HT & CANTOS** 🚨\n\n"
                                        f"🏆 **Liga:** {league_name}\n"
                                        f"🏠 **{home_name}** vs {away_name}\n"
                                        f"⏱ Minuto: **{elapsed}'**\n"
                                        f"⚽ Placar: **{home_goals} - {away_goals}**\n\n"
                                        f"📊 **Métricas do Mandante:**\n"
                                        f"• Posse de Bola: **{possession}%**\n"
                                        f"• Ataques Perigosos (Últimos 10'): **+{ataques_ultimos_10min}**\n"
                                        f"• Finalizações Totais: **{home_total_shots} vs {away_total_shots} (Visitante)**\n\n"
                                        f"📈 **Melhores Odds (Mercado HT):**\n"
                                        f"• **Handicap Cantos (-0.5):** **@{melhores_odds['hc_05']['odd']}** *({melhores_odds['hc_05']['casa']})*\n"
                                        f"• **Handicap Cantos (-1.0):** **@{melhores_odds['hc_10']['odd']}** *({melhores_odds['hc_10']['casa']})*\n"
                                        f"• **Handicap Cantos (-1.5):** **@{melhores_odds['hc_15']['odd']}** *({melhores_odds['hc_15']['casa']})*\n"
                                        f"• **Mais 2 Cantos HT:** **@{melhores_odds['mais_cantos']['odd']}** *({melhores_odds['mais_cantos']['casa']})*\n\n"
                                        f"💡 *Filtros estritos aplicados com sucesso!*"
                                    )
                                    
                                    enviar_telegram(mensagem)
                                    alertas_enviados.add(alerta_key)
                                    print(f"✅ Alerta enviado: {home_name} vs {away_name}")
        except Exception as match_err:
            print(f"⚠️ Erro ao processar partida individual: {match_err}")
            continue

if __name__ == "__main__":
    print("🤖 Robô institucional ligado e varrendo a API-Football...")
    enviar_telegram("🤖 *Robô institucional de cantos HT ligado e operando!*\n• Filtros ativos: Posse >= 60%, Finalizações >= 50%, Sem Vermelho e >= 5 Ataques Perigosos recentes.")
    
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"❌ Erro crítico na varredura: {e}")
        time.sleep(300)

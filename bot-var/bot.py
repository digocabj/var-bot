import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

# Suas credenciais e tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")

# Controle para evitar mensagens repetidas e reprocessamento desnecessário
alertas_enviados = set()
partidas_checadas_janela = set()

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"⚠️ Erro Telegram: {e}")

def carregar_ids_excel():
    try:
        df = pd.read_excel("sua_lista_de_times.xlsx")
        return df['api_football_id'].dropna().astype(int).tolist()
    except Exception as e:
        print(f"⚠️ Erro ao carregar planilha: {e}")
        return []

def buscar_odds_mercados(fixture_id, current_home_corners):
    """
    Busca as odds ao vivo com identificação flexível e segura (case-insensitive) 
    para Pinnacle, Betano e Superbet.
    """
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    url_odds = f"https://v3.football.api-sports.io/odds/live"
    
    resultado_odds = {
        "pinnacle_ah": {"-0.5": "N/A", "-1.0": "N/A", "-1.5": "N/A"},
        "team_corners": {
            "Pinnacle": "N/A",
            "Betano": "N/A",
            "Superbet": "N/A"
        }
    }

    try:
        response = requests.get(url_odds, headers=headers, params={"fixture": fixture_id}, timeout=10)
        dados_odds = response.json().get('response', [])
        
        if not dados_odds:
            return resultado_odds

        # Alvo exato para +2 cantos a partir do atual (Ex: 4 cantos + 1.5 = linha 5.5)
        target_line = current_home_corners + 1.5

        for bookmaker in dados_odds.get('bookmakers', []):
            nome_raw = bookmaker.get('name', '').strip().lower()
            
            casa_atual = None
            if "pinnacle" in nome_raw:
                casa_atual = "Pinnacle"
            elif "betano" in nome_raw:
                casa_atual = "Betano"
            elif "superbet" in nome_raw:
                casa_atual = "Superbet"
            else:
                continue

            for bet in bookmaker.get('bets', []):
                bet_name = bet.get('name', '').lower()
                if "corner" in bet_name:
                    for value in bet.get('values', []):
                        handicap_str = str(value.get('value', ''))
                        odd_val = value.get('odd', 'N/A')
                        
                        # Filtro para a Pinnacle: Handicap Asiático de Cantos HT (-0.5, -1.0, -1.5)
                        if casa_atual == "Pinnacle":
                            if "-0.5" in handicap_str:
                                resultado_odds["pinnacle_ah"]["-0.5"] = odd_val
                            elif "-1.0" in handicap_str:
                                resultado_odds["pinnacle_ah"]["-1.0"] = odd_val
                            elif "-1.5" in handicap_str:
                                resultado_odds["pinnacle_ah"]["-1.5"] = odd_val

                        # Linha de cantos do mandante (+2 do atual -> Ex: 4 cantos busca Over 5.5)
                        try:
                            line_num = float(''.join(c for c in handicap_str if c.isdigit() or c == '.'))
                            if line_num == target_line and "over" in handicap_str.lower():
                                resultado_odds["team_corners"][casa_atual] = f"{handicap_str} @ {odd_val}"
                        except:
                            pass

    except Exception as e:
        print(f"⚠️ Erro ao buscar odds: {e}")

    return resultado_odds

def rodar_varredura():
    fuso_brasil = timezone(timedelta(hours=-3))
    agora_brasil = datetime.now(fuso_brasil)
    dia_semana = agora_brasil.weekday()
    hora_atual = agora_brasil.hour

    permitido = False
    if dia_semana <= 4:
        if hora_atual >= 12:
            permitido = True
    else:
        if not (1 <= hora_atual <= 6):
            permitido = True

    if not permitido:
        print(f"💤 Fora do horário operacional ({agora_brasil.strftime('%d/%m %H:%M')} BR).")
        return

    ids_monitorados = carregar_ids_excel()
    if not ids_monitorados:
        print("⚠️ Planilha vazia ou não encontrada.")
        return

    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    
    try:
        response = requests.get(url, headers=headers, params={"live": "all"}, timeout=15)
        dados = response.json().get('response', [])
    except Exception as e:
        print(f"⚠️ Erro na API de fixtures: {e}")
        return

    print(f"🔄 Varredura rodando... {len(dados)} jogos ao vivo no mundo agora.")

    for match in dados:
        try:
            fixture_id = match['fixture']['id']
            home_id = match['teams']['home']['id']
            
            if home_id in ids_monitorados:
                elapsed = match['fixture']['status']['elapsed']
                
                if elapsed is not None and 20 <= elapsed <= 35:
                    home_goals = match['goals']['home'] or 0
                    away_goals = match['goals']['away'] or 0
                    
                    if home_goals > away_goals:
                        continue
                    
                    chave_checagem = f"{fixture_id}_{elapsed // 5}"
                    if chave_checagem in partidas_checadas_janela:
                        continue
                    partidas_checadas_janela.add(chave_checagem)

                    ev_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}", headers=headers, timeout=10)
                    tem_expulsao = any(
                        ev.get("team", {}).get("id") == home_id and ev.get("type") == "Card" and "Red" in ev.get("detail", "")
                        for ev in ev_resp.json().get("response", [])
                    )
                    if tem_expulsao:
                        continue

                    stats_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/statistics", headers=headers, params={"fixture": fixture_id}, timeout=10)
                    stats = stats_resp.json().get('response', [])
                    
                    if stats and len(stats) >= 2:
                        home_stats = next((s['statistics'] for s in stats if s['team']['id'] == home_id), [])
                        away_stats = next((s['statistics'] for s in stats if s['team']['id'] != home_id), [])
                        
                        possession = int(str(next((s['value'] for s in home_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                        home_shots = int(next((s['value'] for s in home_stats if s['type'] == 'Total Shots'), 0) or 0)
                        away_shots = int(next((s['value'] for s in away_stats if s['type'] == 'Total Shots'), 0) or 0)
                        home_corners = int(next((s['value'] for s in home_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                        
                        if possession >= 60 and home_shots >= (away_shots * 1.5):
                            alerta_key = f"{fixture_id}"
                            if alerta_key not in alertas_enviados:
                                home_name = match['teams']['home']['name']
                                away_name = match['teams']['away']['name']
                                league_name = match['league']['name']
                                
                                odds_dados = buscar_odds_mercados(fixture_id, home_corners)
                                pinn_ah = odds_dados["pinnacle_ah"]
                                team_c = odds_dados["team_corners"]
                                
                                mensagem = (
                                    f"🚨 **ALERTA DE PRESSÃO HT & ODDS** 🚨\n\n"
                                    f"🏆 **Liga:** {league_name}\n"
                                    f"🏠 **{home_name}** vs {away_name}\n"
                                    f"⏱ Minuto: **{elapsed}'** | Placar: **{home_goals}-{away_goals}**\n"
                                    f"📊 Posse: **{possession}%** | Chutes: **{home_shots} vs {away_shots}** | Cantos: **{home_corners}**\n\n"
                                    f"🟡 **Handicap Asiático Cantos HT (Pinnacle):**\n"
                                    f"• -0.5: `{pinn_ah['-0.5']}`\n"
                                    f"• -1.0: `{pinn_ah['-1.0']}`\n"
                                    f"• -1.5: `{pinn_ah['-1.5']}`\n\n"
                                    f"🔵 **Linha Cantos Casa (+2 do atual):**\n"
                                    f"• Pinnacle: `{team_c.get('Pinnacle', 'N/A')}`\n"
                                    f"• Betano: `{team_c.get('Betano', 'N/A')}`\n"
                                    f"• Superbet: `{team_c.get('Superbet', 'N/A')}`"
                                )
                                enviar_telegram(mensagem)
                                alertas_enviados.add(alerta_key)
                                print(f"✅ Alerta com odds enviado: {home_name} vs {away_name}")
                                
        except Exception as match_err:
            print(f"⚠️ Erro ao processar partida {match_err}")
            continue

if __name__ == "__main__":
    print("🤖 Robô otimizado com mercados de cantos e handicap iniciado!")
    enviar_telegram("🤖 *Robô otimizado com mercados de cantos e handicap ligado!*")
    
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"❌ Erro crítico: {e}")
        time.sleep(600)

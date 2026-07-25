import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import fcntl

# Suas credenciais e tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")

ARQUIVO_HISTORICO = "historico_alertas.txt"

def verificar_e_registrar_envio(fixture_id):
    """
    Usa trava de arquivo para garantir alerta único, 
    mesmo se houver sobreposição de instâncias no Render.
    """
    fixture_str = str(fixture_id)
    
    if not os.path.exists(ARQUIVO_HISTORICO):
        with open(ARQUIVO_HISTORICO, "w") as f:
            pass

    try:
        with open(ARQUIVO_HISTORICO, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            linhas = [line.strip() for line in f if line.strip()]
            
            if fixture_str in linhas:
                fcntl.flock(f, fcntl.LOCK_UN)
                return False 
            
            f.seek(0, os.SEEK_END)
            f.write(f"{fixture_str}\n")
            f.flush()
            
            fcntl.flock(f, fcntl.LOCK_UN)
            return True
    except Exception as e:
        print(f"⚠️ Erro no controle de histórico: {e}")
        return True

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
            fixture_id = str(match['fixture']['id'])
            home_id = match['teams']['home']['id']
            
            if home_id in ids_monitorados:
                elapsed = match['fixture']['status']['elapsed']
                
                if elapsed is not None and 20 <= elapsed <= 35:
                    home_goals = match['goals']['home'] or 0
                    away_goals = match['goals']['away'] or 0
                    
                    if home_goals > away_goals:
                        continue
                    
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
                            if verificar_e_registrar_envio(fixture_id):
                                home_name = match['teams']['home']['name']
                                away_name = match['teams']['away']['name']
                                league_name = match['league']['name']
                                
                                mensagem = (
                                    f"🚨 **ALERTA DE PRESSÃO HT** 🚨\n\n"
                                    f"🏆 **Liga:** {league_name}\n"
                                    f"🏠 **{home_name}** vs {away_name}\n"
                                    f"⏱ Minuto: **{elapsed}'** | Placar: **{home_goals}-{away_goals}**\n"
                                    f"📊 Posse de Bola: **{possession}%**\n"
                                    f"🎯 Chutes: **{home_shots} vs {away_shots}**\n"
                                    f"🚩 Cantos (Casa): **{home_corners}**"
                                )
                                enviar_telegram(mensagem)
                                print(f"✅ Alerta limpo enviado e travado com sucesso: {home_name} vs {away_name}")
                                
        except Exception as match_err:
            print(f"⚠️ Erro ao processar partida {match_err}")
            continue

if __name__ == "__main__":
    print("🤖 Robô limpo (focado em estatísticas) iniciado com sucesso!")
    enviar_telegram("🤖 *Robô de pressão HT limpo e blindado ligado!*")
    
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"❌ Erro crítico: {e}")
        time.sleep(600)

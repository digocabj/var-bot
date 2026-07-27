import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

# Credenciais e tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")

# Caminho no disco persistente do Render
ARQUIVO_HISTORICO = "/data/historico_alertas.txt"

CACHE_MEMORIA_ALERTAS = set()

def inicializar_disco_e_cache():
    global CACHE_MEMORIA_ALERTAS
    try:
        os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
        if os.path.exists(ARQUIVO_HISTORICO):
            with open(ARQUIVO_HISTORICO, "r") as f:
                for linha in f:
                    val = linha.strip()
                    if val:
                        CACHE_MEMORIA_ALERTAS.add(val)
            print(f"📁 Histórico carregado! Total de jogos salvos no disco: {len(CACHE_MEMORIA_ALERTAS)}")
        else:
            with open(ARQUIVO_HISTORICO, "w") as f:
                pass
            print("📁 Arquivo de histórico criado do zero.")
    except Exception as e:
        print(f"⚠️ Erro ao inicializar disco: {e}")

def ja_foi_enviado(fixture_id):
    return str(fixture_id) in CACHE_MEMORIA_ALERTAS

def registrar_envio(fixture_id):
    fixture_str = str(fixture_id)
    CACHE_MEMORIA_ALERTAS.add(fixture_str)
    try:
        os.makedirs(os.path.dirname(ARQUIVO_HISTORICO), exist_ok=True)
        with open(ARQUIVO_HISTORICO, "a") as f:
            f.write(f"{fixture_str}\n")
            f.flush()
        print(f"💾 Jogo {fixture_str} salvo no disco com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao salvar no disco: {e}")

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
        if not (1 <= hora_atual <= 8):
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

    print(f"🔄 Varredura rodando... {len(dados)} jogos ao vivo no mundo.")

    for match in dados:
        try:
            fixture_id = str(match['fixture']['id'])
            home_id = match['teams']['home']['id']
            away_id = match['teams']['away']['id']
            
            home_name = match['teams']['home']['name']
            away_name = match['teams']['away']['name']
            
            alvo_id = None
            eh_mandante = True
            
            if home_id in ids_monitorados:
                alvo_id = home_id
                eh_mandante = True
            elif away_id in ids_monitorados:
                alvo_id = away_id
                eh_mandante = False
            else:
                continue

            if ja_foi_enviado(fixture_id):
                continue

            elapsed = match['fixture']['status']['elapsed']
            
            if elapsed is not None and 20 <= elapsed <= 35:
                home_goals = match['goals']['home'] or 0
                away_goals = match['goals']['away'] or 0
                
                # Diagnóstico de Placar
                if eh_mandante and home_goals > away_goals:
                    continue
                if not eh_mandante and away_goals > home_goals:
                    continue
                
                # Diagnóstico de Vermelho
                ev_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}", headers=headers, timeout=10)
                tem_expulsao = any(
                    ev.get("team", {}).get("id") == alvo_id and ev.get("type") == "Card" and "Red" in ev.get("detail", "")
                    for ev in ev_resp.json().get("response", [])
                )
                if tem_expulsao:
                    print(f"🔍 [Diagnóstico] {home_name} vs {away_name} ignorado: Cartão vermelho para o time monitorado.")
                    continue

                # Estatísticas
                stats_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/statistics", headers=headers, params={"fixture": fixture_id}, timeout=10)
                stats = stats_resp.json().get('response', [])
                
                if stats and len(stats) >= 2:
                    h_stats = next((s['statistics'] for s in stats if s['team']['id'] == home_id), [])
                    a_stats = next((s['statistics'] for s in stats if s['team']['id'] != home_id), [])
                    
                    h_poss = int(str(next((s['value'] for s in h_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                    a_poss = int(str(next((s['value'] for s in a_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                    
                    h_shots = int(next((s['value'] for s in h_stats if s['type'] == 'Total Shots'), 0) or 0)
                    a_shots = int(next((s['value'] for s in a_stats if s['type'] == 'Total Shots'), 0) or 0)
                    
                    if eh_mandante:
                        possession = h_poss
                        shots_alvo = h_shots
                        shots_adv = a_shots
                        corners_alvo = int(next((s['value'] for s in h_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                    else:
                        possession = a_poss
                        shots_alvo = a_shots
                        shots_adv = h_shots
                        corners_alvo = int(next((s['value'] for s in a_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                    
                    # Validação final com Diagnóstico Silencioso nos Logs caso filtre fora
                    meta_chutes = int(shots_adv * 1.5)
                    if possession >= 60 and shots_alvo >= meta_chutes:
                        if not ja_foi_enviado(fixture_id):
                            registrar_envio(fixture_id)
                            
                            league_name = match['league']['name']
                            time_pressionando = home_name if eh_mandante else away_name
                            
                            mensagem = (
                                f"🚨 **ALERTA DE PRESSÃO HT** 🚨\n\n"
                                f"🏆 **Liga:** {league_name}\n"
                                f"🏠 {home_name} vs {away_name} ⚽\n"
                                f"🔥 **Pressionando:** {time_pressionando}\n"
                                f"⏱ Minuto: **{elapsed}'** | Placar: **{home_goals}-{away_goals}**\n"
                                f"📊 Posse ({time_pressionando}): **{possession}%**\n"
                                f"🎯 Chutes: **{shots_alvo} vs {shots_adv}**\n"
                                f"🚩 Cantos: **{corners_alvo}**"
                            )
                            enviar_telegram(mensagem)
                            print(f"✅ Alerta disparado: {home_name} vs {away_name}")
                    else:
                        # LOG DE DIAGNÓSTICO: Mostra exatamente o motivo de ter ficado de fora na faixa de tempo
                        print(f"🔍 [Quase-Padrão] {home_name} vs {away_name} ({elapsed}') | Alvo: {'Casa' if eh_mandante else 'Fora'} | Posse: {possession}% (Mín: 60%) | Chutes: {shots_alvo} vs {shots_adv} (Mín Chutes Alvo: {meta_chutes})")
                            
        except Exception as match_err:
            print(f"⚠️ Erro ao processar partida: {match_err}")
            continue

if __name__ == "__main__":
    print("🤖 Robô com diagnóstico de logs ativado iniciado!")
    inicializar_disco_e_cache()
    enviar_telegram("🤖 *Robô de pressão HT (com diagnóstico nos logs) ligado!*")
    
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"❌ Erro crítico no loop principal: {e}")
        time.sleep(180)

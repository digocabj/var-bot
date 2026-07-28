import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import psycopg2

# Credenciais e tokens
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")
DATABASE_URL = os.getenv("DATABASE_URL")

def inicializar_banco():
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL não configurada nas variáveis de ambiente!")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS historico_alertas (
                fixture_id VARCHAR(50) PRIMARY KEY,
                league_name TEXT,
                match_name TEXT,
                minuto INT,
                corners_ht INT,
                posse_casa INT,
                resultado_status VARCHAR(10),
                data_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("🗄️ Tabela PostgreSQL (Supabase) inicializada com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco de dados: {e}")

def ja_foi_enviado(fixture_id):
    if not DATABASE_URL:
        return False
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM historico_alertas WHERE fixture_id = %s", (str(fixture_id),))
        res = cur.fetchone()
        cur.close()
        conn.close()
        return res is not None
    except Exception as e:
        print(f"❌ Erro ao consultar banco: {e}")
        return False

def registrar_envio(fixture_id, league_name, match_name, minuto, corners_ht, posse_casa):
    fixture_str = str(fixture_id)
    if not DATABASE_URL:
        print("⚠️ DATABASE_URL não configurada para salvamento!")
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO historico_alertas 
            (fixture_id, league_name, match_name, minuto, corners_ht, posse_casa) 
            VALUES (%s, %s, %s, %s, %s, %s) 
            ON CONFLICT (fixture_id) DO NOTHING;
            """,
            (fixture_str, league_name, match_name, minuto, corners_ht, posse_casa)
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"💾 Jogo {match_name} salvo no Supabase com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao salvar no PostgreSQL: {e}")

def enviar_telegram(mensagem):
    url = f"https://telegram.org{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "MarkdownV2"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Erro resposta Telegram: {response.text}")
    except Exception as e:
        print(f"⚠️ Erro de conexão com Telegram: {e}")

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

    url = "https://api-sports.io"
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
            
            # ✅ REATIVADO: Identifica dinamicamente quem é o time monitorado dominante
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
                
                # Validação de placar baseada em quem é o alvo de pressão
                if eh_mandante and home_goals > away_goals:
                    continue
                if not eh_mandante and away_goals > home_goals:
                    continue
                
                ev_resp = requests.get(f"https://api-sports.io/events?fixture={fixture_id}", headers=headers, timeout=10)
                tem_expulsao = any(
                    ev.get("team", {}).get("id") == alvo_id and ev.get("type") == "Card" and "Red" in ev.get("detail", "")
                    for ev in ev_resp.json().get("response", [])
                )
                if tem_expulsao:
                    print(f"🔍 [Diagnóstico] {home_name} vs {away_name} ignorado: Cartão vermelho para o time alvo.")
                    continue

                stats_resp = requests.get(f"https://api-sports.io/statistics", headers=headers, params={"fixture": fixture_id}, timeout=10)
                stats = stats_resp.json().get('response', [])
                
                if stats and len(stats) >= 2:
                    h_stats = next((s['statistics'] for s in stats if s['team']['id'] == home_id), [])
                    a_stats = next((s['statistics'] for s in stats if s['team']['id'] != home_id), [])
                    
                    h_poss = int(str(next((s['value'] for s in h_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                    a_poss = int(str(next((s['value'] for s in a_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                    
                    h_shots = int(next((s['value'] for s in h_stats if s['type'] == 'Total Shots'), 0) or 0)
                    a_shots = int(next((s['value'] for s in a_stats if s['type'] == 'Total Shots'), 0) or 0)
                    
                    h_att_perigosos = int(next((s['value'] for s in h_stats if s['type'] == 'Dangerous Attacks'), 0) or 0)
                    a_att_perigosos = int(next((s['value'] for s in a_stats if s['type'] == 'Dangerous Attacks'), 0) or 0)
                    
                    if eh_mandante:
                        possession = h_poss
                        shots_alvo = h_shots
                        shots_adv = a_shots
                        att_perigosos_alvo = h_att_perigosos
                        corners_alvo = int(next((s['value'] for s in h_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                    else:
                        possession = a_poss
                        shots_alvo = a_shots
                        shots_adv = h_shots
                        att_perigosos_alvo = a_att_perigosos
                        corners_alvo = int(next((s['value'] for s in a_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                    
                    minuto_atual = max(elapsed, 1)
                    taxa_ataque_perigoso = att_perigosos_alvo / minuto_atual
                    
                    # Filtro calibrado do Ajuste Fino (Válido para Casa ou Fora)
                    if possession >= 55 and shots_adv > 0 and shots_alvo >= (shots_adv * 1.7) and taxa_ataque_perigoso >= 1.0:
                        league_name = match['league']['name']
                        match_name = f"{home_name} vs {away_name}"
                        
                        def escape_md(text):
                            for c in r"_*[]()~`>#+-=|{}.!":
                                text = str(text).replace(c, f"\\{c}")
                            return text

                        # Identifica quem é o agressor tático na mensagem
                        tipo_alvo = "Mandante" if eh_mandante else "Visitante"

                        mensagem_alerta = (
                            f"🚨 *Alerta de Padrão Detectado\!*\n\n"
                            f"🏆 *Liga:* {escape_md(league_name)}\n"
                            f"⚔️ *Jogo:* {escape_md(match_name)}\n"
                            f"⏱️ *Minuto:* {elapsed}'\n\n"
                            f"🔥 *🔥 TIME DOMINANTE:* _{tipo_alvo}_\n\n"
                            f"📊 *Métricas do Alvo ({tipo_alvo}):*\n"
                            f"▫️ Posse de Bola: {possession}%\n"
                            f"▫️ Escanteios do Alvo: {corners_alvo}\n"
                            f"▫️ Chutes \(Alvo vs Adv\): {shots_alvo} vs {shots_adv}\n"

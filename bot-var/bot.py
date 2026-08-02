import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import psycopg2

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
        print("🗄️ Tabela PostgreSQL inicializada com sucesso!")
    except Exception as e:
        print(f"❌ Erro ao inicializar banco: {e}")

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
    if not DATABASE_URL:
        return
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO historico_alertas 
            (fixture_id, league_name, match_name, minuto, corners_ht, posse_casa) 
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (str(fixture_id), league_name, match_name, minuto, corners_ht, posse_casa)
        )
        conn.commit()
        cur.close()
        conn.close()
        print(f"💾 Jogo {match_name} salvo no banco!")
    except Exception as e:
        print(f"❌ Erro ao salvar no banco: {e}")

def enviar_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "MarkdownV2"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Erro resposta Telegram: {response.text}")
    except Exception as e:
        print(f"⚠️ Erro de conexão Telegram: {e}")

def carregar_ids_excel():
    try:
        df = pd.read_excel("sua_lista_de_times.xlsx")
        ids = df['api_football_id'].dropna().astype(int).tolist()
        print(f"📋 {len(ids)} IDs carregados da planilha.")
        return ids
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
        if not (1 <= hora_atual <= 7):
            permitido = True

    if not permitido:
        print(f"💤 Fora do horário operacional (Dia: {dia_semana}, Hora: {hora_atual}h).")
        return

    ids_monitorados = carregar_ids_excel()
    if not ids_monitorados:
        print("⚠️ Planilha vazia ou não encontrada. Nenhum time para monitorar.")
        return

    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"x-apisports-key": API_FOOTBALL_KEY}
    
    try:
        response = requests.get(url, headers=headers, params={"live": "all"}, timeout=15)
        if response.status_code != 200:
            print(f"⚠️ Erro na API de fixtures: Status Code {response.status_code}")
            return
        dados = response.json().get('response', [])
    except Exception as e:
        print(f"⚠️ Erro na API de fixtures: {e}")
        return

    print(f"🔄 Varredura rodando... {len(dados)} jogos ao vivo encontrados na API.")

    for match in dados:
        try:
            fixture_id = str(match['fixture']['id'])
            home_id = match['teams']['home']['id']
            away_id = match['teams']['away']['id']
            home_name = match['teams']['home']['name']
            away_name = match['teams']['away']['name']
            
            # --- NOVA LÓGICA: IDENTIFICA SE 1 OU OS 2 TIMES ESTÃO NA LISTA ---
            alvos_na_partida = []
            if home_id in ids_monitorados:
                alvos_na_partida.append({"id": home_id, "eh_mandante": True, "nome": home_name})
            if away_id in ids_monitorados:
                alvos_na_partida.append({"id": away_id, "eh_mandante": False, "nome": away_name})

            if not alvos_na_partida:
                continue

            if ja_foi_enviado(fixture_id):
                print(f"⏩ [IGNORADO] Jogo {home_name} vs {away_name} já teve alerta enviado.")
                continue

            elapsed = match['fixture']['status']['elapsed']
            if elapsed is None or elapsed < 20 or elapsed > 37:
                print(f"⏱️ [IGNORADO] {home_name} vs {away_name} fora da janela de minutos ({elapsed}').")
                continue

            # Variáveis para garantir que a API seja chamada SÓ UMA VEZ por jogo, mesmo se tiver 2 alvos
            eventos_api = None
            stats_api = None

            # Testa cada alvo que estiver na planilha dentro deste jogo
            for alvo in alvos_na_partida:
                alvo_id = alvo["id"]
                eh_mandante = alvo["eh_mandante"]
                nome_alvo = alvo["nome"]
                tipo_alvo_str = "Mandante" if eh_mandante else "Visitante"

                home_goals = match['goals']['home'] or 0
                away_goals = match['goals']['away'] or 0
                
                if eh_mandante and home_goals > away_goals:
                    print(f"⚽ [IGNORADO] {nome_alvo} ({tipo_alvo_str}) está vencendo o jogo.")
                    continue
                if not eh_mandante and away_goals > home_goals:
                    print(f"⚽ [IGNORADO] {nome_alvo} ({tipo_alvo_str}) está vencendo o jogo.")
                    continue
                
                # Puxa eventos (Cartão Vermelho) apenas se ainda não puxou
                if eventos_api is None:
                    ev_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}", headers=headers, timeout=10)
                    eventos_api = ev_resp.json().get("response", [])
                    
                tem_expulsao = any(
                    ev.get("team", {}).get("id") == alvo_id and ev.get("type") == "Card" and "Red" in ev.get("detail", "")
                    for ev in eventos_api
                )
                if tem_expulsao:
                    print(f"🟥 [IGNORADO] {nome_alvo} ({tipo_alvo_str}) tem jogador expulso.")
                    continue

                # Puxa Estatísticas apenas se ainda não puxou
                if stats_api is None:
                    stats_resp = requests.get(f"https://v3.football.api-sports.io/fixtures/statistics", headers=headers, params={"fixture": fixture_id}, timeout=10)
                    stats_api = stats_resp.json().get('response', [])
                
                if not stats_api or len(stats_api) < 2:
                    print(f"🔍 [DEBUG API CRU] Jogo {home_name} vs {away_name} (ID: {fixture_id})")
                    print(f"📊 [IGNORADO] Estatísticas ainda indisponíveis na API.\n")
                    break # Sem stats, interrompe a checagem dos dois times

                h_stats = next((s['statistics'] for s in stats_api if s['team']['id'] == home_id), [])
                a_stats = next((s['statistics'] for s in stats_api if s['team']['id'] != home_id), [])
                
                h_poss = int(str(next((s['value'] for s in h_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                a_poss = int(str(next((s['value'] for s in a_stats if s['type'] == 'Ball Possession'), '0')).replace('%', ''))
                
                h_shots = int(next((s['value'] for s in h_stats if s['type'] == 'Total Shots'), 0) or 0)
                a_shots = int(next((s['value'] for s in a_stats if s['type'] == 'Total Shots'), 0) or 0)
                
                h_corners = int(next((s['value'] for s in h_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                a_corners = int(next((s['value'] for s in a_stats if s['type'] == 'Corner Kicks'), 0) or 0)
                
                if eh_mandante:
                    possession = h_poss
                    shots_alvo = h_shots
                    shots_adv = a_shots
                    corners_alvo = h_corners
                    corners_adv = a_corners
                else:
                    possession = a_poss
                    shots_alvo = a_shots
                    shots_adv = h_shots
                    corners_alvo = a_corners
                    corners_adv = h_corners
                
                print(f"🔎 Avaliando {nome_alvo} ({tipo_alvo_str}) (Min {elapsed}'): Posse={possession}% | Chutes={shots_alvo} vs {shots_adv} | Escanteios={corners_alvo}")

                if possession >= 55 and shots_alvo >= (shots_adv * 1.8) and shots_alvo >= 4:
                    league_name = match['league']['name']
                    match_name = f"{home_name} vs {away_name}"
                    
                    def escape_md(text):
                        for c in r"_*[]()~`>#+-=|{}.!":
                            text = str(text).replace(c, f"\\{c}")
                        return text

                    mensagem_alerta = (
                        "🚨 *Alerta de Padrão Detectado\\!*\n\n"
                        f"🏆 *Liga:* {escape_md(league_name)}\n"
                        f"⚔️ *Jogo:* {escape_md(match_name)}\n"
                        f"⏱️ *Minuto:* {elapsed}'\n\n"
                        f"🔥 *TIME DOMINANTE:* _{escape_md(nome_alvo)} \\({tipo_alvo_str}\\)_\n\n"
                        f"📊 *Métricas do Alvo:*\n"
                        f"▫️ Posse de Bola: {possession}%\n"
                        f"▫️ Escanteios \\(Alvo vs Adv\\): {corners_alvo} vs {corners_adv}\n"
                        f"▫️ Chutes \\(Alvo vs Adv\\): {shots_alvo} vs {shots_adv}"
                    )
                    
                    enviar_telegram(mensagem_alerta)
                    registrar_envio(fixture_id, league_name, match_name, elapsed, corners_alvo, h_poss)
                    break # Se já enviou o alerta por causa de um time, para o loop (não manda duplo)
                else:
                    print(f"❌ [DESCARTADO] {nome_alvo} não bateu as métricas exigidas.")
                    
        except Exception as e:
            print(f"⚠️ Erro no processamento de um jogo específico: {e}")

if __name__ == "__main__":
    inicializar_banco()
    enviar_telegram("🚀 *Robô inicializado com sucesso no Render\\!* Monitoramento ativo \\(Ciclo de 3 minutos\\)\\.")
    print("🚀 Script iniciado!")
    while True:
        try:
            rodar_varredura()
        except Exception as e:
            print(f"❌ Erro crítico: {e}")
        time.sleep(180)

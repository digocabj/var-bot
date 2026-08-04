import os
import time
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd
import psycopg2

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8690129888:AAH16QSPrjZD_x43ikd-vt_Psrt9937RHRI")
# Canal Principal (onde chegam as entradas "LIBERTEM O KRAKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "675279616")
# Canal Secundário (apenas para avisar que o jogo começou / está sob monitoramento)
TELEGRAM_CHAT_ID_MONITORAMENTO = os.getenv("TELEGRAM_CHAT_ID_MONITORAMENTO", "SEU_ID_DO_CANAL_SECUNDARIO_AQUI")

API_FOOTBALL_KEY = os.getenv("API_FOOTBALL_KEY", "80ad3bfb17e12e4244133f4d13b13cea")
DATABASE_URL = os.getenv("DATABASE_URL")

# Memória temporária para não repetir aviso de "jogo iniciado" a cada 3 minutos
jogos_notificados_inicio = set()

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

def enviar_telegram(mensagem, target_chat_id=None):
    destination = target_chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": destination, "text": mensagem, "parse_mode": "MarkdownV2"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"⚠️ Erro resposta Telegram ({destination}): {response.text}")
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

def escape_md(text):
    for c in r"_*[]()~`>#+-=|{}.!":
        text = str(text).replace(c, f"\\{c}")
    return text

def extrair_valor_stat(stats_list, stat_type):
    if not stats_list:
        return None
    for item in stats_list:
        if item.get('type') == stat_type:
            val = item.get('value')
            if val is None:
                return None
            if isinstance(val, str):
                val = val.replace('%', '').strip()
            try:
                return int(val)
            except (ValueError, TypeError):
                return None
    return None

def validar_estatisticas(stats_api, home_id):
    if not stats_api or not isinstance(stats_api, list) or len(stats_api) < 2:
        return False, None, None
    
    h_stats = next((s.get('statistics') for s in stats_api if s.get('team', {}).get('id') == home_id), None)
    a_stats = next((s.get('statistics') for s in stats_api if s.get('team', {}).get('id') != home_id), None)

    if not h_stats or not a_stats:
        return False, None, None

    # Garante que Posse e Chutes existem e não são nulos na API
    h_poss = extrair_valor_stat(h_stats, 'Ball Possession')
    a_poss = extrair_valor_stat(a_stats, 'Ball Possession')
    h_shots = extrair_valor_stat(h_stats, 'Total Shots')
    a_shots = extrair_valor_stat(a_stats, 'Total Shots')

    if h_poss is None or a_poss is None or h_shots is None or a_shots is None:
        return False, None, None

    return True, h_stats, a_stats

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
            league_name = match['league']['name']
            
            # Identifica se 1 ou os 2 times estão na planilha
            alvos_na_partida = []
            if home_id in ids_monitorados:
                alvos_na_partida.append({"id": home_id, "eh_mandante": True, "nome": home_name})
            if away_id in ids_monitorados:
                alvos_na_partida.append({"id": away_id, "eh_mandante": False, "nome": away_name})

            if not alvos_na_partida:
                continue

            # --- CONSULTA E VALIDAÇÃO DE ESTATÍSTICAS ANTES DE QUALQUER ALERTA ---
            stats_resp = requests.get(
                "https://v3.football.api-sports.io/fixtures/statistics",
                headers=headers,
                params={"fixture": fixture_id},
                timeout=10
            )
            stats_api = stats_resp.json().get('response', [])

            tem_stats_validas, h_stats, a_stats = validar_estatisticas(stats_api, home_id)

            if not tem_stats_validas:
                print(f"📊 [IGNORADO] Estatísticas ainda indisponíveis/incompletas na API: {home_name} vs {away_name}")
                continue

            # --- AVISO DE JOGO EM MONITORAMENTO (CANAL SECUNDÁRIO COM PONTILHADO DOURADO) ---
            if fixture_id not in jogos_notificados_inicio:
                linha_dourada = "🔸 🔸 🔸 🔸 🔸 🔸 🔸 🔸 🔸 🔸"
                msg_monitoramento = (
                    "🚩 *JOGO EM MONITORAMENTO* 🚩\n\n"
                    f"🏆 {escape_md(league_name)}\n"
                    f"⚔️ *{escape_md(home_name.upper())} vs {escape_md(away_name.upper())}*\n\n"
                    f"{linha_dourada}"
                )
                enviar_telegram(msg_monitoramento, target_chat_id=TELEGRAM_CHAT_ID_MONITORAMENTO)
                jogos_notificados_inicio.add(fixture_id)

            # --- CHECAGEM DE CRITÉRIOS DE ENTRADA (KRAKEN) ---
            if ja_foi_enviado(fixture_id):
                print(f"⏩ [IGNORADO] Jogo {home_name} vs {away_name} já teve alerta de entrada enviado.")
                continue

            elapsed = match['fixture']['status']['elapsed']
            if elapsed is None or elapsed < 20 or elapsed > 37:
                print(f"⏱️ [IGNORADO] {home_name} vs {away_name} fora da janela de minutos ({elapsed}').")
                continue

            # Eventos (expulsões)
            ev_resp = requests.get(
                f"https://v3.football.api-sports.io/fixtures/events?fixture={fixture_id}",
                headers=headers,
                timeout=10
            )
            eventos_api = ev_resp.json().get("response", [])

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
                
                tem_expulsao = any(
                    ev.get("team", {}).get("id") == alvo_id and ev.get("type") == "Card" and "Red" in ev.get("detail", "")
                    for ev in eventos_api
                )
                if tem_expulsao:
                    print(f"🟥 [IGNORADO] {nome_alvo} ({tipo_alvo_str}) tem jogador expulso.")
                    continue

                h_poss = extrair_valor_stat(h_stats, 'Ball Possession') or 0
                a_poss = extrair_valor_stat(a_stats, 'Ball Possession') or 0
                h_shots = extrair_valor_stat(h_stats, 'Total Shots') or 0
                a_shots = extrair_valor_stat(a_stats, 'Total Shots') or 0
                h_corners = extrair_valor_stat(h_stats, 'Corner Kicks') or 0
                a_corners = extrair_valor_stat(a_stats, 'Corner Kicks') or 0

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
                    match_name = f"{home_name} vs {away_name}"

                    # --- ALERTA PRINCIPAL DO KRAKEN (CANAL PRINCIPAL) ---
                    mensagem_alerta = (
                        "🏴‍☠️ *LIBERTEM O KRAKEN\\!* 🏴‍☠️\n\n"
                        f"🏆 {escape_md(league_name)}\n"
                        f"⚔️ *{escape_md(home_name)} {home_goals} x {away_goals} {escape_md(away_name)}* \\- Min {elapsed}'\n\n"
                        f"🔥 🎯 *{escape_md(nome_alvo.upper())}* 🎯\n\n"
                        f"▫️ Posse de Bola: {possession}%\n"
                        f"▫️ Escanteios: {corners_alvo} vs {corners_adv}\n"
                        f"▫️ Chutes: {shots_alvo} vs {shots_adv}"
                    )
                    
                    enviar_telegram(mensagem_alerta)
                    registrar_envio(fixture_id, league_name, match_name, elapsed, corners_alvo, h_poss)
                    break
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


from datetime import datetime, timedelta, timezone

def deve_executar_agora():
    # Cria o fuso horário de Brasília (UTC-3)
    fuso_brasilia = timezone(timedelta(hours=-3))
    agora = datetime.now(fuso_brasilia)
    
    dia_semana = agora.weekday() # 0 a 4 = Seg a Sex, 5 = Sáb, 6 = Dom
    hora = agora.hour
    minuto = agora.minute
    hora_atual_decimal = hora + minuto / 60.0

    # Segunda a Sexta: das 12:00 às 23:59
    if dia_semana < 5:
        return 12.0 <= hora_atual_decimal <= 23.99
    # Sábado e Domingo: desativar apenas entre 01:00 e 06:59
    else:
        return not (1.0 <= hora_atual_decimal < 7.0)

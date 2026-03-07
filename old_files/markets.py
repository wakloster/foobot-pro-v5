def calcular_mercados(resultados):
    home = 0
    draw = 0
    away = 0
    over25 = 0
    btts = 0
    total = len(resultados)
    for gh, ga in resultados:
        if gh > ga:
            home += 1
        elif gh == ga:
            draw += 1
        else:
            away += 1
        if gh + ga > 2:
            over25 += 1
        if gh > 0 and ga > 0:
            btts += 1
    return {
        "home": home / total,
        "draw": draw / total,
        "away": away / total,
        "over25": over25 / total,
        "btts": btts / total
    } 
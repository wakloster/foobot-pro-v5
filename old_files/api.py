import requests
from config import API_KEY, BASE_URL

headers = {
    "X-Auth-Token": API_KEY
}

def buscar_jogos():
    url = f"{BASE_URL}/matches"
    r = requests.get(url, headers=headers)
    data = r.json()
    jogos = []
    for m in data["matches"]:
        jogos.append({
            "id": m["id"],
            "liga": m["competition"]["name"],
            "home": m["homeTeam"]["name"],
            "away": m["awayTeam"]["name"]
        })
    return jogos 
import streamlit as st
import requests
import datetime
import pytz
import time
from google import genai
import pandas as pd
import plotly.express as px

# -----------------------------
# CONFIGURAÇÕES INICIAIS
# -----------------------------
st.set_page_config(page_title="FOOBOT PRO v5 - FOOBOT I.A", page_icon="⚽", layout="wide")

API_KEY_FOOTBALL = st.secrets["FOOTBALL_API_KEY"]
headers = {"X-Auth-Token": API_KEY_FOOTBALL}
BASE_URL = "https://api.football-data.org/v4"

# Parâmetros de Simulação
MAX_GOALS = 8
SIMULATIONS = 50000
HOME_ADVANTAGE = 1.10

LEAGUES = {
    "🇬🇧 Premier League": "PL",
    "🇪🇸 La Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🇫🇷 Ligue 1": "FL1",
    "🇧🇷 Brasileirão": "BSA"
}

# -----------------------------
# SIDEBAR (GESTÃO DE ACESSO E CRÉDITOS)
# -----------------------------
with st.sidebar:
    st.header("👤 Área do Usuário")
    st.write("---")
    
    # Simulação de Login (Futuramente você pode integrar com um banco de dados)
    user_status = st.toggle("Simular Login", value=True)
    
    if user_status:
        st.success("Logado como: **Wesley Kloster**")
        st.metric(label="🪙 Créditos Disponíveis", value="45", delta="-1")
        st.info("Plano: **Premium Gold**")
    else:
        st.warning("Você não está logado.")
        st.button("Fazer Login")

# -----------------------------
# LOGICA DE IA (VERSÃO CORRIGIDA 2026)
# -----------------------------
def realizar_analise_gemini(home, away, league):
    # Lista de chaves (adicione as chaves novas que você criar aqui)
    LISTA_CHAVES = [
        st.secrets["GEMINI_CHAVE_1"],  # Nome: Default Gemini Project
        st.secrets["GEMINI_CHAVE_2"]  # Nome: FOOTBOT PRO V5 com IA
    ]
    
    prompt = f"""
    Você é um analista profissional de apostas esportivas e trader de elite. Sua precisão é o seu maior ativo.
    Hoje é dia {datetime.date.today()}. Considere todas as notícias, lesões e escalações reais para este momento.

    Analise o jogo: {home} vs {away}
    Competição: {league}

    Produza uma análise objetiva e profissional para apostas. 
    Retorne EXATAMENTE neste formato de Markdown, sem textos adicionais antes ou depois:

    🎯 **Veredito Final**
    * {home} XxX {away}
    (Retorne o RESULTADO EXATO com maior confiança estatística)

    📊 **Probabilidades estimadas**
    * Casa: %
    * Empate: %
    * Fora: %
    (Faça nesse formato de lista, linha por linha)

    ⚽ **Mercado de Gols**
    * **Over/Under:** (Ex: Mais que 2.5 gols / Menos que 2.5 gols)
    * **Ambas as equipes marcam (BTTS): Sim/Não** 

    🔎 **Justificativa Técnica:**
    * (5 a 6 linhas explicando a lógica, focando em desfalques, mando de campo e necessidade de vitória)
    """
    
    # Modelos baseados no  dashboard e na versão atual (Gemini 3)
    modelos_disponiveis = ["gemini-3-flash", "gemini-2.5-flash"]

    # O código vai tentar cada chave até uma funcionar
    for api_key in LISTA_CHAVES:
        client = genai.Client(api_key=api_key)
        
        for modelo in modelos_disponiveis:
            try:
                response = client.models.generate_content(model=modelo, contents=prompt)
                # Se deu certo, retorna o texto e interrompe os loops
                return response.text
            except Exception as e:
                # Se for erro de cota (429), ele avisa e pula para a próxima tentativa
                if "429" in str(e):
                    continue 
                # Se for outro erro, ele tenta o próximo modelo/chave
                continue

    return "❌ Todas as chaves atingiram o limite. Tente novamente em alguns minutos."

# -----------------------------
# FUNÇÃO BUSCAR JOGOS
# -----------------------------
@st.cache_data(ttl=600)
def get_matches(league_code, date_str):
    url = f"{BASE_URL}/competitions/{league_code}/matches?dateFrom={date_str}&dateTo={date_str}"
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json().get("matches", [])
        return []
    except:
        return []

# -----------------------------
# FUNÇÃO PARA EXTRAIR PORCENTAGENS
# -----------------------------
def extrair_probabilidades(texto_analise):
    # Procura por números seguidos de % no texto
    import re
    numeros = re.findall(r'(\d+)%', texto_analise)
    if len(numeros) >= 3:
        return [int(numeros[0]), int(numeros[1]), int(numeros[2])]
    return [33, 33, 34] # Fallback caso não encontre

# -----------------------------
# INTERFACE PRINCIPAL
# -----------------------------
st.title("⚽ FOOBOT PRO v5 - FOOBOT I.A")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("🏆 Seleção de Partida")
    
    # Data agora no corpo principal e formatada BR
    date = st.date_input(
        "📅 Data da partida", 
        datetime.date.today(), 
        format="DD/MM/YYYY"
    )
    date_str = date.strftime("%Y-%m-%d")

    all_matches = []
    leagues_found = []

    # Coleta de jogos
    for league_name, league_code in LEAGUES.items():
        matches = get_matches(league_code, date_str)
        if matches:
            leagues_found.append(league_name)
            for m in matches:
                utc_dt = datetime.datetime.strptime(m["utcDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
                brasil_dt = utc_dt.astimezone(pytz.timezone("America/Sao_Paulo"))
                
                all_matches.append({
                    "horario": brasil_dt.strftime("%H:%M"),
                    "home": m["homeTeam"]["name"],
                    "away": m["awayTeam"]["name"],
                    "name": f"[ {brasil_dt.strftime('%H:%M')} ] {m['homeTeam']['name']} x {m['awayTeam']['name']}",
                    "league_display": league_name,
                    "league_name": m["competition"]["name"]
                })

    if all_matches:
        sel_league = st.selectbox("Escolha a Liga", ["🌍 Todas"] + leagues_found)
        
        filtered = [m for m in all_matches if sel_league == "🌍 Todas" or m['league_display'] == sel_league]
        
        match_names = [m['name'] for m in filtered]
        selected_name = st.selectbox("Escolha o Jogo", match_names)
        
        jogo = next(item for item in filtered if item["name"] == selected_name)
        
        st.info(f"📍 **Liga:** {jogo['league_name']}\n\n⏰ **Início:** {jogo['horario']}")
        
        btn_analise = st.button("🚀 GERAR ANÁLISE PREMIUM", use_container_width=True)
    else:
        st.warning("Nenhum jogo encontrado.")
        btn_analise = False

with col2:
    st.subheader("📊 Análise de Inteligência")
    if btn_analise:
        with st.spinner(f"Analisando a partida entre {jogo['home']} x {jogo['away']}..."):
            resultado = realizar_analise_gemini(jogo['home'], jogo['away'], jogo['league_name'])
            
            # 1. Exibe a análise em texto
            st.markdown(resultado)
            
            # SÓ GERA O GRÁFICO SE A ANÁLISE FOR BEM-SUCEDIDA
            # Verificamos se o texto contém "Probabilidades", que é parte do nosso prompt de sucesso
            if "Probabilidades" in resultado:
                probs = extrair_probabilidades(resultado)
                df_probs = pd.DataFrame({
                    'Resultado': ['Casa', 'Empate', 'Fora'],
                    'Probabilidade (%)': probs
                })

                fig = px.bar(
                    df_probs, x='Probabilidade (%)', y='Resultado', orientation='h',
                    text='Probabilidade (%)', color='Resultado',
                    color_discrete_map={'Casa': '#2ecc71', 'Empate': '#95a5a6', 'Fora': '#e74c3c'},
                    title="📊 Probabilidades Visuais"
                )
                
                fig.update_layout(showlegend=False, height=250, margin=dict(l=10, r=10, t=50, b=20), xaxis_range=[0, 110])
                fig.update_traces(texttemplate='%{text}%', textposition='outside')
                st.plotly_chart(fig, use_container_width=True)
            
    else:
        st.write("Selecione um jogo para gerar as estatíscas completas da partida.")
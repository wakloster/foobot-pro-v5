import streamlit as st
import requests
import datetime
import pytz
import time
from google import genai
import pandas as pd
import plotly.express as px
from streamlit_gsheets import GSheetsConnection

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


# 1. Cria a conexão usando as chaves [connections.gsheets] do seu secrets.toml
conn = st.connection("gsheets", type=GSheetsConnection)

def obter_dados_usuarios(tempo_cache="1m"):
    try:
        # 2. Lê a planilha usando a URL que está dentro da seção [connections.gsheets]
        # ttl="1m" mantém um cache de 1 minuto para não estourar a cota do Google
        df = conn.read(ttl=tempo_cache)
        return df
    except Exception as e:
        st.error(f"Erro ao carregar créditos: {e}")
        return pd.DataFrame()
    
def descontar_credito(nome_usuario):
    try:
        # Lê os dados sem cache (ttl=0) para pegar o saldo mais atualizado
        df_atual = conn.read(ttl=0)
        
        # Localiza o índice do usuário
        idx = df_atual[df_atual['nome'].str.lower() == nome_usuario.lower()].index
        
        if not idx.empty:
            saldo_atual = int(df_atual.loc[idx, 'creditos'].values[0])
            if saldo_atual > 0:
                novo_saldo = saldo_atual - 1
                df_atual.loc[idx, 'creditos'] = novo_saldo
                
                # Salva a planilha atualizada no Google Sheets
                conn.update(data=df_atual)
                return novo_saldo
        return None
    except Exception as e:
        st.error(f"Erro ao atualizar saldo: {e}")
        return None

LEAGUES = {
    "🇧🇷 Brasileirão": "BSA",         # Prioridade máxima!
    "🇪🇺 Champions League": "CL",
    "🇬🇧 Premier League": "PL",
    "🇪🇸 La Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🇫🇷 Ligue 1": "FL1"
}

# -----------------------------
# SIDEBAR (LOGIN, GESTÃO DE ACESSO E CRÉDITOS)
# -----------------------------
# --- INICIALIZAÇÃO DO ESTADO (Coloque no topo do script) ---
if "logado" not in st.session_state:
    st.session_state.logado = False
    st.session_state.usuario = None
    st.session_state.nome_exibicao = ""
    if "ultima_analise" not in st.session_state:
        st.session_state.ultima_analise = None

# --- SIDEBAR ESTILIZADA ---
st.sidebar.markdown("### 👤 Área do Usuário")
st.sidebar.markdown("---")

# Verificação de Estado para alternar entre Tela de Login e Dashboard
if not st.session_state.logado:
    # --- TELA DE LOGIN ---
    nome_input_login = st.sidebar.text_input("Digite seu usuário:", key="login_input").strip().lower()
    
    if st.sidebar.button("🚀 Entrar", use_container_width=True):
        df_usuarios = obter_dados_usuarios()
        if not df_usuarios.empty and nome_input_login in df_usuarios['nome'].str.lower().values:
            user_row = df_usuarios.loc[df_usuarios['nome'].str.lower() == nome_input_login]
            creditos_val = int(user_row['creditos'].values[0])
            
            if creditos_val > 0:
                st.session_state.logado = True
                st.session_state.usuario = nome_input_login
                # Busca nome de exibição na planilha ou usa o login formatado
                st.session_state.nome_exibicao = user_row['exibicao'].values[0] if 'exibicao' in user_row.columns else nome_input_login.capitalize()
                st.rerun()
            else:
                st.sidebar.warning("⚠️ Você não possui créditos suficientes.")
        else:
            st.sidebar.error("❌ Usuário não encontrado na base.")
else:
    # --- TELA LOGADA (IGUAL À IMAGEM) ---
    st.sidebar.success(f"Logado como: **{st.session_state.nome_exibicao}**")
    
    st.sidebar.markdown("#### 🪙 Créditos Disponíveis")
    
    # Busca saldo em tempo real para exibir no contador grande
    df_vivos = obter_dados_usuarios(tempo_cache=0)
    saldo_atual = int(df_vivos.loc[df_vivos['nome'].str.lower() == st.session_state.usuario, 'creditos'].values[0])
    
    # Layout de colunas para o contador e o indicador de débito
    col_saldo, col_debito = st.sidebar.columns([1, 1])
    with col_saldo:
        st.title(f"{saldo_atual}")
    with col_debito:
        st.markdown("\n") # Espaçador para alinhar
        st.error("🔻 -1")
    
    st.sidebar.info("Plano: **Premium Gold**")
    
    if st.sidebar.button("🚪 Sair / Logout", use_container_width=True):
        st.session_state.logado = False
        st.session_state.usuario = None
        st.rerun()

# --- VARIÁVEIS DE CONTROLE PARA O RESTO DO APP ---
autorizado = st.session_state.logado
nome_input = st.session_state.usuario # Mantém compatibilidade com a função de desconto

# -----------------------------
# LOGICA DE IA (VERSÃO CORRIGIDA 2026)
# -----------------------------
def realizar_analise_gemini(home, away, league):
    # Lista de chaves (adicione as chaves novas que você criar aqui)
    LISTA_CHAVES = [
        st.secrets["GEMINI_CHAVE_1"],
        st.secrets["GEMINI_CHAVE_2"],
        st.secrets["GEMINI_CHAVE_3"],
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
    (Retorne o RESULTADO EXATO com maior confiança estatística, nada além disso, não escreva mais nada além do resultado.)

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
    
    ⚠️ **Nota de Responsabilidade:**
    * Esta análise é baseada em probabilidades estatísticas e dados históricos. No futebol, não existem garantias. 
    Aposte com responsabilidade e nunca utilize valores que possam comprometer sua saúde financeira.
    """
    
    # Modelos baseados no  dashboard e na versão atual (Gemini 3)
    modelos_disponiveis = ["gemini-2.5-flash"]

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
    # Criamos a data de "amanhã" para cobrir jogos que viram a noite no UTC
    dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    amanha_str = (dt_obj + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}/competitions/{league_code}/matches?dateFrom={date_str}&dateTo={amanha_str}"
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
    
    btn_analise = False
    
    # 1. TRAVA DE ACESSO: Só mostra o calendário se estiver logado
    if autorizado:
        fuso_br = pytz.timezone("America/Sao_Paulo")
        hoje_br = datetime.datetime.now(fuso_br).date()
        
        # O Streamlit só executa o que vem abaixo se o usuário interagir com a data
        date = st.date_input(
            "📅 Selecione a data para buscar jogos:", 
            value=None, # Deixa vazio inicialmente para não disparar a busca automática
            format="DD/MM/YYYY"
        )

        if date:
            date_str = date.strftime("%Y-%m-%d")
            all_matches = []
            leagues_found = []

            # 2. BUSCA SOB DEMANDA: Só roda o loop se a data foi selecionada
            with st.spinner("Buscando partidas nas ligas..."):
                for league_name, league_code in LEAGUES.items():
                    matches = get_matches(league_code, date_str)
                    if matches:
                        for m in matches:
                            utc_dt = datetime.datetime.strptime(m["utcDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
                            brasil_dt = utc_dt.astimezone(pytz.timezone("America/Sao_Paulo"))
                            
                            if brasil_dt.strftime("%Y-%m-%d") == date_str:
                                if league_name not in leagues_found:
                                    leagues_found.append(league_name)
                                
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
                
                # Botão de análise (já protegido pelo 'autorizado' lá em cima)
                btn_analise = st.button("🚀 GERAR ANÁLISE PREMIUM", use_container_width=True)
            else:
                st.warning("Nenhuma partida encontrada para esta data nas ligas configuradas.")
    else:
        # Mensagem para quem não está logado
        st.error("🔒 Área Restrita")
        st.info("Para visualizar as partidas disponíveis e gerar análises, por favor, realize o login na barra lateral.")

with col2:
    st.subheader("📊 Análise de Inteligência")
    
    # Se o botão for clicado e estiver autorizado
    if btn_analise and autorizado:
        with st.spinner(f"Analisando a partida entre {jogo['home']} x {jogo['away']}..."):
            resultado = realizar_analise_gemini(jogo['home'], jogo['away'], jogo['league_name'])
            
            if "atingiram o limite" not in resultado:
                # 1. Guarda a análise no estado da sessão
                st.session_state.ultima_analise = resultado 
                # 2. Desconta o crédito na planilha
                descontar_credito(st.session_state.usuario)
                # 3. Força o recarregamento para atualizar o saldo na sidebar
                st.rerun() 
            else:
                st.error(resultado)
                st.info("🛡️ Nenhum crédito foi descontado.")

    # EXIBIÇÃO DA ANÁLISE (Fica fora do if btn_analise para persistir após o rerun)
    if st.session_state.ultima_analise:
        st.markdown(st.session_state.ultima_analise)
        
        # Gera o gráfico baseado na última análise guardada
        if "Probabilidades" in st.session_state.ultima_analise:
            probs = extrair_probabilidades(st.session_state.ultima_analise)
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
            
            # Aviso Legal (sempre ao final da análise)
            st.markdown("---")
            st.warning("""
                **📢 AVISO LEGAL:** O placar sugerido é uma estimativa baseada em algoritmos de 
                Inteligência Artificial. O **FOOBOT PRO V5** não garante resultados. 
                O futebol é imprevisível; use as informações como suporte à sua própria decisão.
            """)
    
    elif not autorizado:
        st.warning("Aguardando login para liberar os dados de I.A.")
    else:
        st.write("Selecione um jogo para gerar as estatísticas completas.")
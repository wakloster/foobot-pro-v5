import streamlit as st
import requests
import datetime
import pytz
import time
from google import genai
import pandas as pd
import plotly.express as px
import random
import firebase_admin
from firebase_admin import credentials, firestore

# -----------------------------
# CONFIGURAÇÕES INICIAIS
# -----------------------------
st.set_page_config(page_title="FOOBOT PRO v5 - FOOBOT I.A", page_icon="⚽", layout="wide")

API_KEY_FOOTBALL = st.secrets["FOOTBALL_API_KEY"]
headers = {"X-Auth-Token": API_KEY_FOOTBALL}
BASE_URL = "https://api.football-data.org/v4"

# ------------------------
# AQUI COMEÇA A DEFINIÇÃO DE TODAS AS FUNÇÕES
# ------------------------


# Inicializa o Firebase usando os Secrets do Streamlit
if not firebase_admin._apps:
    # Transforma o dicionário do TOML em credenciais válidas
    cred_dict = st.secrets["firebase"]
    cred = credentials.Certificate(dict(cred_dict))
    firebase_admin.initialize_app(cred)

db = firestore.client()

def limpar_analise():
    if "ultima_analise" in st.session_state:
        st.session_state.ultima_analise = None

# -----------------------------
# FUNÇÕES FIREBASE (MIGRAÇÃO)
# -----------------------------

def obter_logs_firebase(limite=50):
    try:
        # Busca na coleção 'logs' ordenando pela data decrescente
        logs_ref = db.collection('logs').order_by(
            "data_hora", direction=firestore.Query.DESCENDING
        ).limit(limite)
        
        docs = logs_ref.stream()
        logs_list = []
        
        for doc in docs:
            d = doc.to_dict()
            if 'data_hora' in d:
                # Converte o timestamp do Firebase para o horário de Brasília
                d['data_hora'] = d['data_hora'].astimezone(pytz.timezone("America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
            logs_list.append(d)
            
        return pd.DataFrame(logs_list)
    except Exception as e:
        return pd.DataFrame()

def obter_dados_usuarios_firebase():
    """Busca todos os usuários da coleção 'usuarios' no Firestore"""
    try:
        users_ref = db.collection('usuarios')
        docs = users_ref.stream()
        
        usuarios_list = []
        for doc in docs:
            dados = doc.to_dict()
            dados['id'] = doc.id  # Mantém o ID do documento
            usuarios_list.append(dados)
            
        return pd.DataFrame(usuarios_list)
    except Exception as e:
        st.error(f"Erro ao carregar usuários do Firebase: {e}")
        return pd.DataFrame()

def descontar_credito_firebase(nome_usuario):
    """Desconta 1 crédito diretamente no documento do usuário"""
    try:
        # No Firebase, usamos o nome em minúsculo como ID do documento para facilitar
        user_ref = db.collection('usuarios').document(nome_usuario.lower())
        doc = user_ref.get()
        
        if doc.exists:
            saldo_atual = int(doc.to_dict().get('creditos', 0))
            if saldo_atual > 0:
                novo_saldo = saldo_atual - 1
                user_ref.update({'creditos': novo_saldo})
                return novo_saldo
        return None
    except Exception as e:
        st.error(f"Erro ao atualizar saldo no Firebase: {e}")
        return None
    
def adicionar_creditos_firebase(nome_usuario, quantidade):
    try:
        user_ref = db.collection('usuarios').document(nome_usuario.lower())
        doc = user_ref.get()
        if doc.exists:
            saldo_atual = int(doc.to_dict().get('creditos', 0))
            novo_saldo = saldo_atual + quantidade
            user_ref.update({'creditos': novo_saldo})
            return novo_saldo
        return None
    except Exception as e:
        st.error(f"Erro na recarga Firebase: {e}")
        return None

def registrar_log_firebase(usuario, acao, detalhe):
    """Registra logs como novos documentos em uma coleção, sem limite de quota!"""
    try:
        log_ref = db.collection('logs').document() # Gera um ID automático
        log_ref.set({
            "data_hora": datetime.datetime.now(pytz.timezone("America/Sao_Paulo")),
            "usuario": usuario,
            "acao": acao,
            "detalhe": detalhe
        })
    except Exception as e:
        print(f"Erro no log Firebase: {e}")

def gerenciar_broadcast_firebase(nova_msg=None):
    """Gerencia a mensagem global em um documento fixo de configuração"""
    try:
        config_ref = db.collection('config').document('broadcast')
        
        if nova_msg is not None:
            config_ref.set({'valor': str(nova_msg).strip() if nova_msg else ""})
            return nova_msg
        
        doc = config_ref.get()
        if doc.exists:
            return doc.to_dict().get('valor', "")
        return ""
    except:
        return ""

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
        # BUSCA DIRETA NO FIREBASE
        user_ref = db.collection('usuarios').document(nome_input_login)
        doc = user_ref.get()
        
        if doc.exists:
            user_data = doc.to_dict()
            creditos_val = int(user_data.get('creditos', 0))
            
            if creditos_val > 0:
                st.session_state.logado = True
                st.session_state.usuario = nome_input_login
                st.session_state.nivel = int(user_data.get('nivel', 0))
                st.session_state.nome_exibicao = user_data.get('exibicao', nome_input_login.capitalize())
                
                # Log de sucesso (Já usando a função nova de log do Firebase)
                registrar_log_firebase(nome_input_login, "LOGIN", "Acessou o sistema via Firebase")
                st.rerun()
            else:
                st.sidebar.warning("⚠️ Você não possui créditos suficientes.")
        else:
            st.sidebar.error("❌ Usuário não encontrado no Firebase.")
else:
    # --- TELA LOGADA (SIDEBAR) ---
    st.sidebar.success(f"Olá **{st.session_state.nome_exibicao}**")
    st.sidebar.markdown("#### 🪙 Créditos Disponíveis")
    
    # Busca saldo em tempo real no FIREBASE
    user_ref = db.collection('usuarios').document(st.session_state.usuario)
    doc = user_ref.get()
    saldo_atual = int(doc.to_dict().get('creditos', 0)) if doc.exists else 0
    
    col_saldo, col_debito = st.sidebar.columns([1, 1])
    with col_saldo:
        st.title(f"{saldo_atual}")
    with col_debito:
        st.markdown("\n") 
        st.error("🔻 -1")
    
    st.sidebar.info("Plano: **Premium Gold**")

    # --- ÁREA ADMINISTRATIVA (ESTRUTURA CORRIGIDA) ---
    # Esta parte DEVE vir antes do botão de Logout para garantir a renderização
    if st.session_state.get("nivel") == 1:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🛠️ Painel Master Admin")
        
        # --- ABA 1: GESTÃO DE CRÉDITOS ---
        with st.sidebar.expander("➕ Recarga Rápida", expanded=False):
            u_destino = st.text_input("Para:", key="adm_u").strip().lower()
            qtd = st.number_input("Quantidade:", min_value=1, step=5, key="adm_q")
            if st.button("Confirmar Recarga", use_container_width=True):
                if adicionar_creditos_firebase(u_destino, qtd):
                    registrar_log_firebase(st.session_state.usuario, "RECARGA", f"+{qtd} para {u_destino}")
                    st.success("Créditos adicionados!")
                    time.sleep(1); st.rerun()

        # --- ABA 2: VISUALIZAR BANCO ---
        with st.sidebar.expander("👥 Base de Usuários"):
            df_view = obter_dados_usuarios_firebase() 
            if not df_view.empty:
                st.dataframe(df_view[['nome', 'creditos', 'nivel']], hide_index=True)

        # --- ABA 3: AUDITORIA (VAR DO SISTEMA) ---
        with st.sidebar.expander("📜 Histórico de Logs", expanded=False):
            if st.button("🔄 Atualizar Logs"):
                st.rerun()

            df_logs = obter_logs_firebase(limite=30)
            
            if not df_logs.empty:
                # Define a ordem das colunas para a tabela ficar intuitiva
                st.dataframe(
                    df_logs[['data_hora', 'usuario', 'acao', 'detalhe']], 
                    hide_index=True,
                    use_container_width=True
                )
            else:
                st.info("Nenhuma atividade registrada ainda.")
        
        # --- ABA 4: COMUNICAÇÃO (BROADCAST) ---
        with st.sidebar.expander("📢 Mural"):
            msg_atu = gerenciar_broadcast_firebase()
            nova_m = st.text_area("Aviso:", value=msg_atu)
            if st.button("Atualizar Mural"):
                gerenciar_broadcast_firebase(nova_m)
                st.success("Mural atualizado!")

# --- ABA 5: CADASTRAR NOVO USUÁRIO ---
        with st.sidebar.expander("👤 Novo Usuário"):
            new_login = st.text_input("Login:", key="new_u").strip().lower()
            new_name = st.text_input("Nome de Exibição:", key="new_e")
            if st.button("Criar Usuário"):
                db.collection('usuarios').document(new_login).set({
                    "nome": new_login, "exibicao": new_name, "creditos": 10, "nivel": 0
                })
                registrar_log_firebase(st.session_state.usuario, "CADASTRO", f"Criou {new_login}")
                st.success("Criado!")

if st.sidebar.button("Sair", use_container_width=True):
        # Limpa TUDO da memória da sessão atual
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        
        # Reinicia o app do zero
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
# EXIBIÇÃO DO BROADCAST COM EMOJI ALEATÓRIO
msg_global = gerenciar_broadcast_firebase()
if msg_global:
    # Lista de emojis para dar aquele grau no visual
    emojis = ["📢", "🔔", "⚠️", "🔥", "🚀", "💡", "⚽", "🏆"]
    icon = random.choice(emojis)
    
    st.info(f"{icon} **AVISO:** {msg_global}")

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
            format="DD/MM/YYYY",
            on_change=limpar_analise
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
                sel_league = st.selectbox("Escolha a Liga", ["🌍 Todas"] + leagues_found, on_change=limpar_analise)
                filtered = [m for m in all_matches if sel_league == "🌍 Todas" or m['league_display'] == sel_league]
                match_names = [m['name'] for m in filtered]
                selected_name = st.selectbox("Escolha o Jogo", match_names, on_change=limpar_analise)
                
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
                descontar_credito_firebase(st.session_state.usuario)
                # 3. Força o recarregamento para atualizar o saldo na sidebar
                # --- AQUI É ONDE O LOG É GRAVADO NA CONSULTA! ---
                registrar_log_firebase(st.session_state.usuario, "CONSULTA", f"{jogo['home']} x {jogo['away']}")
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
        
# -----------------------------
# DASHBOARD ESTATÍSTICO (RODAPÉ ADMIN)
# -----------------------------
if autorizado and st.session_state.get("nivel") == 1:
    st.markdown("---")
    st.subheader("📊 Painel de Controle Analítico")
    
    try:
        # Busca logs do Firebase
        logs_ref = db.collection('logs').order_by("data_hora", direction=firestore.Query.DESCENDING).limit(100)
        logs_docs = logs_ref.stream()
        logs_list = [d.to_dict() for d in logs_docs]
        df_stats = pd.DataFrame(logs_list)
        
        if not df_stats.empty:
            # Firebase já retorna datetime, só formatamos para o gráfico
            df_stats['dia'] = df_stats['data_hora'].dt.strftime('%d/%m/%Y')
            
            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                contagem_dia = df_stats.groupby('dia').size().reset_index(name='total')
                fig_vol = px.line(contagem_dia, x='dia', y='total', title="📈 Uso Diário", template="plotly_dark")
                fig_vol.update_xaxes(type='category')
                st.plotly_chart(fig_vol, use_container_width=True)
            
            with col_graph2:
                dist_acao = df_stats['acao'].value_counts().reset_index()
                dist_acao.columns = ['Ação', 'Qtd']
                fig_pizza = px.pie(dist_acao, values='Qtd', names='Ação', title="🍕 Operações")
                st.plotly_chart(fig_pizza, use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao carregar dashboard: {e}")
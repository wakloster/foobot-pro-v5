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
st.set_page_config(page_title="FOOBOT PRO v5 - FOOBOT I.A",
                   page_icon="⚽", layout="wide")

if "historico_analises" not in st.session_state:
    # Dicionário: {ID_DO_JOGO: TEXTO_DA_ANALISE}
    st.session_state.historico_analises = {}


# APIs e Credenciais

# API da Football-Data.org
API_KEY_FOOTBALL = st.secrets["FOOTBALL_API_KEY"]
headers = {"X-Auth-Token": API_KEY_FOOTBALL}
BASE_URL = "https://api.football-data.org/v4"

# API da API-Football
API_KEY_2 = st.secrets["API_FOOTBALL_KEY"]
URL_2 = "https://v3.football.api-sports.io/fixtures"
HEADERS_2 = {
    "x-rapidapi-key": API_KEY_2,
    "x-rapidapi-host": "v3.football.api-sports.io"
}

# Inicializa o Firebase usando os Secrets do Streamlit
if not firebase_admin._apps:
    # Transforma o dicionário do TOML em credenciais válidas
    cred_dict = st.secrets["firebase"]
    cred = credentials.Certificate(dict(cred_dict))
    firebase_admin.initialize_app(cred)

db = firestore.client()

# -----------------------------
# FUNÇÕES DE APOIO
# -----------------------------


def limpar_analise():
    if "ultima_analise" in st.session_state:
        st.session_state.ultima_analise = None


def extrair_probabilidades(texto_analise):
    """Extrai as 3 porcentagens (Casa, Empate, Fora) do texto da IA de forma segura"""
    import re
    # Remove espaços e limpa o texto para evitar erros de formatação da IA
    texto_limpo = texto_analise.replace(" ", "")
    # Busca por padrões de números seguidos de %
    numeros = re.findall(r'(\d+)%', texto_limpo)

    try:
        if len(numeros) >= 3:
            # Pega os 3 primeiros valores encontrados
            p_casa = int(numeros[0])
            p_empate = int(numeros[1])
            p_fora = int(numeros[2])
            return [p_casa, p_empate, p_fora]
        else:
            # Caso a IA não tenha gerado as %, retorna um padrão equilibrado para não quebrar o gráfico
            return [33, 34, 33]
    except:
        return [33, 34, 33]

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
                d['data_hora'] = d['data_hora'].astimezone(pytz.timezone(
                    "America/Sao_Paulo")).strftime("%d/%m/%Y %H:%M:%S")
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


def descontar_credito_firebase(nome_usuario, jogo_id):
    """Desconta 1 crédito e registra o ID do jogo no perfil do usuário"""
    try:
        # No Firebase, usamos o nome em minúsculo como ID do documento para facilitar
        user_ref = db.collection('usuarios').document(nome_usuario.lower())
        doc = user_ref.get()

        if doc.exists:
            dados = doc.to_dict()
            # Se for vitalício, apenas registra o jogo sem descontar nada
            if dados.get('vitalicio', False):
                user_ref.update(
                    {"analises_liberadas": firestore.ArrayUnion([jogo_id])})
                return "VITALÍCIO"

            saldo_atual = float(doc.to_dict().get('creditos', 0))

            if saldo_atual >= 1.0:
                novo_saldo = round(saldo_atual - 1.0, 2)
                # Atualiza saldo E adiciona o jogo à lista de liberados
                user_ref.update({
                    'creditos': novo_saldo,
                    "analises_liberadas": firestore.ArrayUnion([jogo_id])
                })
                return novo_saldo
            else:
                return "SALDO_INSUFICIENTE"  # Retorna erro em vez de negativar
        return None
    except Exception as e:
        st.error(f"Erro ao atualizar saldo no Firebase: {e}")
        return None


def descontar_reanalise_firebase(nome_usuario, jogo_id):
    """Desconta apenas meio crédito para reanálise, exceto para vitalícios"""
    try:
        user_ref = db.collection('usuarios').document(nome_usuario.lower())
        doc = user_ref.get()
        if doc.exists:
            dados = doc.to_dict()
            # 🛡️ TRAVA DE SEGURANÇA: Se for vitalício, sai sem descontar
            if dados.get('vitalicio', False):
                return "VITALÍCIO"

            saldo_atual = float(dados.get('creditos', 0))

            if saldo_atual >= 0.5:
                novo_saldo = round(saldo_atual - 0.5, 2)
                user_ref.update({'creditos': novo_saldo})
                return novo_saldo
            else:
                return "SALDO_INSUFICIENTE"
        return None
    except Exception as e:
        print(f"Erro no desconto: {e}")
        return None


def adicionar_creditos_firebase(nome_usuario, quantidade):
    try:
        user_ref = db.collection('usuarios').document(nome_usuario.lower())
        doc = user_ref.get()
        # TRAVA: Só prossegue se o documento existir
        if doc.exists:
            saldo_atual = float(doc.to_dict().get('creditos', 0))
            novo_saldo = saldo_atual + quantidade
            user_ref.update({'creditos': novo_saldo})
            return True, novo_saldo
        else:
            return False, "Usuário não encontrado"
    except Exception as e:
        return False, str(e)


def registrar_log_firebase(usuario, acao, detalhe):
    """Registra logs como novos documentos em uma coleção, sem limite de quota!"""
    try:
        log_ref = db.collection('logs').document()  # Gera um ID automático
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
            config_ref.set(
                {'valor': str(nova_msg).strip() if nova_msg else ""})
            return nova_msg

        doc = config_ref.get()
        if doc.exists:
            return doc.to_dict().get('valor', "")
        return ""
    except:
        return ""


LEAGUES = {
    "🇧🇷 Brasileirão Série A": "BSA",
    "🇪🇺 Champions League": "CL",
    "🇬🇧 Premier League": "PL",
    "🇪🇸 La Liga": "PD",
    "🇩🇪 Bundesliga": "BL1",
    "🇮🇹 Serie A": "SA",
    "🇫🇷 Ligue 1": "FL1"
}


@st.dialog("Confirmar Transação")
def modal_confirmar_recarga(usuario, quantidade):
    st.warning(
        f"Você está prestes a adicionar **{quantidade}** créditos para **{usuario}**.")
    st.write("Deseja prosseguir com a operação?")

    col_sim, col_nao = st.columns(2)

    with col_sim:
        if st.button("✅ Confirmar", use_container_width=True):
            sucesso, resultado = adicionar_creditos_firebase(
                usuario, quantidade)
            if sucesso:
                registrar_log_firebase(
                    st.session_state.usuario, "RECARGA", f"+{quantidade} para {usuario}")
                st.success("Créditos injetados!")
                time.sleep(1)
                st.rerun()
            else:
                st.error(f"Erro: {resultado}")

    with col_nao:
        if st.button("❌ Cancelar", use_container_width=True):
            st.rerun()


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
if not st.session_state.get("logado", False):
    # --- TELA DE LOGIN (Só aparece se NÃO estiver logado) ---
    nome_input_login = st.sidebar.text_input(
        "Digite seu usuário:", key="login_input").strip().lower()

    if st.sidebar.button("🚀 Entrar", use_container_width=True):
        # 🛡️ TRAVA DE SEGURANÇA: Verifica se o campo não está vazio
        if not nome_input_login:
            st.sidebar.warning(
                "⚠️ Por favor, digite seu usuário antes de entrar.")
        else:
            # Só faz a chamada ao Firebase se houver texto
            try:
                user_ref = db.collection('usuarios').document(nome_input_login)
                doc = user_ref.get()

                if doc.exists:
                    user_data = doc.to_dict()
                    creditos_val = float(user_data.get('creditos', 0))
                    is_vitalicio = user_data.get('vitalicio', False)

                    if is_vitalicio or creditos_val > 0:
                        st.session_state.logado = True
                        st.session_state.usuario = nome_input_login
                        st.session_state.nivel = int(user_data.get('nivel', 0))
                        st.session_state.nome_exibicao = user_data.get(
                            'exibicao', nome_input_login.capitalize())
                        st.session_state.vitalicio = is_vitalicio

                        # --- EFEITO DE BOAS-VINDAS ---
                        st.balloons()  # Solta balões na tela
                        st.sidebar.success(
                            f"🚀 Bem-vindo ao time, {st.session_state.nome_exibicao}!")

                        registrar_log_firebase(
                            nome_input_login, "LOGIN", "Acessou o sistema")
                        # Aguarda 2 segundos para o usuário ver a mensagem antes de atualizar a página
                        time.sleep(3)
                        st.rerun()
                    else:
                        st.sidebar.warning(
                            "⚠️ Você não possui créditos suficientes.")
                else:
                    st.sidebar.error("❌ Usuário não encontrado.")
            except Exception as e:
                # Captura qualquer outro erro inesperado do Firebase
                st.sidebar.error(f"Erro ao conectar com o servidor: {e}")
else:
    # --- TELA LOGADA (SIDEBAR) ---
    st.sidebar.success(f"Olá **{st.session_state.nome_exibicao}**")

    # Busca saldo em tempo real no FIREBASE
    user_ref = db.collection('usuarios').document(st.session_state.usuario)
    doc = user_ref.get()
    dados_usuario = doc.to_dict() if doc.exists else {}

    # ♾️ Verifica se é vitalício
    is_vitalicio = dados_usuario.get('vitalicio', False)
    saldo_atual = float(dados_usuario.get('creditos', 0))

    st.sidebar.markdown("---")

    if is_vitalicio:
        # Visual para quem é VIP
        st.sidebar.markdown("### ♾️ Créditos Ilimitados")
        st.sidebar.success("🏆 Acesso: **VITALÍCIO**")
    else:
        # Visual padrão para quem usa créditos
        st.sidebar.markdown(f"### 🪙 Saldo: {saldo_atual:.1f}")

        # Opcional: Se quiser manter o selo de "Variável" de forma discreta
        st.sidebar.error("🔻 Consumo Variável")

        st.sidebar.info("Plano: **Gold Básico**")
        
        # --- SISTEMA DE RECARGA TRIBOPAY ---
        st.sidebar.markdown("---")
        with st.sidebar.expander("💳 Adquirir Créditos", expanded=False):
            st.caption("Valor por crédito: R$ 0,75")
            
            link_base = "https://pay.tribopay.com.br/SEU_ID_AQUI" # Substitua pelo seu link de produto
            u_ref = st.session_state.usuario
            
            # Opções de pacotes fixos
            col1, col2, col3 = st.columns(3)
            if col1.button("🪙 10", help="R$ 7,50"):
                st.link_button("Pagar R$ 7,50", f"{link_base}?external_id={u_ref}&amount=7.50")
            
            if col2.button("🪙 20", help="R$ 15,00"):
                st.link_button("Pagar R$ 15,00", f"{link_base}?external_id={u_ref}&amount=15.00")
                
            if col3.button("🪙 50", help="R$ 37,50"):
                st.link_button("Pagar R$ 37,50", f"{link_base}?external_id={u_ref}&amount=37.50")

            st.markdown("---")
            
            # Input para créditos personalizados
            qtd_custom = st.number_input("Quantidade personalizada:", min_value=1.0, step=1.0, value=10.0)
            valor_total = qtd_custom * 0.75
            
            st.write(f"Total: **R$ {valor_total:.2f}**")
            
            if st.button("Gerar Pagamento Personalizado", use_container_width=True):
                # Enviamos o valor calculado via parâmetro para a TriboPay
                url_final = f"{link_base}?external_id={u_ref}&amount={valor_total:.2f}"
                st.link_button("Confirmar e Pagar", url_final, type="primary", use_container_width=True)

    # --- ÁREA ADMINISTRATIVA (ESTRUTURA CORRIGIDA) ---
    # Esta parte DEVE vir antes do botão de Logout para garantir a renderização
    if st.session_state.get("nivel") == 1:
        st.sidebar.markdown("---")
        st.sidebar.markdown("### 🛠️ Painel Master Admin")

        # --- ABA 1: GESTÃO DE CRÉDITOS ---
        with st.sidebar.expander("➕ Recarga Rápida", expanded=False):
            u_destino = st.text_input("Para:", key="adm_u").strip().lower()
            qtd = st.number_input(
                "Quantidade:", min_value=5, step=5, key="adm_q")

            if st.button("🚀 Iniciar Recarga", use_container_width=True):
                if u_destino:  # <--- O sistema só verifica isso DEPOIS do clique
                    # 🔍 VALIDAÇÃO ANTES DE ABRIR O MODAL
                    user_ref = db.collection('usuarios').document(u_destino)
                    if user_ref.get().exists:
                        # Se existe, aí sim abre o pop-up
                        modal_confirmar_recarga(u_destino, qtd)
                    else:
                        # Se não existe, erro na sidebar
                        st.error(f"❌ Usuário '{u_destino}' não encontrado!")
                else:
                    # Esta mensagem só vai aparecer se clicar com o campo vazio
                    st.warning("Digite o login do caboco, home!")

        # --- ABA 2: VISUALIZAR BANCO ---
        with st.sidebar.expander("👥 Base de Usuários"):
            df_view = obter_dados_usuarios_firebase()
            if not df_view.empty:
                st.dataframe(
                    df_view[['nome', 'creditos', 'nivel']], hide_index=True)

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

            # Checkbox para definir se é VIP/Vitalício
            is_vip = st.checkbox("Usuário Vitalício?")

            if st.button("Criar Usuário"):
                if new_login and new_name:
                    # Referencia o documento e tenta dar um .get()
                    user_ref = db.collection('usuarios').document(new_login)
                    if user_ref.get().exists:
                        st.error(
                            f"❌ Erro: O usuário '{new_login}' já existe na base!")
                    else:
                        # Só cria se o .get().exists for falso
                        user_ref.set({
                            "nome": new_login,
                            "exibicao": new_name,
                            "creditos": 0 if is_vip else 5,
                            "nivel": 0,          # 0 = Cliente (Não vê Admin)
                            "vitalicio": is_vip  # True = Não gasta créditos
                        })
                        registrar_log_firebase(
                            st.session_state.usuario, "CADASTRO", f"Criou {new_login}")
                        st.success(
                            f"✅ Usuário {new_login} criado com sucesso!")
                else:
                    st.warning("Preencha todos os campos, porra!")

    if st.sidebar.button("Sair", use_container_width=True):
        # Limpa TUDO da memória da sessão atual
        for key in list(st.session_state.keys()):
            del st.session_state[key]

        # Reinicia o app do zero
        st.rerun()

# --- VARIÁVEIS DE CONTROLE PARA O RESTO DO APP ---
autorizado = st.session_state.logado
# Mantém compatibilidade com a função de desconto
nome_input = st.session_state.usuario

# 🛠️ INICIALIZAÇÃO DE SEGURANÇA (Para evitar NameError)
ja_pagou = False
jogo_id_atual = None

# -----------------------------
# LOGICA DE IA (VERSÃO CORRIGIDA 2026)
# -----------------------------


def realizar_analise_gemini(home, away, league):
    # Lista de chaves (adicione as chaves novas que você criar aqui)
    LISTA_CHAVES = [
        st.secrets["GEMINI_CHAVE_1"],
        st.secrets["GEMINI_CHAVE_2"],
        st.secrets["GEMINI_CHAVE_3"],
        st.secrets["GEMINI_CHAVE_4"],
        st.secrets["GEMINI_CHAVE_5"],
        st.secrets["GEMINI_CHAVE_6"],
    ]

    # 🕵️ BUSCA O PROMPT SECRETO DOS SECRETS (Escondido de curiosos)
    template_prompt = st.secrets["PROMPT_FOOTBOT_PRO"]

    # Formata o prompt com os dados do jogo atual
    prompt_final = template_prompt.format(
        home=home,
        away=away,
        league=league,
        data_atual=datetime.date.today()
    )

    # Modelos baseados no  dashboard e na versão atual (Gemini 3)
    modelos_disponiveis = ["gemini-2.5-flash"]

    # O código vai tentar cada chave até uma funcionar
    for api_key in LISTA_CHAVES:
        try:
            client = genai.Client(api_key=api_key)
            # 🚀 Chamada com o Prompt formatado
            response = client.models.generate_content(
                model=modelos_disponiveis[0], contents=prompt_final)
            return response.text
        except Exception as e:
            if "429" in str(e):
                continue
            continue

    return "❌ Todas as chaves atingiram o limite. Tente novamente em alguns minutos."

# -----------------------------
# FUNÇÃO BUSCAR JOGOS
# -----------------------------


@st.cache_data(ttl=3600)
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


@st.cache_data(ttl=3600)
def buscar_jogos_brasil_v3(data_str):
    """Busca APENAS jogos do Brasil na API-Football para não poluir a lista"""
    params = {"date": data_str, "timezone": "America/Sao_Paulo"}
    try:
        response = requests.get(URL_2, headers=HEADERS_2, params=params)
        if response.status_code == 200:
            fixtures = response.json().get("response", [])
            matches = []
            for f in fixtures:
                # 🔍 Verifica o país da competição
                pais = f['league'].get('country', '')
                nome_liga = f['league'].get('name', '')

                # 🛡️ FILTRO REFINADO: Apenas Brasil AND (Série A ou Série B)
                # Adicionamos a Copa do Brasil também, pois é um "campeonato maior"
                ligas_principais = ["Serie A", "Serie B",
                                    "Copa do Brasil", "Paulista"]

                # 🛡️ TRAVA: Só adiciona na lista se o país for o Brasil
                if pais == "Brazil" and any(liga in nome_liga for liga in ligas_principais):
                    matches.append({
                        "horario": f["fixture"]["date"][11:16],
                        "home": f["teams"]["home"]["name"],
                        "away": f["teams"]["away"]["name"],
                        "league_display": f"🇧🇷 {f['league']['name']}",
                        "league_name": f['league']['name'],
                        "name": f"[ {f['fixture']['date'][11:16]} ] {f['teams']['home']['name']} x {f['teams']['away']['name']}"
                    })
            return matches
        return []
    except Exception as e:
        print(f"Erro na API 2: {e}")
        return []


@st.dialog("🔄 Atualizar Inteligência")
def modal_confirmar_reanalise(jogo, jogo_id):
    st.write(
        f"Deseja forçar uma nova análise da I.A para **{jogo['home']} x {jogo['away']}**?")
    st.info(
        "💡 Use isso apenas se houver notícias de última hora (ex.: lesões ou escalações).")
    # 🕵️ TRAVA VISUAL: Só mostra o custo se NÃO for vitalício
    if not st.session_state.get('vitalicio', False):
        st.warning("💰 Custo: **0.5 crédito**")

    label_botao = "✅ Confirmar" if st.session_state.get(
        'vitalicio', False) else "✅ Confirmar e Descontar"

    if st.button(label_botao, use_container_width=True):
        with st.spinner("Recalculando probabilidades com dados novos..."):
            nova_analise = realizar_analise_gemini(
                jogo['home'], jogo['away'], jogo['league_name'])

            if "atingiram o limite" not in nova_analise:
                # Sobrescreve o Cache no Firebase
                db.collection('analises_cache').document(jogo_id).set({
                    'texto': nova_analise,
                    'data': datetime.datetime.now(pytz.timezone("America/Sao_Paulo"))
                })
                # Desconta o crédito reduzido (0.5) da reanálise
                descontar_reanalise_firebase(st.session_state.usuario, jogo_id)

                # ATUALIZA A SESSÃO ANTES DO RERUN
                st.session_state.ultima_analise = nova_analise  # Alimenta a Col2

                registrar_log_firebase(
                    st.session_state.usuario, "REANALISE", f"{jogo['home']} x {jogo['away']}")
                st.rerun()


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

# -----------------------------
# INTERFACE - COLUNA 1
# -----------------------------
col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("🏆 Seleção de Partida")

    btn_analise = False

    if autorizado:
        fuso_br = pytz.timezone("America/Sao_Paulo")
        agora_br = datetime.datetime.now(fuso_br)
        hoje_br = agora_br.date()
        hora_atual_str = agora_br.strftime("%H:%M")

        date = st.date_input(
            "📅 Selecione a data para buscar jogos:",
            value=hoje_br,
            min_value=hoje_br,  # Trava calendário retroativo
            format="DD/MM/YYYY",
            on_change=limpar_analise
        )

        if date:
            if date < hoje_br:
                st.error("🚫 Não é permitido analisar jogos que já aconteceram!")
                st.stop()

            date_str = date.strftime("%Y-%m-%d")
            all_matches = []
            leagues_found = []
            data_formatada = date.strftime("%d/%m/%Y")

            with st.spinner(f"Buscando partidas do dia {data_formatada}..."):
                # 1. Resetar as listas para cada nova busca
                all_matches = []
                leagues_found = []

                # Busca API 1 (Europa e Brasileirão Série A)
                for league_name, league_code in LEAGUES.items():
                    matches_api1 = get_matches(league_code, date_str)

                    if matches_api1:
                        # Criamos uma lista temporária para filtrar jogos do dia correto
                        jogos_da_liga = []
                        for m in matches_api1:
                            utc_dt = datetime.datetime.strptime(
                                m["utcDate"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
                            brasil_dt = utc_dt.astimezone(fuso_br)

                            if brasil_dt.date() == date:
                                jogos_da_liga.append({
                                    "horario": brasil_dt.strftime("%H:%M"),
                                    "home": m["homeTeam"]["name"],
                                    "away": m["awayTeam"]["name"],
                                    "league_display": league_name,
                                    "league_name": m["competition"]["name"],
                                    "name": f"[ {brasil_dt.strftime('%H:%M')} ] {m['homeTeam']['name']} x {m['awayTeam']['name']}"
                                })

                                # SÓ ADICIONA A LIGA se houver jogos para o Brasil no dia selecionado
                        if jogos_da_liga:
                            all_matches.extend(jogos_da_liga)
                            if league_name not in leagues_found:
                                leagues_found.append(league_name)

                # Busca API 2 (Série B, Estaduais e Copas do Brasil)
                jogos_br_api2 = buscar_jogos_brasil_v3(date_str)
                if jogos_br_api2:
                    for jb in jogos_br_api2:
                        is_duplicado = any(
                            jb['home'].lower() in m['home'].lower() for m in all_matches)
                        is_serie_a = "serie a" in jb['league_name'].lower()

                        if not is_duplicado and not is_serie_a:
                            all_matches.append(jb)
                            if jb['league_display'] not in leagues_found:
                                leagues_found.append(jb['league_display'])

            # Ordena por horário
            all_matches = sorted(all_matches, key=lambda x: x['horario'])

            if all_matches:
                sel_league = st.selectbox(
                    "Escolha a Liga", ["🌍 Todas"] + leagues_found, on_change=limpar_analise)
                filtered = [m for m in all_matches if sel_league ==
                            "🌍 Todas" or m['league_display'] == sel_league]

                # --- LÓGICA DA TRAVA VISUAL (VERSÃO COMPACTA) ---
                match_display_options = []
                for m in filtered:
                    if date == hoje_br and m['horario'] <= hora_atual_str:
                        # Usamos "INDISP." ou "AO VIVO" para não cortar o nome dos times
                        match_display_options.append(
                            f"🔴 [INDISP.] {m['home']} x {m['away']}")
                    else:
                        match_display_options.append(m['name'])

                selected_display = st.selectbox(
                    "Escolha o Jogo", match_display_options, on_change=limpar_analise)

                # Recupera o objeto original
                idx = match_display_options.index(selected_display)
                jogo = filtered[idx]

                # 🛠️ ID ÚNICO COM LIGA (Evita colisão)
                liga_limpa = jogo['league_name'].replace(" ", "_")
                jogo_id_atual = f"{jogo['home']}_{jogo['away']}_{liga_limpa}_{date_str}"

                # --- BOTÃO COM STATUS NO TEXTO ---
                esta_bloqueado = "INDISP." in selected_display

                # Busca dados atualizados do usuário
                user_doc = db.collection('usuarios').document(
                    st.session_state.usuario).get().to_dict()
                liberados = user_doc.get("analises_liberadas", [])
                ja_pagou = jogo_id_atual in liberados

                if esta_bloqueado:
                    st.button("🚫 ANÁLISE BLOQUEADA", disabled=True,
                              use_container_width=True)

                    # Mensagem de motivo logo abaixo do botão travado
                    st.error("📉 **Por que esta partida está bloqueada?**")
                    st.info(
                        "O FOOBOT PRO realiza apenas **análises pré-jogo**. "
                        "Como esta partida já iniciou ou encerrou, os dados em tempo real "
                        "viciariam a probabilidade da nossa Inteligência Artificial."
                    )
                else:
                    # 1. Se NÃO está bloqueado, primeiro verificamos se já foi pago ou se precisa gerar
                    if ja_pagou:
                        st.success("✅ Você já possui acesso!")
                        st.button("👁️ ANÁLISE LIBERADA",
                                  disabled=True, use_container_width=True)

                        st.caption(
                            "🚨 Mudanças de última hora (lesões/escalação)?")
                        texto_reanalise = "🔄 REANALISAR PARTIDA AGORA"
                        if not is_vitalicio:
                            texto_reanalise += " (-0.5)"

                        if st.button(texto_reanalise, use_container_width=True):
                            # --- VERIFICAÇÃO EM TEMPO REAL ---
                            user_doc = db.collection('usuarios').document(st.session_state.usuario).get().to_dict()
                            saldo_limpo = round(float(user_doc.get('creditos', 0)), 2)
                            
                            if saldo_limpo < 0.5 and not st.session_state.get('vitalicio'):
                                st.error(f"❌ Saldo insuficiente para reanálise ({saldo_limpo}). Você precisa de 0.5 créditos.")
                            else:
                                # Se tiver saldo, abre o modal ou executa a função
                                modal_confirmar_reanalise(jogo, jogo_id_atual)
                    else:
                        # Botão principal de compra
                        btn_analise = st.button(
                            "🚀 GERAR ANÁLISE PREMIUM", use_container_width=True)

                    # 2. Logo abaixo do botão (seja ele de gerar ou de liberado), mostramos o cronômetro
                    try:
                        hora_jogo = datetime.datetime.strptime(
                            f"{date_str} {jogo['horario']}", "%Y-%m-%d %H:%M")
                        hora_jogo = fuso_br.localize(hora_jogo)
                        agora = datetime.datetime.now(fuso_br)
                        diferenca = hora_jogo - agora

                        if diferenca.total_seconds() > 0:
                            horas, rem = divmod(
                                int(diferenca.total_seconds()), 3600)
                            minutos, _ = divmod(rem, 60)

                            if horas > 0:
                                st.warning(
                                    f"⏳ Inicia em: **{horas}h {minutos}min**")
                            else:
                                st.error(
                                    f"🔥 **FECHANDO!** Inicia em: **{minutos}min**")
                    except:
                        pass
            else:
                st.warning("Nenhuma partida encontrada para esta data.")
    else:
        st.error("🔒 Área Restrita - Faça login na lateral.")
        st.info("Para visualizar as partidas disponíveis e gerar análises, por favor, realize o login na barra lateral.")

# -----------------------------
# INTERFACE - COLUNA 2
# -----------------------------
with col2:
    st.subheader("📊 Análise de Inteligência")

    # 🛡️ TRAVA DE SEGURANÇA: Só prossegue se 'jogo' existir na memória
    if 'jogo' in locals() and jogo:
        # Define o ID Único
        liga_limpa = jogo['league_name'].replace(" ", "_")
        jogo_id_atual = f"{jogo['home']}_{jogo['away']}_{liga_limpa}_{date_str}"

    # --- LÓGICA DE GERAÇÃO (Quando clica no botão) ---
    if btn_analise and autorizado:
        # Busca saldo atualizado antes de começar
        user_ref_check = db.collection('usuarios').document(
            st.session_state.usuario).get()
        saldo_antes = user_ref_check.to_dict().get('creditos', 0)

        # Arredonda para 2 casas decimais antes de comparar
        saldo_limpo = round(float(saldo_antes), 2)

        if saldo_limpo < 1.0 and not st.session_state.get('vitalicio'):
            st.error(
                f"❌ Saldo insuficiente ({saldo_limpo}). Você precisa de 1.0 crédito para análises completas.")
        else:
            with st.spinner(f"Analisando partida entre {jogo['home']} x {jogo['away']}..."):
                resultado = realizar_analise_gemini(
                    jogo['home'], jogo['away'], jogo['league_name'])

                if "atingiram o limite" not in resultado:
                    # 1. Salva na sessão para exibição imediata
                    st.session_state.ultima_analise = resultado
                    # 2. Registra no Firebase (Desconta crédito e libera o jogo)
                    descontar_credito_firebase(
                        st.session_state.usuario, jogo_id_atual)
                    # 3. (OPCIONAL) Salva a análise em uma coleção global para outros usuários
                    db.collection('analises_cache').document(jogo_id_atual).set({
                        'texto': resultado,
                        'data': datetime.datetime.now(pytz.timezone("America/Sao_Paulo"))
                    })

                    registrar_log_firebase(
                        st.session_state.usuario, "CONSULTA", f"{jogo['home']} x {jogo['away']}")
                    st.rerun()
                else:
                    st.error(resultado)

    # --- LÓGICA DE EXIBIÇÃO (Sempre ativa se ja_pagou for True) ---
    if autorizado and ja_pagou:
        # Recupera do cache se a sessão estiver vazia (pós-rerun)
        if not st.session_state.get('ultima_analise'):
            with st.spinner("Recuperando análise liberada..."):
                cache_ref = db.collection(
                    'analises_cache').document(jogo_id_atual).get()
                if cache_ref.exists:
                    st.session_state.ultima_analise = cache_ref.to_dict().get('texto')

        # 🛡️ VERIFICAÇÃO FINAL: Só tenta mostrar se realmente houver texto
        if st.session_state.get('ultima_analise'):
            st.markdown(st.session_state.ultima_analise)

        # --- GERADOR DE GRÁFICO ---
            # Tenta extrair os dados
            probs = extrair_probabilidades(st.session_state.ultima_analise)

            # Monta o DataFrame para o Plotly
            df_probs = pd.DataFrame({
                'Resultado': ['Casa', 'Empate', 'Fora'],
                'Probabilidade (%)': probs
            })

            # Cria o gráfico horizontal
            fig = px.bar(
                df_probs,
                x='Probabilidade (%)',
                y='Resultado',
                orientation='h',
                text='Probabilidade (%)',
                color='Resultado',
                # Cores padrão Foobot: Verde (Casa), Cinza (Empate), Vermelho (Fora)
                color_discrete_map={'Casa': '#2ecc71',
                                    'Empate': '#95a5a6', 'Fora': '#e74c3c'},
                title="📊 Probabilidades Visuais"
            )

            # Ajustes finos de layout
            fig.update_layout(
                showlegend=False,
                height=280,
                margin=dict(l=10, r=10, t=50, b=20),
                # Garante que a barra de 100% apareça inteira
                xaxis_range=[0, 110]
            )
            fig.update_traces(texttemplate='%{text}%', textposition='outside')

            # Renderiza
            st.plotly_chart(fig, use_container_width=True)

            st.markdown("---")
            st.warning(
                "📢 **AVISO LEGAL:** O placar sugerido é uma estimativa baseada em I.A. Aposte com responsabilidade.")

    elif not autorizado:
        st.warning("Aguardando login para liberar os dados de I.A.")
    else:
        st.write("Selecione um jogo e gere a análise para ver as estatísticas.")

# -----------------------------
# DASHBOARD ESTATÍSTICO (RODAPÉ ADMIN)
# -----------------------------
if autorizado and st.session_state.get("nivel") == 1:
    st.markdown("---")
    st.subheader("📊 Painel de Controle Analítico")

    try:
        # Busca logs do Firebase
        logs_ref = db.collection('logs').order_by(
            "data_hora", direction=firestore.Query.DESCENDING).limit(100)
        logs_docs = logs_ref.stream()
        logs_list = [d.to_dict() for d in logs_docs]
        df_stats = pd.DataFrame(logs_list)

        if not df_stats.empty:
            # Firebase já retorna datetime, só formatamos para o gráfico
            df_stats['dia'] = df_stats['data_hora'].dt.strftime('%d/%m/%Y')

            col_graph1, col_graph2 = st.columns(2)
            with col_graph1:
                contagem_dia = df_stats.groupby(
                    'dia').size().reset_index(name='total')
                fig_vol = px.line(contagem_dia, x='dia', y='total',
                                  title="📈 Uso Diário", template="plotly_dark")
                fig_vol.update_xaxes(type='category')
                st.plotly_chart(fig_vol, use_container_width=True)

            with col_graph2:
                dist_acao = df_stats['acao'].value_counts().reset_index()
                dist_acao.columns = ['Ação', 'Qtd']
                fig_pizza = px.pie(dist_acao, values='Qtd',
                                   names='Ação', title="🍕 Operações")
                st.plotly_chart(fig_pizza, use_container_width=True)
    except Exception as e:
        st.error(f"Erro ao carregar dashboard: {e}")

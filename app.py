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
import mercadopago
import qrcode
from io import BytesIO
from firebase_admin import auth

# --- 1. INICIALIZAÇÃO IMEDIATA DO ESTADO ---
# Isso garante que o comando abaixo não dê erro de "KeyError" ou "AttributeError"
if "logado" not in st.session_state:
    st.session_state.logado = False
if "nome_exibicao" not in st.session_state:
    st.session_state.nome_exibicao = ""
if "usuario" not in st.session_state:
    st.session_state.usuario = None

# -----------------------------
# 2. CONFIGURAÇÕES INICIAIS
# -----------------------------
st.set_page_config(
    page_title="FOOBOT PRO - FOOBOT I.A",
    page_icon="assets/favicon.png",
    layout="wide",
    initial_sidebar_state="expanded" if not st.session_state.get(
        "logado") else "collapsed"
)

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

# Pega o Token do MP dos Secrets
MP_TOKEN = st.secrets["MP_ACCESS_TOKEN"]

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


def gerar_pix_mp(valor, usuario_id):
    # Use seu token APP_USR
    sdk = mercadopago.SDK(
        MP_TOKEN)

    payment_data = {
        "transaction_amount": float(valor),
        "description": f"Créditos FOObot - {usuario_id}",
        "payment_method_id": "pix",
        "external_reference": usuario_id,  # ISSO É O QUE O MAKE VAI LER
        # Sua URL da imagem
        "notification_url": st.secrets["MAKE_WEBHOOK_URL"],
        "payer": {
            "email": f"{usuario_id}@foobot.com",
            "first_name": usuario_id
        }
    }

    payment_response = sdk.payment().create(payment_data)
    return payment_response["response"]


def gerar_imagem_qrcode(conteudo_pix):
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(conteudo_pix)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    # Converte a imagem para um formato que o Streamlit aceita (Bytes)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@st.dialog("Finalizar Pagamento")
def mostrar_tela_pagamento(valor, label):
    st.write(f"Você escolheu o pacote: **{label}**")
    st.write(f"Valor a pagar: **R$ {valor:.2f}**")

    with st.spinner("Gerando Pix..."):
        user_id = st.session_state.get('usuario', 'desconhecido')
        dados = gerar_pix_mp(valor, user_id)

        if 'point_of_interaction' in dados:
            pix_code = dados['point_of_interaction']['transaction_data']['qr_code']

            # Gerar a imagem do QR Code
            img_qr = gerar_imagem_qrcode(pix_code)

            # Centralizar imagem e código
            col_qr, col_txt = st.columns([1, 1])

            with col_qr:
                st.image(img_qr, caption="Escaneie com o app do seu banco")

            with col_txt:
                st.markdown("### 🔑 Pix Copia e Cola")

                # --- BOTÃO DE COPIAR VIA HTML/JS (Não recarrega a página) ---
                button_html = f"""
                <button onclick="navigator.clipboard.writeText('{pix_code}').then(() => alert('Chave Pix Copiada!'))" 
                    style="
                        width: 100%;
                        background-color: #2ecc71;
                        color: white;
                        border: none;
                        padding: 10px;
                        border-radius: 5px;
                        cursor: pointer;
                        font-weight: bold;
                        margin-top: 10px;
                    ">
                    📋 COPIAR CHAVE PIX
                </button>
                """
                st.components.v1.html(button_html, height=60)

                st.write("")
                st.success("✅ O saldo cairá automaticamente!")

            st.warning(
                "⚠️ Não feche esta janela até concluir o pagamento para garantir a confirmação.")

            if st.button("Concluí o pagamento!"):
                st.rerun()
        else:
            st.error("Erro ao conectar com o Mercado Pago. Tente novamente.")

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


def autocadastro_firebase(nome_completo, login_id, email, senha):
    try:
        # 1. Cria no AUTHENTICATION (Cofre do Google)
        user_record = auth.create_user(
            email=email, password=senha, uid=login_id, display_name=nome_completo
        )

        # 2. Cria no FIRESTORE (Sua carteira de créditos - SEM SENHA)
        user_data = {
            "exibicao": nome_completo.split()[0],
            "usuario": login_id,
            "email": email,
            "creditos": 0.0,
            "nivel": 0,
            "bonus_recebido": False,
            "vitalicio": False,
            "analises_liberadas": [],
            "data_cadastro": datetime.datetime.now(pytz.timezone("America/Sao_Paulo"))
        }
        db.collection('usuarios').document(login_id).set(user_data)
        registrar_log_firebase(login_id, "AUTOCADASTRO",
                               "Conta criada com sucesso.")
        return True, user_data
    except Exception as e:
        return False, str(e)


def verificar_login_auth(email_ou_user, senha):
    """
    Valida as credenciais no Firebase Auth. 
    Retorna o UID (Login) se estiver correto, ou None se falhar.
    """
    try:
        # 1. Se o cara digitou o Login (ID), precisamos do e-mail dele para o Auth
        email_final = email_ou_user
        uid_final = email_ou_user

        if "@" not in email_ou_user:
            user_doc = db.collection('usuarios').document(email_ou_user).get()
            if user_doc.exists:
                email_final = user_doc.to_dict().get('email')
            else:
                return None, "Usuário não encontrado."
        else:
            # Se digitou email, buscamos o UID no Firestore
            query = db.collection('usuarios').where(
                "email", "==", email_ou_user).get()
            if query:
                uid_final = query[0].id
            else:
                return None, "E-mail não cadastrado."

        # 2. No Admin SDK não existe 'sign_in_with_password'.
        # O padrão profissional é usar a REST API do Google para validar a senha:
        import requests
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={st.secrets['FIREBASE_WEB_API_KEY']}"
        payload = {"email": email_final,
                   "password": senha, "returnSecureToken": True}
        r = requests.post(url, json=payload)

        if r.status_code == 200:
            return uid_final, "Sucesso"
        else:
            return None, "Senha incorreta ou erro de acesso."
    except Exception as e:
        return None, str(e)


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
# MONITOR DE PAGAMENTO AUTOMÁTICO
# -----------------------------


@st.fragment(run_every=5)  # Verifica o Firebase a cada 5 segundos
def monitorar_pagamento_real():
    if st.session_state.get("logado"):
        user_id = st.session_state.usuario
        # Busca apenas o campo necessário para economizar processamento
        user_ref = db.collection('usuarios').document(user_id)
        doc = user_ref.get()

        if doc.exists:
            dados = doc.to_dict()
            id_no_firebase = dados.get("ultimo_id_pagamento")

            # SÓ DISPARA SE O ID FOR DIFERENTE DO QUE SALVAMOS NO LOGIN
            if id_no_firebase and id_no_firebase != st.session_state.get("id_pago_visto"):
                st.balloons()
                st.toast(
                    f"✅ CRÉDITO ADICIONADO! Seu novo saldo é: {dados.get('creditos', 0):.1f}", icon="💰")
                # Salva que já vimos esse ID para não repetir o aviso
                st.session_state.id_pago_visto = id_no_firebase
                time.sleep(4)
                st.rerun()


# -----------------------------
# SIDEBAR (LOGIN, GESTÃO DE ACESSO E CRÉDITOS)
# -----------------------------

# --- SIDEBAR ESTILIZADA ---
st.sidebar.markdown("### 👤 Área do Usuário")
st.sidebar.markdown("---")

if not st.session_state.get("logado", False):
    # Aqui criamos as abas para o usuário escolher entre entrar ou criar conta
    tab_login, tab_cadastro = st.sidebar.tabs(["🚀 Entrar", "📝 Criar Conta"])

    with tab_login:
        identificador = st.text_input(
            "Usuário ou E-mail:", key="login_id").strip().lower()
        senha_login = st.text_input(
            "Senha:", type="password", key="login_pass")

        col_btn_in, col_btn_forgot = st.columns([1, 1.6])

        with col_btn_in:
            if st.button("🚀 Entrar", use_container_width=True, key="btn_login_real"):
                if identificador and senha_login:
                    with st.spinner("Validando..."):
                        # 1. Busca o e-mail se o cara digitou o login
                        email_final = identificador
                        if "@" not in identificador:
                            user_doc = db.collection(
                                'usuarios').document(identificador).get()
                            if user_doc.exists:
                                email_final = user_doc.to_dict().get('email')
                            else:
                                st.error("Usuário não encontrado.")
                                st.stop()

                        # 2. Valida a senha na API do Google
                        import requests
                        url_auth = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={st.secrets['FIREBASE_WEB_API_KEY']}"
                        payload = {
                            "email": email_final, "password": senha_login, "returnSecureToken": True}
                        r = requests.post(url_auth, json=payload)

                        if r.status_code == 200:
                            # 3. Puxa os dados reais do Firestore para a sessão
                            query = db.collection('usuarios').where(
                                "email", "==", email_final).get()
                            user_data = query[0].to_dict()

                            st.session_state.logado = True
                            st.session_state.usuario = user_data.get('usuario')
                            st.session_state.nome_exibicao = user_data.get(
                                'exibicao')
                            st.session_state.nivel = int(
                                user_data.get('nivel', 0))
                            st.session_state.vitalicio = user_data.get(
                                'vitalicio', False)
                            st.balloons()
                            st.rerun()
                        else:
                            st.error("Senha incorreta!")
                else:
                    st.warning("Preencha os campos!")

        with col_btn_forgot:
            if st.button("🔑 Esqueci a senha", use_container_width=True):
                if identificador:
                    try:
                        # 1. Descobrir o e-mail
                        email_reset = identificador
                        if "@" not in identificador:
                            doc = db.collection('usuarios').document(
                                identificador).get()
                            if doc.exists:
                                email_reset = doc.to_dict().get('email')
                            else:
                                st.error("Usuário não encontrado.")
                                st.stop()

                        # 2. DISPARAR E-MAIL REAL VIA REST API DO GOOGLE
                        import requests
                        api_key = st.secrets["FIREBASE_WEB_API_KEY"]
                        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"
                        payload = {"requestType": "PASSWORD_RESET",
                                   "email": email_reset}

                        response = requests.post(url, json=payload)

                        if response.status_code == 200:
                            st.success(f"E-mail enviado para {email_reset}!")
                            st.warning(
                                "🚨 **ATENÇÃO:** O link pode cair na sua pasta de **SPAM** ou **LIXO ELETRÔNICO**. Verifique lá!")
                        else:
                            st.error(
                                "Erro ao solicitar o e-mail. Verifique se o endereço está correto.")

                    except Exception as e:
                        st.error(f"Erro no processo: {e}")
                else:
                    st.warning("Digite seu login ou e-mail acima.")

    with tab_cadastro:
        st.markdown("🎁 Ganhe **5 créditos** ao criar sua conta!")

        # Criamos um formulário para evitar que a página recarregue a cada campo digitado
        with st.form("form_cadastro", clear_on_submit=False):
            reg_nome = st.text_input("Nome Completo:")
            reg_user = st.text_input(
                "Nome de Usuário (login):").strip().lower()
            reg_email = st.text_input("E-mail:").strip().lower()
            reg_pass = st.text_input(
                "Senha (mín. 6 caracteres):", type="password")
            reg_pass2 = st.text_input("Repita a Senha:", type="password")

            # No st.form, o botão PRECISA ser o st.form_submit_button
            btn_registrar = st.form_submit_button(
                "Finalizar Cadastro 🚀", use_container_width=True)

        if btn_registrar:
            if not all([reg_nome, reg_user, reg_email, reg_pass, reg_pass2]):
                st.warning("Preencha todos os campos!")
            elif reg_pass != reg_pass2:
                st.error("As senhas não conferem!")
            elif len(reg_pass) < 6:
                st.error("A senha deve ter pelo menos 6 caracteres!")
            else:
                try:
                    # Chama sua função de cadastro (que já cria no Auth e Firestore)
                    sucesso, user_info = autocadastro_firebase(
                        reg_nome, reg_user, reg_email, reg_pass)

                    if sucesso:
                        st.session_state.logado = True
                        st.session_state.usuario = reg_user
                        st.session_state.nome_exibicao = user_info["exibicao"]
                        st.session_state.nivel = 0
                        st.session_state.vitalicio = False

                        st.balloons()
                        st.success(f"Bem-vindo, {user_info['exibicao']}!")
                        time.sleep(2)
                        st.rerun()
                    else:
                        st.error(f"Erro: {user_info}")
                except Exception as e:
                    st.error(f"Erro crítico: {str(e)}")

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
        if st.sidebar.button("🔄 Atualizar Saldo"):
            st.rerun()

        # Opcional: Se quiser manter o selo de "Variável" de forma discreta
        st.sidebar.error("🔻 Consumo Variável")

        st.sidebar.info("Plano: **Gold Básico**")

        # ----- CARD PARA COMPRAR CRÉDITOS ----
        with st.sidebar.expander("💳 COMPRAR CRÉDITOS", expanded=False):
            st.markdown("### ✨ Escolha seu pacote")

            # Criamos os pacotes: (Nome, Quantidade de Créditos, Preço)
            pacotes = [
                {"label": "🥉 10 Créditos", "qtd": 10, "preco": 7.50},
                {"label": "🥈 20 Créditos", "qtd": 20, "preco": 15.00},
                {"label": "🥇 50 Créditos", "qtd": 50, "preco": 37.50},
                {"label": "💎 100 Créditos", "qtd": 100, "preco": 75.00},
            ]

            # Renderiza os botões/cards
            for p in pacotes:
                with st.container(border=True):
                    col_info, col_btn = st.columns([1.2, 1])
                    with col_info:
                        st.markdown(f"**{p['label']}**")
                        st.caption(f"Valor: R$ {p['preco']:.2f}")
                    with col_btn:
                        # Se clicar, abre o modal de pagamento
                        if st.button(f"Comprar", key=f"compra_{p['qtd']}"):
                            mostrar_tela_pagamento(p['preco'], p['label'])

            st.markdown("---")
            st.caption("💡 1 crédito = R$ 0.75")

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
                    df_view[['exibicao', 'creditos']], hide_index=True)

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
        # 🚨 TRAVA DE SEGURANÇA CRÍTICA
        if not jogo_id:
            st.error("❌ Erro: ID do jogo não encontrado. Feche esta janela e tente novamente.")
            return
        
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
# st.title("⚽ FOOBOT PRO v5 - FOOBOT I.A")
# --- LOGO PRINCIPAL (Header) NO CANTO ESQUERDO ---
# Criamos duas colunas. A primeira para a logo, e a segunda maior para o respiro.
# Uma proporção de [1, 3.5] costuma deixar a logo num tamanho médio/bonito no canto.
col_logo_esquerda, col_logo_respiro = st.columns([1, 2.0])

with col_logo_esquerda:
    # use_container_width=True faz a imagem preencher toda a coluna que criamos
    # Se você achar que ficou muito grande, aumente o segundo número (ex: [1, 4.5])
    st.image("assets/logo_sem_fundo.png", use_container_width=True)


# CHAMADA DO MONITOR (Sempre rodando no background)
if st.session_state.get("logado"):
    monitorar_pagamento_real()

# EXIBIÇÃO DO BROADCAST COM EMOJI ALEATÓRIO
msg_global = gerenciar_broadcast_firebase()
if msg_global:
    # Lista de emojis para dar aquele grau no visual
    emojis = ["📢", "🔔", "⚠️", "🔥", "🚀", "💡", "⚽", "🏆"]
    icon = random.choice(emojis)

    st.info(f"{icon} **AVISO:** {msg_global}")

st.markdown("---")

# -----------------------------
# INTERFACE PRINCIPAL COM ABAS
# -----------------------------
if autorizado:
    # 1. BUSCA DADOS PARA VERIFICAR SE ESTÁ COMPLETO
    u_ref_aviso = db.collection('usuarios').document(st.session_state.usuario)
    u_dados_aviso = u_ref_aviso.get().to_dict()

    # Verifica se falta CPF ou Telefone
    cadastro_incompleto = not u_dados_aviso.get(
        'cpf') or not u_dados_aviso.get('telefone')

    # 🚀 Controlar qual aba está aberta
    if "aba_ativa" not in st.session_state:
        st.session_state.aba_ativa = 0  # 0 é a aba de Jogos

    # Criamos as abas para separar o Jogo do Perfil
    tab_jogos, tab_perfil = st.tabs(["⚽ Analisador de Jogos", "👤 Meu Perfil"])

    with tab_jogos:
        if cadastro_incompleto:
            # Criamos um container bonitão para o aviso
            with st.container(border=True):
                st.info(
                    "🎁 **BÔNUS DISPONÍVEL:** Você tem **5 CRÉDITOS GRÁTIS** esperando! Complete seu cadastro para liberar.")

                # O botão que faz a mágica
                if st.button("CLIQUE AQUI PARA COMPLETAR AGORA ➔", use_container_width=True):
                    # Como o Streamlit não permite mudar o índice do st.tabs via código direto facilmente,
                    # a gente usa esse alerta visual e instrução rápida:
                    st.warning(
                        "⬆️ **QUASE LÁ!** Clique na aba **'👤 Meu Perfil'** bem ali no topo da tela para ganhar seus créditos!")
                    st.balloons()  # Um incentivo extra kkk

        # CÓDIGO ORIGINAL DE COLUNAS
        col1, col2 = st.columns([1, 2])

        with col1:
            st.subheader("🏆 Seleção de Partida")
            btn_analise = False

            fuso_br = pytz.timezone("America/Sao_Paulo")
            agora_br = datetime.datetime.now(fuso_br)
            hoje_br = agora_br.date()
            hora_atual_str = agora_br.strftime("%H:%M")

            date = st.date_input(
                "📅 Selecione a data para buscar jogos:",
                value=hoje_br,
                min_value=hoje_br,
                format="DD/MM/YYYY",
                on_change=limpar_analise
            )

            if date:
                if date < hoje_br:
                    st.error(
                        "🚫 Não é permitido analisar jogos que já aconteceram!")
                    st.stop()

                date_str = date.strftime("%Y-%m-%d")
                data_formatada = date.strftime("%d/%m/%Y")

                with st.spinner(f"Buscando partidas do dia {data_formatada}..."):
                    all_matches = []
                    leagues_found = []

                    # Busca API 1
                    for league_name, league_code in LEAGUES.items():
                        matches_api1 = get_matches(league_code, date_str)
                        if matches_api1:
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
                            if jogos_da_liga:
                                all_matches.extend(jogos_da_liga)
                                if league_name not in leagues_found:
                                    leagues_found.append(league_name)

                    # Busca API 2
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

                all_matches = sorted(all_matches, key=lambda x: x['horario'])

                if all_matches:
                    sel_league = st.selectbox(
                        "Escolha a Liga", ["🌍 Todas"] + leagues_found, on_change=limpar_analise)
                    filtered = [m for m in all_matches if sel_league ==
                                "🌍 Todas" or m['league_display'] == sel_league]

                    match_display_options = []
                    for m in filtered:
                        if date == hoje_br and m['horario'] <= hora_atual_str:
                            match_display_options.append(
                                f"🔴 [INDISP.] {m['home']} x {m['away']}")
                        else:
                            match_display_options.append(m['name'])

                    selected_display = st.selectbox(
                        "Escolha o Jogo", match_display_options, on_change=limpar_analise)
                    idx = match_display_options.index(selected_display)
                    jogo = filtered[idx]

                    liga_limpa = jogo['league_name'].replace(" ", "_")
                    jogo_id_atual = f"{jogo['home']}_{jogo['away']}_{liga_limpa}_{date_str}"

                    esta_bloqueado = "INDISP." in selected_display
                    user_doc = db.collection('usuarios').document(
                        st.session_state.usuario).get().to_dict()
                    liberados = user_doc.get("analises_liberadas", [])
                    ja_pagou = jogo_id_atual in liberados

                    if esta_bloqueado:
                        st.button("🚫 ANÁLISE BLOQUEADA",
                                  disabled=True, use_container_width=True)
                        st.error("📉 **Por que esta partida está bloqueada?**")
                        st.info("O FOOBOT PRO realiza apenas análises pré-jogo.")
                    else:
                        if ja_pagou:
                            st.success("✅ Você já possui acesso!")
                            st.button("👁️ ANÁLISE LIBERADA",
                                      disabled=True, use_container_width=True)
                            texto_reanalise = "🔄 REANALISAR PARTIDA AGORA"
                            if not st.session_state.get('vitalicio'):
                                texto_reanalise += " (-0.5)"
                            if st.button(texto_reanalise, use_container_width=True):
                                modal_confirmar_reanalise(jogo, jogo_id_atual)
                        else:
                            btn_analise = st.button(
                                "🚀 GERAR ANÁLISE PREMIUM", use_container_width=True)

        with col2:
            st.subheader("📊 Análise de Inteligência")

            # 🛡️ SÓ ENTRA SE UM JOGO ESTIVER SELECIONADO
            if 'jogo' in locals() and jogo and jogo_id_atual:

                if btn_analise:
                    user_ref_check = db.collection('usuarios').document(
                        st.session_state.usuario).get()
                    saldo_antes = float(
                        user_ref_check.to_dict().get('creditos', 0))

                    if saldo_antes < 1.0 and not st.session_state.get('vitalicio'):
                        st.error(f"❌ Saldo insuficiente ({saldo_antes}).")
                    else:
                        with st.spinner(f"Analisando {jogo['home']} x {jogo['away']}..."):
                            resultado = realizar_analise_gemini(
                                jogo['home'], jogo['away'], jogo['league_name'])

                            if "atingiram o limite" not in resultado:
                                st.session_state.ultima_analise = resultado
                                descontar_credito_firebase(
                                    st.session_state.usuario, jogo_id_atual)

                                # 🚀 GRAVA NO CACHE (Protegido pelo IF lá de cima)
                                db.collection('analises_cache').document(jogo_id_atual).set({
                                    'texto': resultado,
                                    'data': datetime.datetime.now(pytz.timezone("America/Sao_Paulo"))
                                })

                                registrar_log_firebase(
                                    st.session_state.usuario, "CONSULTA", f"{jogo['home']} x {jogo['away']}")
                                st.rerun()

                if ja_pagou:
                    # 🚀 BUSCA NO CACHE (Protegido pelo IF lá de cima)
                    if not st.session_state.get('ultima_analise'):
                        cache_ref = db.collection(
                            'analises_cache').document(jogo_id_atual).get()
                        if cache_ref.exists:
                            st.session_state.ultima_analise = cache_ref.to_dict().get('texto')

                    if st.session_state.get('ultima_analise'):
                        st.markdown(st.session_state.ultima_analise)
                        probs = extrair_probabilidades(
                            st.session_state.ultima_analise)
                        df_probs = pd.DataFrame(
                            {'Resultado': ['Casa', 'Empate', 'Fora'], 'Probabilidade (%)': probs})
                        fig = px.bar(df_probs, x='Probabilidade (%)', y='Resultado', orientation='h', text='Probabilidade (%)',
                                     color='Resultado', color_discrete_map={'Casa': '#2ecc71', 'Empate': '#95a5a6', 'Fora': '#e74c3c'})
                        st.plotly_chart(fig, use_container_width=True)

            else:
                # Caso o ID ainda não exista (usuário acabou de logar e não mexeu em nada)
                st.info(
                    "👋 Escolha uma partida na coluna ao lado para iniciar a análise.")

    with tab_perfil:
        st.subheader("👤 Configurações do Perfil")

        # 1. BUSCA DADOS SEMPRE QUE ENTRA NA ABA (Garante dado novo)
        u_ref = db.collection('usuarios').document(st.session_state.usuario)
        u_dados = u_ref.get().to_dict()

        with st.form("meu_perfil_form"):
            c1, c2 = st.columns(2)
            p_nome = c1.text_input("Nome de Exibição:",
                                   value=u_dados.get('exibicao', ''))
            p_whatsapp = c1.text_input(
                "WhatsApp (apenas números):", value=u_dados.get('telefone', ''))
            p_cpf = c2.text_input("CPF (apenas números):",
                                  value=u_dados.get('cpf', ''), max_chars=11)
            c2.info(f"**E-mail:** {u_dados.get('email')}")

            btn_salvar = st.form_submit_button(
                "💾 Salvar e Validar Perfil", use_container_width=True)

        if btn_salvar:
            # --- FUNÇÃO INTERNA DE VALIDAÇÃO DE CPF ---
            def validar_cpf(cpf_num):
                cpf_num = ''.join(filter(str.isdigit, cpf_num))
                if len(cpf_num) != 11 or cpf_num == cpf_num[0] * 11:
                    return False
                for i in range(9, 11):
                    soma = sum(int(cpf_num[num]) * ((i + 1) - num)
                               for num in range(i))
                    digito = (soma * 10 % 11) % 10
                    if digito != int(cpf_num[i]):
                        return False
                return True

            # --- FLUXO DE VALIDAÇÕES ---
            if not p_nome or not p_whatsapp or not p_cpf:
                st.error("⚠️ Preencha todos os campos para continuar.")

            elif not validar_cpf(p_cpf):
                st.error("❌ CPF inválido! Verifique os números digitados.")

            else:
                # 2. VERIFICA DUPLICIDADE (Telefone e CPF)
                # Procura Telefone
                outros_tel = db.collection('usuarios').where(
                    'telefone', '==', p_whatsapp).get()
                # Procura CPF
                outros_cpf = db.collection('usuarios').where(
                    'cpf', '==', p_cpf).get()

                # Filtra pra ver se pertencem a OUTROS usuários
                conflito_tel = any(
                    doc.id != st.session_state.usuario for doc in outros_tel)
                conflito_cpf = any(
                    doc.id != st.session_state.usuario for doc in outros_cpf)

                if conflito_tel:
                    st.error("❌ Este WhatsApp já está em uso por outro usuário.")
                elif conflito_cpf:
                    st.error("❌ Este CPF já está vinculado a outra conta.")
                else:
                    # 3. TUDO OK - PREPARA SALVAMENTO
                    updates = {
                        "exibicao": p_nome,
                        "telefone": p_whatsapp,
                        "cpf": p_cpf
                    }

                    # Lógica do Bônus
                    foi_bonificado = u_dados.get('bonus_recebido', False)
                    if not foi_bonificado:
                        updates["creditos"] = u_dados.get('creditos', 0) + 5.0
                        updates["bonus_recebido"] = True
                        st.balloons()
                        st.success(
                            "🔥 SUCESSO! Você ganhou 5 créditos de bônus!")
                        registrar_log_firebase(
                            st.session_state.usuario, "BÔNUS", "Perfil Completo +5")
                    else:
                        st.success("✅ Perfil atualizado com sucesso!")

                    # Grava no banco e força o REFRESH
                    u_ref.update(updates)
                    st.session_state.nome_exibicao = p_nome
                    time.sleep(1.5)
                    st.rerun()  # 🚀 Aqui ele limpa o cache e recarrega tudo novo

        st.markdown("---")
        st.subheader("🔐 Segurança")
        st.write(
            "Clique abaixo para receber um link de troca de senha no seu e-mail.")

        if st.button("🔑 Enviar Link de Nova Senha", use_container_width=True):
            import requests
            import json
            api_key = st.secrets["FIREBASE_WEB_API_KEY"]
            url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"

            payload = json.dumps({
                "requestType": "PASSWORD_RESET",
                "email": u_dados.get('email')
            })

            with st.spinner("Solicitando ao Google..."):
                r = requests.post(url, data=payload)

                if r.status_code == 200:
                    st.success(
                        "✅ Sucesso! O link foi enviado para o seu e-mail cadastrado.")
                    st.info(
                        "Verifique a pasta de SPAM se não encontrar na caixa de entrada.")
                else:
                    st.error(
                        "❌ Não foi possível solicitar o link agora. Tente novamente em instantes.")

else:
    st.error("🔒 Área Restrita - Faça login na lateral clicando no ícone ' >> ' no canto superior esquerdo.")

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

import streamlit as st
import pandas as pd
import plotly.express as px
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
import hashlib

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Wan Shi Tong Library", layout="wide", page_icon="🦉")

# --- CSS E ESTILO ---
st.markdown("""
<style>
    .stMetric {background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px;}
    div[data-testid="stExpander"] {background-color: #161616; border: 1px solid #333; border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

# --- ESTADO DE SESSÃO ---
if 'user' not in st.session_state: st.session_state.user = None
if 'edit_id' not in st.session_state: st.session_state.edit_id = None
if 'serie_manager_id' not in st.session_state: st.session_state.serie_manager_id = None

# --- CONEXÃO ---
conn = st.connection("postgresql", type="sql")

def init_db():
    with conn.session as s:
        # Tabela de Usuários e Senhas
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            );
        '''))
        
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS midia (
                id SERIAL PRIMARY KEY,
                titulo TEXT NOT NULL,
                tipo TEXT NOT NULL,
                plataforma TEXT,
                status TEXT NOT NULL,
                nota REAL,
                comentario TEXT,
                data_registro DATE,
                capa_url TEXT,
                nickname TEXT,
                data_inicio DATE,
                data_fim DATE,
                travar_nota INTEGER DEFAULT 0,
                dono TEXT
            );
        '''))
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS episodios (
                id SERIAL PRIMARY KEY,
                serie_id INTEGER,
                episodio_num INTEGER,
                titulo_ep TEXT,
                nota REAL,
                data_assistido DATE,
                FOREIGN KEY(serie_id) REFERENCES midia(id) ON DELETE CASCADE
            );
        '''))
        s.commit()

# --- AUTENTICAÇÃO ---
def hash_pass(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    user_clean = username.strip().lower()
    pass_hash = hash_pass(password)
    try:
        with conn.session as s:
            # Verifica se já existe
            exists = s.execute(text("SELECT username FROM users WHERE username=:u"), {"u": user_clean}).fetchone()
            if exists:
                st.error("Usuário já existe. Tente outro.")
                return False
            
            s.execute(text("INSERT INTO users (username, password) VALUES (:u, :p)"), {"u": user_clean, "p": pass_hash})
            s.commit()
        st.success("Cadastro realizado! Faça login.")
        return True
    except Exception as e:
        st.error(f"Erro no cadastro: {e}")
        return False

def login_user(username, password):
    user_clean = username.strip().lower()
    pass_hash = hash_pass(password)
    try:
        user_data = conn.query("SELECT * FROM users WHERE username=:u AND password=:p", params={"u": user_clean, "p": pass_hash}, ttl=0)
        if not user_data.empty:
            st.session_state.user = user_clean
            st.rerun()
        else:
            st.error("Usuário ou senha incorretos.")
    except Exception as e:
        st.error(f"Erro no login: {e}")

# --- CRUD (Mantido similar, com nickname automático) ---

def add_midia(titulo, tipo, plataforma, status, nota, comentario, data_reg, capa_url, nickname, d_ini, d_fim, dono):
    try:
        with conn.session as s:
            s.execute(
                text('''
                INSERT INTO midia (titulo, tipo, plataforma, status, nota, comentario, data_registro, capa_url, nickname, data_inicio, data_fim, dono) 
                VALUES (:t, :tp, :p, :s, :n, :c, :dr, :url, :nick, :di, :df, :owner)
                '''),
                {
                    "t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, 
                    "c": comentario, "dr": data_reg, "url": capa_url, "nick": nickname, 
                    "di": d_ini, "df": d_fim, "owner": dono
                }
            )
            s.commit()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

def update_midia(id_item, titulo, nota, comentario, dono):
    try:
        with conn.session as s:
            s.execute(
                text('''
                UPDATE midia 
                SET titulo=:t, nota=:n, comentario=:c
                WHERE id=:id AND dono=:owner
                '''),
                {"t": titulo, "n": nota, "c": comentario, "id": id_item, "owner": dono}
            )
            s.commit()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")

def delete_midia(id_item, dono):
    try:
        with conn.session as s:
            res = s.execute(text("SELECT id FROM midia WHERE id=:id AND dono=:owner"), {"id": id_item, "owner": dono}).fetchone()
            if res:
                s.execute(text('DELETE FROM episodios WHERE serie_id=:id'), {"id": id_item})
                s.execute(text('DELETE FROM midia WHERE id=:id'), {"id": id_item})
                s.commit()
            else:
                st.error("Erro de permissão.")
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao deletar: {e}")

def get_data(dono, tipo_filtro=None):
    query = "SELECT * FROM midia WHERE dono = :owner"
    params = {"owner": dono}
    if tipo_filtro: 
        query += " AND tipo = :tp"
        params["tp"] = tipo_filtro
    
    df = conn.query(query, params=params, ttl=0)
    
    if not df.empty:
        df['data_registro'] = pd.to_datetime(df['data_registro'], errors='coerce')
        df['data_inicio'] = pd.to_datetime(df['data_inicio'], errors='coerce')
        df['data_fim'] = pd.to_datetime(df['data_fim'], errors='coerce')
        df['ano'] = df['data_registro'].dt.year
        df['mes_nome'] = df['data_registro'].dt.month_name()
        if 'nickname' not in df.columns: df['nickname'] = ""
        df['nickname'] = df['nickname'].fillna("")
        df['nota'] = pd.to_numeric(df['nota'], errors='coerce').fillna(0.0)
    return df

# --- EPISODIOS ---
def add_episodio(serie_id, ep_num, titulo, nota, data):
    with conn.session as s:
        s.execute(
            text('INSERT INTO episodios (serie_id, episodio_num, titulo_ep, nota, data_assistido) VALUES (:sid, :enum, :tit, :nt, :dt)'),
            {"sid": serie_id, "enum": ep_num, "tit": titulo, "nt": nota, "dt": data}
        )
        s.commit()
    st.cache_data.clear()
    recalcular_nota_serie(serie_id)

def recalcular_nota_serie(serie_id):
    df_midia = conn.query("SELECT travar_nota FROM midia WHERE id=:id", params={"id": serie_id}, ttl=0)
    if not df_midia.empty and df_midia.iloc[0]['travar_nota'] == 1: return

    res = conn.query("SELECT AVG(nota) as media, MIN(data_assistido) as inicio, MAX(data_assistido) as fim FROM episodios WHERE serie_id=:id", params={"id": serie_id}, ttl=0)
    
    if not res.empty:
        nova_media = res.iloc[0]['media'] if res.iloc[0]['media'] is not None else 0
        d_ini = res.iloc[0]['inicio']
        d_fim = res.iloc[0]['fim']
        with conn.session as s:
            if d_ini and d_fim:
                s.execute(text("UPDATE midia SET nota=:n, data_inicio=:di, data_fim=:df WHERE id=:id"), {"n": float(nova_media), "di": d_ini, "df": d_fim, "id": serie_id})
            else:
                s.execute(text("UPDATE midia SET nota=:n WHERE id=:id"), {"n": float(nova_media), "id": serie_id})
            s.commit()

def get_episodios(serie_id):
    df = conn.query("SELECT * FROM episodios WHERE serie_id=:id ORDER BY episodio_num", params={"id": serie_id}, ttl=0)
    if not df.empty: df['data_assistido'] = pd.to_datetime(df['data_assistido'])
    return df

def salvar_edicao_tabela_eps(serie_id, edits):
    if not edits: return
    with conn.session as s:
        df_orig = get_episodios(serie_id)
        for idx, changes in edits['edited_rows'].items():
            if int(idx) < len(df_orig):
                ep_id = int(df_orig.iloc[int(idx)]['id'])
                for col_name, new_val in changes.items():
                    if col_name == "data_assistido": s.execute(text("UPDATE episodios SET data_assistido=:v WHERE id=:id"), {"v": pd.to_datetime(new_val).date(), "id": ep_id})
                    elif col_name == "episodio_num": s.execute(text("UPDATE episodios SET episodio_num=:v WHERE id=:id"), {"v": new_val, "id": ep_id})
                    elif col_name == "titulo_ep": s.execute(text("UPDATE episodios SET titulo_ep=:v WHERE id=:id"), {"v": new_val, "id": ep_id})
                    elif col_name == "nota": s.execute(text("UPDATE episodios SET nota=:v WHERE id=:id"), {"v": new_val, "id": ep_id})
        for idx in edits['deleted_rows']:
             if int(idx) < len(df_orig):
                ep_id = int(df_orig.iloc[int(idx)]['id'])
                s.execute(text("DELETE FROM episodios WHERE id=:id"), {"id": ep_id})
        s.commit()
    st.cache_data.clear()
    recalcular_nota_serie(serie_id)
    st.toast("Atualizado!")

# --- CARD GENERATOR ---
def gerar_card(titulo, nota, comentario, url_imagem, nickname):
    try:
        response = requests.get(url_imagem, timeout=3)
        img = Image.open(BytesIO(response.content)).convert("RGBA")
    except: img = Image.new('RGB', (400, 600), color='#2b2b2b')
    largura_fixa = 400
    percentual = (largura_fixa / float(img.size[0]))
    altura_dinamica = int((float(img.size[1]) * float(percentual)))
    img = img.resize((largura_fixa, altura_dinamica), Image.Resampling.LANCZOS)
    altura_rodape = 160
    altura_total = altura_dinamica + altura_rodape
    card = Image.new('RGB', (largura_fixa, altura_total), (15, 15, 15))
    card.paste(img, (0, 0))
    draw = ImageDraw.Draw(card)
    
    if nota is not None and nota > 0:
        if nota >= 75: cor_badge, cor_txt = '#FFD700', '#000000'
        elif nota >= 50: cor_badge, cor_txt = '#C0C0C0', '#000000'
        else: cor_badge, cor_txt = '#B22222', '#FFFFFF'
        diametro, margem = 70, 20
        x1, y1 = largura_fixa - diametro - margem, margem
        x2, y2 = largura_fixa - margem, margem + diametro
        draw.ellipse((x1, y1, x2, y2), fill=cor_badge)
        try: font_nota = ImageFont.truetype("arial.ttf", 35)
        except: font_nota = ImageFont.load_default()
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        draw.text((cx, cy), str(int(nota)), fill=cor_txt, font=font_nota, anchor="mm")
    
    try: font_titulo = ImageFont.truetype("arial.ttf", 26); font_comm = ImageFont.truetype("arial.ttf", 16); font_nick = ImageFont.truetype("arial.ttf", 14)
    except: font_titulo = font_comm = font_nick = ImageFont.load_default()

    y_texto = altura_dinamica + 20
    draw.text((15, y_texto), f"{titulo[:30]}", fill=(255, 255, 255), font=font_titulo)
    comm_safe = comentario if comentario else ""
    draw.text((15, y_texto + 40), f"\"{comm_safe[:90]}...\"", fill=(200, 200, 200), font=font_comm)
    if nickname:
        txt_nick = f"- {nickname.title()}"
        bbox = draw.textbbox((0, 0), txt_nick, font=font_nick)
        w_nick = bbox[2] - bbox[0]
        draw.text((largura_fixa - w_nick - 15, y_texto + 90), txt_nick, fill=(150, 150, 150), font=font_nick)
    buf = BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()

# --- CALLBACKS UI ---
def salvar_novo_registro():
    t = st.session_state.novo_titulo
    tp = st.session_state.novo_tipo
    p = st.session_state.nova_plataforma
    s = st.session_state.novo_status
    n = st.session_state.nova_nota
    c = st.session_state.novo_comentario
    url = st.session_state.nova_capa
    # AUTOMÁTICO: O nickname agora é o usuário logado!
    nick = st.session_state.user 
    
    d_ini = st.session_state.get('nova_data_inicio', None)
    d_fim = st.session_state.get('nova_data_fim', datetime.now().date())
    if tp not in ["Jogo", "Livro", "Série"]: d_ini = None 
    
    if not t.strip(): st.session_state.msg_erro = ["Título obrigatório."]; return
    
    add_midia(t, tp, p, s, n, c, datetime.now().date(), url, nick, d_ini, d_fim, st.session_state.user)
    st.session_state.novo_titulo = ""
    st.session_state.novo_comentario = ""
    st.session_state.msg_sucesso = f"✅ {t} salvo!"
    st.session_state.msg_erro = None

def render_categoria_page(titulo_pagina, categoria_db, filtro_ano, filtro_mes):
    st.header(f"{titulo_pagina}")
    
    if st.session_state.serie_manager_id is not None and categoria_db == "Série":
        serie_check = conn.query("SELECT * FROM midia WHERE id=:id AND dono=:owner", params={"id": st.session_state.serie_manager_id, "owner": st.session_state.user}, ttl=0)
        if not serie_check.empty:
            serie_info = serie_check.iloc[0]
            with st.container(border=True):
                st.markdown(f"### 📺 Episódios: **{serie_info['titulo']}**")
                c1, c2, c3, c4, c5 = st.columns([1,3,1.5,1.5,1])
                with c1: st.number_input("Ep Nº", min_value=1, value=1, key="ep_num")
                with c2: st.text_input("Título", key="ep_tit")
                with c3: st.date_input("Data", datetime.now(), key="ep_data")
                with c4: st.number_input("Nota", 0, 100, 80, key="ep_nota")
                with c5: 
                    st.write("")
                    st.write("")
                    st.button("➕ Add", on_click=lambda: (add_episodio(st.session_state.serie_manager_id, st.session_state.ep_num, st.session_state.ep_tit, st.session_state.ep_nota, st.session_state.ep_data), st.session_state.update({"ep_tit": ""})))
                
                df_eps = get_episodios(st.session_state.serie_manager_id)
                if not df_eps.empty:
                    st.data_editor(
                        df_eps[['episodio_num', 'titulo_ep', 'nota', 'data_assistido']],
                        column_config={"episodio_num": st.column_config.NumberColumn("#", width="small"), "titulo_ep": "Título", "nota": "Nota", "data_assistido": st.column_config.DateColumn("Data", format="DD/MM/YYYY")},
                        use_container_width=True, num_rows="dynamic", key="editor_eps",
                        on_change=lambda: salvar_edicao_tabela_eps(st.session_state.serie_manager_id, st.session_state.editor_eps)
                    )
                if st.button("Fechar"): st.session_state.serie_manager_id = None; st.rerun()
            st.markdown("---")
    
    df = get_data(st.session_state.user, categoria_db)
    if df.empty: st.info("Nenhum registro."); return

    if filtro_ano != "Todos": df = df[df['data_registro'].dt.year == int(filtro_ano)]
    if filtro_mes != "Todos":
        meses_map = {"Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4, "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8, "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12}
        if filtro_mes in meses_map: df = df[df['data_registro'].dt.month == meses_map[filtro_mes]]
            
    if df.empty: st.warning("Nada com estes filtros."); return

    col_s1, _ = st.columns([1, 3])
    with col_s1: sort_op = st.selectbox("Ordenar:", ["Data (Recente)", "Nota (Melhor)", "Nome (A-Z)"], key=f"sort_{categoria_db}")
    
    if "Recente" in sort_op: df = df.sort_values(by="data_registro", ascending=False)
    elif "Melhor" in sort_op: df = df.sort_values(by="nota", ascending=False)
    elif "A-Z" in sort_op: df = df.sort_values(by="titulo", ascending=True)
    df = df.reset_index(drop=True)

    cols = st.columns(5)
    for index, row in df.iterrows():
        with cols[index % 5]:
            with st.container(border=True):
                st.image(row['capa_url'] if row['capa_url'] else "https://placehold.co/300x450")
                st.markdown(f"**{row['titulo']}**")
                st.caption(f"⭐ {int(row['nota'])}")
                if categoria_db == "Série" and st.button("📺 Eps", key=f"ep_{row['id']}"): st.session_state.serie_manager_id = row['id']; st.rerun()
                with st.expander("Ver +"):
                    st.write(row['comentario'])
                    if st.button("✏️", key=f"edt_{row['id']}"): st.session_state.edit_id = row['id']; st.rerun()
                    card = gerar_card(row['titulo'], row['nota'], row['comentario'], row['capa_url'], row['nickname'])
                    st.download_button("📸", card, f"card_{row['id']}.png", key=f"dl_{row['id']}")

# --- TELA DE LOGIN / REGISTRO ---
def login_screen():
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        st.title("🦉 Wan Shi Tong")
        st.subheader("Login de Acesso")
        
        tab_login, tab_register = st.tabs(["Entrar", "Criar Conta"])
        
        with tab_login:
            with st.form("login_form"):
                user_l = st.text_input("Usuário")
                pass_l = st.text_input("Senha", type="password")
                sub_l = st.form_submit_button("Entrar", type="primary")
                if sub_l and user_l and pass_l:
                    login_user(user_l, pass_l)
        
        with tab_register:
            with st.form("register_form"):
                user_r = st.text_input("Novo Usuário")
                pass_r = st.text_input("Nova Senha", type="password")
                sub_r = st.form_submit_button("Cadastrar")
                if sub_r and user_r and pass_r:
                    if register_user(user_r, pass_r):
                        st.info("Agora faça login na aba 'Entrar'.")

# --- MAIN APP ---
init_db()

if not st.session_state.user:
    login_screen()
else:
    # SIDEBAR
    st.sidebar.title(f"Olá, {st.session_state.user.title()}")
    if st.sidebar.button("Sair"): st.session_state.user = None; st.rerun()
    st.sidebar.markdown("---")
    page = st.sidebar.radio("Ir para", ["Registrar Novo", "🎮 Jogos", "🎬 Filmes", "📺 Séries", "📖 Livros"])
    
    st.sidebar.subheader("Filtros")
    f_ano = st.sidebar.selectbox("Ano", ["Todos"] + list(range(2024, datetime.now().year + 2)))
    f_mes = st.sidebar.selectbox("Mês", ["Todos", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"])

    if page == "Registrar Novo":
        st.title("➕ Novo Registro")
        if 'msg_sucesso' in st.session_state and st.session_state.msg_sucesso: st.success(st.session_state.msg_sucesso)
        
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Título", key="novo_titulo")
            st.selectbox("Categoria", ["Jogo", "Filme", "Série", "Livro"], key="novo_tipo")
            st.selectbox("Plataforma", ["Steam", "PS", "Xbox", "Netflix", "Prime Video", "Kindle", "Outros"], key="nova_plataforma")
        with c2:
            st.selectbox("Status", ["Concluído", "Em Andamento", "Abandonado"], key="novo_status")
            st.text_input("URL Capa", key="nova_capa")
            st.slider("Nota", 0, 100, 75, key="nova_nota")
        
        st.text_area("Comentário", key="novo_comentario")
        # NICKNAME AUTOMÁTICO - REMOVIDO INPUT MANUAL
        st.caption(f"Registro será salvo como: **{st.session_state.user.title()}**")
        st.button("Salvar", type="primary", on_click=salvar_novo_registro)

    else:
        if st.session_state.edit_id:
            def _save_update():
                update_midia(st.session_state.edit_id, st.session_state.e_tit, st.session_state.e_nota, st.session_state.e_com, st.session_state.user)
                st.session_state.edit_id = None; st.rerun()
            def _delete():
                delete_midia(st.session_state.edit_id, st.session_state.user)
                st.session_state.edit_id = None; st.rerun()

            with st.expander("Edição Rápida", expanded=True):
                curr = conn.query("SELECT * FROM midia WHERE id=:id", params={"id": st.session_state.edit_id}, ttl=0).iloc[0]
                st.text_input("Título", value=curr['titulo'], key="e_tit")
                st.slider("Nota", 0, 100, int(curr['nota']), key="e_nota")
                st.text_area("Comentário", value=curr['comentario'], key="e_com")
                c1, c2 = st.columns(2)
                c1.button("Salvar", on_click=_save_update); c2.button("Deletar", on_click=_delete)
        
        mapa = {"🎮 Jogos": "Jogo", "🎬 Filmes": "Filme", "📺 Séries": "Série", "📖 Livros": "Livro"}
        render_categoria_page(page, mapa[page], f_ano, f_mes)

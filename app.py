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

# --- CONFIGURAÇÃO DE PLATAFORMAS (REQ. DO USUÁRIO) ---
MAPA_PLATAFORMAS = {
    "Livro": ["Físico", "Digital"],
    "Jogo": ["PC", "PlayStation", "Xbox", "Nintendo Switch", "Mobile"],
    "Filme": ["Cinema", "Netflix", "Prime Video", "Disney+", "Max", "Apple TV+", "Stremio", "GloboPlay", "Outros"],
    "Série": ["Netflix", "Prime Video", "Disney+", "Max", "Apple TV+", "Stremio", "GloboPlay", "TV", "Outros"]
}

# --- CONEXÃO ---
conn = st.connection("postgresql", type="sql")

def init_db():
    with conn.session as s:
        # Tabela de Usuários
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password TEXT NOT NULL
            );
        '''))
        # Tabela de Mídia
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
        # Tabela de Episódios
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
            exists = s.execute(text("SELECT username FROM users WHERE username=:u"), {"u": user_clean}).fetchone()
            if exists:
                st.error("Usuário já existe.")
                return False
            s.execute(text("INSERT INTO users (username, password) VALUES (:u, :p)"), {"u": user_clean, "p": pass_hash})
            s.commit()
        st.success("Cadastrado com sucesso!")
        return True
    except Exception as e:
        st.error(f"Erro: {e}")
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
            st.error("Dados incorretos.")
    except Exception as e:
        st.error(f"Erro: {e}")

# --- CRUD COMPLETO ---

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

def update_midia(id_item, titulo, tipo, plataforma, status, nota, comentario, data_reg, capa_url, nickname, d_ini, d_fim, travar_nota, dono):
    trava_int = 1 if travar_nota else 0
    try:
        with conn.session as s:
            s.execute(
                text('''
                UPDATE midia 
                SET titulo=:t, tipo=:tp, plataforma=:p, status=:s, nota=:n, comentario=:c, 
                    data_registro=:dr, capa_url=:url, nickname=:nick, data_inicio=:di, data_fim=:df, travar_nota=:lock
                WHERE id=:id AND dono=:owner
                '''),
                {
                    "t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, "c": comentario,
                    "dr": data_reg, "url": capa_url, "nick": nickname, "di": d_ini, "df": d_fim,
                    "lock": trava_int, "id": id_item, "owner": dono
                }
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
                st.error("Permissão negada.")
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
        s.execute(text('INSERT INTO episodios (serie_id, episodio_num, titulo_ep, nota, data_assistido) VALUES (:sid, :enum, :tit, :nt, :dt)'),
            {"sid": serie_id, "enum": ep_num, "tit": titulo, "nt": nota, "dt": data})
        s.commit()
    st.cache_data.clear()
    recalcular_nota_serie(serie_id)

def recalcular_nota_serie(serie_id):
    df_midia = conn.query("SELECT travar_nota FROM midia WHERE id=:id", params={"id": serie_id}, ttl=0)
    if not df_midia.empty and df_midia.iloc[0]['travar_nota'] == 1: return

    res = conn.query("SELECT AVG(nota) as media, MIN(data_assistido) as inicio, MAX(data_assistido) as fim FROM episodios WHERE serie_id=:id", params={"id": serie_id}, ttl=0)
    if not res.empty:
        nova_media = res.iloc[0]['media'] if res.iloc[0]['media'] is not None else 0
        d_ini, d_fim = res.iloc[0]['inicio'], res.iloc[0]['fim']
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
    altura_total = altura_dinamica + 160
    card = Image.new('RGB', (largura_fixa, altura_total), (15, 15, 15))
    card.paste(img, (0, 0))
    draw = ImageDraw.Draw(card)
    
    if nota is not None and nota > 0:
        if nota >= 75: cor_badge, cor_txt = '#FFD700', '#000000'
        elif nota >= 50: cor_badge, cor_txt = '#C0C0C0', '#000000'
        else: cor_badge, cor_txt = '#B22222', '#FFFFFF'
        x1, y1 = largura_fixa - 90, 20
        draw.ellipse((x1, y1, x1+70, y1+70), fill=cor_badge)
        try: font_nota = ImageFont.truetype("arial.ttf", 35)
        except: font_nota = ImageFont.load_default()
        draw.text((x1+35, y1+35), str(int(nota)), fill=cor_txt, font=font_nota, anchor="mm")
    
    try: font_t = ImageFont.truetype("arial.ttf", 26); font_c = ImageFont.truetype("arial.ttf", 16); font_n = ImageFont.truetype("arial.ttf", 14)
    except: font_t = font_c = font_n = ImageFont.load_default()

    y_t = altura_dinamica + 20
    draw.text((15, y_t), f"{titulo[:30]}", fill=(255, 255, 255), font=font_t)
    comm_s = comentario if comentario else ""
    draw.text((15, y_t + 40), f"\"{comm_s[:90]}...\"", fill=(200, 200, 200), font=font_c)
    if nickname:
        txt_n = f"- {nickname.title()}"
        bbox = draw.textbbox((0, 0), txt_n, font=font_n)
        draw.text((largura_fixa - (bbox[2]-bbox[0]) - 15, y_t + 90), txt_n, fill=(150, 150, 150), font=font_n)
    
    buf = BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()

# --- FUNÇÕES UI (CALLBACKS) ---
def salvar_novo_registro():
    t = st.session_state.novo_titulo
    tp = st.session_state.novo_tipo
    p = st.session_state.nova_plataforma
    s = st.session_state.novo_status
    n = st.session_state.nova_nota
    c = st.session_state.novo_comentario
    url = st.session_state.nova_capa
    nick = st.session_state.user 
    
    d_ini = st.session_state.get('nova_data_inicio', None)
    d_fim = st.session_state.get('nova_data_fim', datetime.now().date())
    if tp not in ["Jogo", "Livro", "Série"]: d_ini = None 
    
    erros = []
    if not t.strip(): erros.append("Título obrigatório.")
    if s == "Concluído" and tp != "Série":
        if not c.strip(): erros.append("Comentário é obrigatório para itens concluídos.")
        if n == 0: erros.append("Nota deve ser maior que 0.")

    if erros:
        st.session_state.msg_erro = erros
    else:
        add_midia(t, tp, p, s, n, c, datetime.now().date(), url, nick, d_ini, d_fim, st.session_state.user)
        st.session_state.novo_titulo = ""
        st.session_state.novo_comentario = ""
        st.session_state.msg_sucesso = f"✅ {t} salvo!"
        st.session_state.msg_erro = None

def atualizar_registro():
    id_edit = st.session_state.edit_id
    t = st.session_state.edit_titulo
    tp = st.session_state.edit_tipo
    p = st.session_state.edit_plataforma
    s = st.session_state.edit_status
    n = st.session_state.edit_nota
    c = st.session_state.edit_comentario
    url = st.session_state.edit_capa
    nick = st.session_state.edit_nick
    d_ini = st.session_state.get('edit_data_inicio', None)
    d_fim = st.session_state.get('edit_data_fim', None)
    travar = st.session_state.get('edit_travar', False)

    df_orig = conn.query("SELECT data_registro FROM midia WHERE id=:id", params={"id": id_edit}, ttl=0)
    data_reg = df_orig.iloc[0]['data_registro'] if not df_orig.empty else datetime.now().date()

    if not t.strip(): st.session_state.msg_erro_edit = ["Título obrigatório."]; return
    
    update_midia(id_edit, t, tp, p, s, n, c, data_reg, url, nick, d_ini, d_fim, travar, st.session_state.user)
    st.session_state.msg_sucesso_edit = f"✅ {t} atualizado!"
    st.session_state.edit_id = None
    st.rerun()

def render_categoria_page(titulo_pagina, categoria_db, filtro_ano, filtro_mes):
    st.header(f"{titulo_pagina}")
    
    # GERENCIADOR EPISÓDIOS
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
    
    # EDIÇÃO
    if st.session_state.edit_id is not None:
        item_df = conn.query("SELECT * FROM midia WHERE id=:id AND dono=:owner", params={"id": st.session_state.edit_id, "owner": st.session_state.user}, ttl=0)
        if not item_df.empty:
            row = item_df.iloc[0]
            if row['tipo'] == categoria_db:
                with st.expander(f"✏️ Editando: {row['titulo']}", expanded=True):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.text_input("Título", value=row['titulo'], key="edit_titulo")
                        st.text_input("Categoria", value=row['tipo'], disabled=True, key="edit_tipo")
                        
                        # --- LISTA DINÂMICA NA EDIÇÃO ---
                        lista_plat = MAPA_PLATAFORMAS.get(row['tipo'], ["Outros"])
                        idx_plat = 0
                        if row['plataforma'] in lista_plat: idx_plat = lista_plat.index(row['plataforma'])
                        st.selectbox("Plataforma", lista_plat, index=idx_plat, key="edit_plataforma")

                    with ec2:
                        l_status = ["Concluído", "Em Andamento", "Abandonado"]
                        try: idx_stat = l_status.index(row['status']) 
                        except: idx_stat = 1
                        st.selectbox("Status Geral", l_status, index=idx_stat, key="edit_status")
                        
                        val_d_ini = pd.to_datetime(row['data_inicio']).date() if row['data_inicio'] else None
                        val_d_fim = pd.to_datetime(row['data_fim']).date() if row['data_fim'] else datetime.now().date()
                        
                        if categoria_db in ["Jogo", "Livro", "Série"]:
                            cd1, cd2 = st.columns(2)
                            cd1.date_input("Início", value=val_d_ini, key="edit_data_inicio")
                            cd2.date_input("Fim/Conclusão", value=val_d_fim, key="edit_data_fim")
                        else:
                            st.date_input("Data Assistido", value=val_d_fim, key="edit_data_fim")
                        st.text_input("URL Capa", value=row['capa_url'], key="edit_capa")
                    
                    st.text_input("Nick", value=row['nickname'], key="edit_nick")
                    if categoria_db == "Série":
                        is_locked = True if row['travar_nota'] == 1 else False
                        col_lock, col_nota = st.columns([1, 2])
                        col_lock.checkbox("🔒 Travar Nota?", value=is_locked, key="edit_travar")
                        col_nota.slider("Nota", 0, 100, int(row['nota']), key="edit_nota")
                    else:
                        st.slider("Nota (0-100)", 0, 100, int(row['nota']), key="edit_nota")
                        
                    st.text_area("Comentário", value=row['comentario'], key="edit_comentario")
                    
                    b1, b2, b3 = st.columns([1, 1, 3])
                    b1.button("💾 Atualizar", type="primary", on_click=atualizar_registro)
                    b2.button("🗑️ Excluir", on_click=lambda: (delete_midia(st.session_state.edit_id, st.session_state.user), st.session_state.update({"edit_id": None})))
                    if b3.button("Cancelar"): st.session_state.edit_id = None; st.rerun()
                st.divider()

    # DADOS
    df = get_data(st.session_state.user, categoria_db)
    if df.empty: st.info("Nenhum registro."); return

    if filtro_ano != "Todos": df = df[df['data_registro'].dt.year == int(filtro_ano)]
    if filtro_mes != "Todos":
        meses_map = {"Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4, "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8, "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12}
        if filtro_mes in meses_map: df = df[df['data_registro'].dt.month == meses_map[filtro_mes]]
            
    if df.empty: st.warning("Nada com estes filtros."); return

    # ABAS (BIBLIOTECA & ANALYTICS)
    tab_galeria, tab_analytics = st.tabs(["📚 Biblioteca", "📊 Analytics"])

    with tab_galeria:
        col_s1, _ = st.columns([1, 3])
        with col_s1:
            sort_map = {
                "Data (Mais Recente)": "date_desc",
                "Data (Mais Antigo)": "date_asc",
                "Nota (Melhores)": "score_desc",
                "Nota (Piores)": "score_asc",
                "Nome (A-Z)": "title_asc"
            }
            sort_label = st.selectbox("Ordenar:", list(sort_map.keys()), key=f"s_{categoria_db}")
            sort_op = sort_map[sort_label]
        
        if sort_op == "date_desc": df = df.sort_values(by="data_registro", ascending=False)
        elif sort_op == "date_asc": df = df.sort_values(by="data_registro", ascending=True)
        elif sort_op == "score_desc": df = df.sort_values(by="nota", ascending=False)
        elif sort_op == "score_asc": df = df.sort_values(by="nota", ascending=True)
        elif sort_op == "title_asc": df = df.sort_values(by="titulo", ascending=True)
        df = df.reset_index(drop=True)

        cols = st.columns(5)
        for index, row in df.iterrows():
            with cols[index % 5]:
                with st.container(border=True):
                    st.image(row['capa_url'] if row['capa_url'] else "https://placehold.co/300x450")
                    st.markdown(f"**{row['titulo']}**")
                    
                    nota_show = int(row['nota'])
                    if row['status'] == "Concluído":
                        if nota_show >= 75: st.success(f"🏆 {nota_show}")
                        elif nota_show >= 50: st.warning(f"😐 {nota_show}")
                        else: st.error(f"💔 {nota_show}")
                    elif row['status'] == "Abandonado": st.error("💀 Abandonado")
                    else: st.info("⏳ Em Andamento")
                    
                    if categoria_db == "Série" and st.button("📺 Eps", key=f"ep_{row['id']}"): st.session_state.serie_manager_id = row['id']; st.rerun()
                    with st.expander("Ver +"):
                        if pd.notnull(row['data_inicio']):
                            di = row['data_inicio'].strftime('%d/%m/%Y')
                            dfim = row['data_fim'].strftime('%d/%m/%Y') if pd.notnull(row['data_fim']) else "..."
                            st.caption(f"🗓️ {di} a {dfim}")
                        else:
                            dreg = row['data_registro'].strftime('%d/%m/%Y') if pd.notnull(row['data_registro']) else "-"
                            st.caption(f"📅 {dreg}")
                        
                        st.write(row['comentario'])
                        if st.button("✏️ Editar", key=f"edt_{row['id']}"): st.session_state.edit_id = row['id']; st.rerun()
                        card = gerar_card(row['titulo'], row['nota'], row['comentario'], row['capa_url'], row['nickname'])
                        st.download_button("📸 Card", card, f"card_{row['id']}.png", key=f"dl_{row['id']}")

    with tab_analytics:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total de Itens", len(df))
        concluidos = df[df['status'] == "Concluído"]
        c2.metric("Concluídos", len(concluidos))
        media = concluidos['nota'].mean()
        c3.metric("Média (Concluídos)", f"{media:.1f}" if pd.notnull(media) else "-")
        st.divider()
        g1, g2 = st.columns(2)
        g1.plotly_chart(px.pie(df, names='status', title="Distribuição por Status", hole=0.4))
        g2.plotly_chart(px.bar(df['plataforma'].value_counts(), title="Plataformas Mais Usadas", orientation='h'))

# --- TELA DE LOGIN ---
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
                if st.form_submit_button("Entrar", type="primary") and user_l and pass_l: login_user(user_l, pass_l)
        with tab_register:
            with st.form("register_form"):
                user_r = st.text_input("Novo Usuário")
                pass_r = st.text_input("Nova Senha", type="password")
                if st.form_submit_button("Cadastrar") and user_r and pass_r:
                    if register_user(user_r, pass_r): st.info("Faça login na aba 'Entrar'.")

# --- MAIN APP ---
init_db()

if not st.session_state.user:
    login_screen()
else:
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
        if 'msg_erro' in st.session_state and st.session_state.msg_erro: 
            for e in st.session_state.msg_erro: st.error(e)
            
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Título", key="novo_titulo")
            tp = st.selectbox("Categoria", ["Jogo", "Filme", "Série", "Livro"], key="novo_tipo")
            
            # --- LISTA DINÂMICA NO REGISTRO ---
            lista_plat = MAPA_PLATAFORMAS.get(tp, ["Outros"])
            st.selectbox("Plataforma", lista_plat, key="nova_plataforma")

        with c2:
            st.selectbox("Status", ["Concluído", "Em Andamento", "Abandonado"], key="novo_status")
            st.text_input("URL Capa", key="nova_capa")
            st.slider("Nota", 0, 100, 75, key="nova_nota")
        
        st.text_area("Comentário", key="novo_comentario")
        st.caption(f"Registro será salvo como: **{st.session_state.user.title()}**")
        st.button("Salvar", type="primary", on_click=salvar_novo_registro)

    else:
        mapa = {"🎮 Jogos": "Jogo", "🎬 Filmes": "Filme", "📺 Séries": "Série", "📖 Livros": "Livro"}
        render_categoria_page(page, mapa[page], f_ano, f_mes)

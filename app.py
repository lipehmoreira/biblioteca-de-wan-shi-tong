import streamlit as st
import pandas as pd
import plotly.express as px
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from datetime import datetime
from sqlalchemy import text

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Biblioteca de Wan Shi Tong", layout="wide", page_icon="🦉")

# --- CSS ---
st.markdown("""
<style>
    .stMetric {background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px;}
    div[data-testid="stExpander"] {background-color: #161616; border: 1px solid #333; border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

# --- ESTADO ---
if 'edit_id' not in st.session_state: st.session_state.edit_id = None
if 'serie_manager_id' not in st.session_state: st.session_state.serie_manager_id = None

# --- CONEXÃO COM BANCO DE DADOS (POSTGRESQL) ---
# Procura as credenciais em .streamlit/secrets.toml
conn = st.connection("postgresql", type="sql")

def init_db():
    # Criação de tabelas ajustada para sintaxe PostgreSQL (SERIAL em vez de AUTOINCREMENT)
    with conn.session as s:
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
                travar_nota INTEGER DEFAULT 0
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

# --- CRUD MIDIA ---
def add_midia(titulo, tipo, plataforma, status, nota, comentario, data_reg, capa_url, nickname, d_ini, d_fim):
    try:
        with conn.session as s:
            s.execute(
                text('''
                INSERT INTO midia (titulo, tipo, plataforma, status, nota, comentario, data_registro, capa_url, nickname, data_inicio, data_fim) 
                VALUES (:t, :tp, :p, :s, :n, :c, :dr, :url, :nick, :di, :df)
                '''),
                {
                    "t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, 
                    "c": comentario, "dr": data_reg, "url": capa_url, "nick": nickname, 
                    "di": d_ini, "df": d_fim
                }
            )
            s.commit()
        st.cache_data.clear() # Limpa cache para atualizar a tela
    except Exception as e:
        st.error(f"Erro ao salvar: {e}")

def update_midia(id_item, titulo, tipo, plataforma, status, nota, comentario, data_reg, capa_url, nickname, d_ini, d_fim, travar_nota):
    trava_int = 1 if travar_nota else 0
    try:
        with conn.session as s:
            s.execute(
                text('''
                UPDATE midia 
                SET titulo=:t, tipo=:tp, plataforma=:p, status=:s, nota=:n, comentario=:c, 
                    data_registro=:dr, capa_url=:url, nickname=:nick, data_inicio=:di, data_fim=:df, travar_nota=:lock
                WHERE id=:id
                '''),
                {
                    "t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, "c": comentario,
                    "dr": data_reg, "url": capa_url, "nick": nickname, "di": d_ini, "df": d_fim,
                    "lock": trava_int, "id": id_item
                }
            )
            s.commit()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao atualizar: {e}")

def delete_midia(id_item):
    try:
        with conn.session as s:
            # Em Postgres com Foreign Key Cascade, deletar a mídia deleta os episódios, 
            # mas vamos manter explícito por segurança
            s.execute(text('DELETE FROM episodios WHERE serie_id=:id'), {"id": id_item})
            s.execute(text('DELETE FROM midia WHERE id=:id'), {"id": id_item})
            s.commit()
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Erro ao deletar: {e}")

def get_data(tipo_filtro=None):
    query = "SELECT * FROM midia"
    params = {}
    if tipo_filtro: 
        query += " WHERE tipo = :tp"
        params = {"tp": tipo_filtro}
    
    # ttl=0 garante dados frescos do banco
    df = conn.query(query, params=params, ttl=0)
    
    if not df.empty:
        df['data_registro'] = pd.to_datetime(df['data_registro'], errors='coerce')
        df['data_inicio'] = pd.to_datetime(df['data_inicio'], errors='coerce')
        df['data_fim'] = pd.to_datetime(df['data_fim'], errors='coerce')
        df['ano'] = df['data_registro'].dt.year
        df['mes_nome'] = df['data_registro'].dt.month_name()
        
        # Tratamento de nulos
        if 'nickname' not in df.columns: df['nickname'] = ""
        df['nickname'] = df['nickname'].fillna("")
        df['nota'] = pd.to_numeric(df['nota'], errors='coerce').fillna(0.0)
    return df

# --- CRUD EPISODIOS ---
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
    # Verifica trava
    df_midia = conn.query("SELECT travar_nota FROM midia WHERE id=:id", params={"id": serie_id}, ttl=0)
    if not df_midia.empty and df_midia.iloc[0]['travar_nota'] == 1:
        return

    # Calcula média e datas
    res = conn.query(
        "SELECT AVG(nota) as media, MIN(data_assistido) as inicio, MAX(data_assistido) as fim FROM episodios WHERE serie_id=:id", 
        params={"id": serie_id}, 
        ttl=0
    )
    
    if not res.empty:
        nova_media = res.iloc[0]['media']
        if nova_media is None: nova_media = 0
        d_ini = res.iloc[0]['inicio']
        d_fim = res.iloc[0]['fim']

        with conn.session as s:
            if d_ini and d_fim:
                s.execute(
                    text("UPDATE midia SET nota=:n, data_inicio=:di, data_fim=:df WHERE id=:id"), 
                    {"n": float(nova_media), "di": d_ini, "df": d_fim, "id": serie_id}
                )
            else:
                s.execute(
                    text("UPDATE midia SET nota=:n WHERE id=:id"), 
                    {"n": float(nova_media), "id": serie_id}
                )
            s.commit()

def get_episodios(serie_id):
    df = conn.query(
        "SELECT * FROM episodios WHERE serie_id=:id ORDER BY episodio_num", 
        params={"id": serie_id}, 
        ttl=0
    )
    if not df.empty:
        df['data_assistido'] = pd.to_datetime(df['data_assistido'])
    return df

def salvar_edicao_tabela():
    edits = st.session_state.editor_eps
    serie_id = st.session_state.serie_manager_id
    
    if not edits: return

    with conn.session as s:
        df_orig = get_episodios(serie_id)
        
        # Updates
        for idx, changes in edits['edited_rows'].items():
            # O Streamlit retorna o índice da linha na tabela original
            if int(idx) < len(df_orig):
                ep_id = int(df_orig.iloc[int(idx)]['id'])
                for col_name, new_val in changes.items():
                    # Mapeia colunas do DataFrame para o Banco
                    if col_name == "data_assistido":
                        s.execute(text("UPDATE episodios SET data_assistido=:v WHERE id=:id"), {"v": pd.to_datetime(new_val).date(), "id": ep_id})
                    elif col_name == "episodio_num":
                        s.execute(text("UPDATE episodios SET episodio_num=:v WHERE id=:id"), {"v": new_val, "id": ep_id})
                    elif col_name == "titulo_ep":
                        s.execute(text("UPDATE episodios SET titulo_ep=:v WHERE id=:id"), {"v": new_val, "id": ep_id})
                    elif col_name == "nota":
                        s.execute(text("UPDATE episodios SET nota=:v WHERE id=:id"), {"v": new_val, "id": ep_id})

        # Deletes
        for idx in edits['deleted_rows']:
             if int(idx) < len(df_orig):
                ep_id = int(df_orig.iloc[int(idx)]['id'])
                s.execute(text("DELETE FROM episodios WHERE id=:id"), {"id": ep_id})
        
        s.commit()
    
    st.cache_data.clear()
    recalcular_nota_serie(serie_id)
    st.toast("Episódios atualizados!")

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

    try:
        font_titulo = ImageFont.truetype("arial.ttf", 26)
        font_comm = ImageFont.truetype("arial.ttf", 16)
        font_nick = ImageFont.truetype("arial.ttf", 14)
    except: font_titulo = font_comm = font_nick = ImageFont.load_default()

    y_texto = altura_dinamica + 20
    draw.text((15, y_texto), f"{titulo[:30]}", fill=(255, 255, 255), font=font_titulo)
    comm_safe = comentario if comentario else ""
    draw.text((15, y_texto + 40), f"\"{comm_safe[:90]}...\"", fill=(200, 200, 200), font=font_comm)
    
    if nickname:
        txt_nick = f"- {nickname}"
        bbox = draw.textbbox((0, 0), txt_nick, font=font_nick)
        w_nick = bbox[2] - bbox[0]
        draw.text((largura_fixa - w_nick - 15, y_texto + 90), txt_nick, fill=(150, 150, 150), font=font_nick)
    
    buf = BytesIO()
    card.save(buf, format="PNG")
    return buf.getvalue()

# --- CALLBACKS ---
def salvar_novo_registro():
    t = st.session_state.novo_titulo
    tp = st.session_state.novo_tipo
    p = st.session_state.nova_plataforma
    s = st.session_state.novo_status
    n = st.session_state.nova_nota
    c = st.session_state.novo_comentario
    url = st.session_state.nova_capa
    nick = st.session_state.novo_nick
    d_ini = st.session_state.get('nova_data_inicio', None)
    d_fim = st.session_state.get('nova_data_fim', datetime.now().date())
    if tp not in ["Jogo", "Livro", "Série"]: d_ini = None 
    
    erros = []
    if not t.strip(): erros.append("O Título é obrigatório.")
    if s == "Concluído" and tp != "Série":
        if not c.strip(): erros.append("Comentário é obrigatório.")
        if n == 0: erros.append("Nota deve ser maior que 0.")
    
    if erros:
        st.session_state.msg_erro = erros
        st.session_state.msg_sucesso = None
    else:
        add_midia(t, tp, p, s, n, c, datetime.now().date(), url, nick, d_ini, d_fim)
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

    # Buscar data_registro original para não perder
    df_orig = conn.query("SELECT data_registro FROM midia WHERE id=:id", params={"id": id_edit}, ttl=0)
    data_reg = df_orig.iloc[0]['data_registro'] if not df_orig.empty else datetime.now().date()

    erros = []
    if not t.strip(): erros.append("Título obrigatório.")
    
    if erros: st.session_state.msg_erro_edit = erros
    else:
        update_midia(id_edit, t, tp, p, s, n, c, data_reg, url, nick, d_ini, d_fim, travar)
        st.session_state.msg_sucesso_edit = f"✅ {t} atualizado!"
        st.session_state.edit_id = None
        st.rerun()

def excluir_registro():
    if st.session_state.edit_id:
        delete_midia(st.session_state.edit_id)
        st.session_state.edit_id = None
        st.rerun()

def salvar_episodio():
    s_id = st.session_state.serie_manager_id
    num = st.session_state.ep_num
    tit = st.session_state.ep_tit
    nota = st.session_state.ep_nota
    dt = st.session_state.ep_data
    add_episodio(s_id, num, tit, nota, dt)
    st.session_state.ep_tit = "" 

# --- RENDERIZAÇÃO ---
def render_categoria_page(titulo_pagina, categoria_db, filtro_ano, filtro_mes):
    st.header(f"{titulo_pagina}")
    
    # --- GERENCIADOR EPISODIOS ---
    if st.session_state.serie_manager_id is not None and categoria_db == "Série":
        serie_info_df = conn.query(f"SELECT * FROM midia WHERE id=:id", params={"id": st.session_state.serie_manager_id}, ttl=0)
        
        if not serie_info_df.empty:
            serie_info = serie_info_df.iloc[0]
            with st.container(border=True):
                st.markdown(f"### 📺 Gerenciar Episódios: **{serie_info['titulo']}**")
                col_add1, col_add2, col_add3, col_add4, col_add5 = st.columns([1,3,1.5,1.5,1])
                with col_add1: st.number_input("Ep Nº", min_value=1, value=1, key="ep_num")
                with col_add2: st.text_input("Título Episódio", key="ep_tit")
                with col_add3: st.date_input("Data", datetime.now(), key="ep_data")
                with col_add4: st.number_input("Nota", 0, 100, 80, key="ep_nota")
                with col_add5: 
                    st.write("")
                    st.write("")
                    st.button("➕ Add", on_click=salvar_episodio)
                st.divider()
                
                df_eps = get_episodios(st.session_state.serie_manager_id)
                if not df_eps.empty:
                    st.caption("📝 Edite direto na tabela abaixo:")
                    st.data_editor(
                        df_eps[['episodio_num', 'titulo_ep', 'nota', 'data_assistido']],
                        column_config={
                            "episodio_num": st.column_config.NumberColumn("#", width="small"),
                            "titulo_ep": st.column_config.TextColumn("Título", width="large"),
                            "nota": st.column_config.NumberColumn("Nota (0-100)", min_value=0, max_value=100),
                            "data_assistido": st.column_config.DateColumn("Data", format="DD/MM/YYYY")
                        },
                        width=None,
                        use_container_width=True,
                        num_rows="dynamic",
                        key="editor_eps",
                        on_change=salvar_edicao_tabela
                    )
                else: st.info("Nenhum episódio registrado.")
                
                if st.button("Fechar Gerenciador"):
                    st.session_state.serie_manager_id = None
                    st.rerun()
            st.markdown("---")

    # --- ÁREA DE EDIÇÃO ---
    if st.session_state.edit_id is not None:
        item_df = conn.query("SELECT * FROM midia WHERE id=:id", params={"id": st.session_state.edit_id}, ttl=0)
        
        if not item_df.empty:
            row = item_df.iloc[0]
            if row['tipo'] == categoria_db:
                with st.expander(f"✏️ Editando: {row['titulo']}", expanded=True):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        st.text_input("Título", value=row['titulo'], key="edit_titulo")
                        st.text_input("Categoria", value=row['tipo'], disabled=True, key="edit_tipo")
                        l = ["Netflix", "Prime Video", "Disney+", "Max", "Apple TV", "Cinema", "Stremio", "TV"]
                        if categoria_db == "Jogo": l = ["Steam", "Epic", "Ubisoft", "GOG", "Xbox", "PS", "Switch"]
                        elif categoria_db == "Livro": l = ["Kindle", "Físico", "Audiobook"]
                        idx_plat = 0
                        if row['plataforma'] in l: idx_plat = l.index(row['plataforma'])
                        st.selectbox("Plataforma", l, index=idx_plat, key="edit_plataforma")

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
                    
                    st.text_input("Seu Nick", value=row['nickname'], key="edit_nick")
                    if categoria_db == "Série":
                        is_locked = True if row['travar_nota'] == 1 else False
                        col_lock, col_nota = st.columns([1, 2])
                        with col_lock:
                            st.write("")
                            st.write("")
                            st.checkbox("🔒 Travar Nota?", value=is_locked, key="edit_travar")
                        with col_nota:
                            st.slider("Nota da Série", 0, 100, int(row['nota']), key="edit_nota")
                    else:
                        st.slider("Nota (0-100)", 0, 100, int(row['nota']), key="edit_nota")
                        
                    st.text_area("Comentário", value=row['comentario'], key="edit_comentario")
                    b1, b2, b3 = st.columns([1, 1, 3])
                    b1.button("💾 Atualizar", type="primary", on_click=atualizar_registro)
                    b2.button("🗑️ Excluir", on_click=excluir_registro)
                    if b3.button("Cancelar"):
                        st.session_state.edit_id = None
                        st.rerun()
                st.divider()

    # --- LISTAGEM ---
    df = get_data(categoria_db)
    if df.empty:
        st.info(f"Nenhum registro encontrado em {titulo_pagina}.")
        return

    # Filtros
    if filtro_ano != "Todos": df = df[df['data_registro'].dt.year == int(filtro_ano)]
    if filtro_mes != "Todos":
        meses_map = {"Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4, "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8, "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12}
        if filtro_mes in meses_map: df = df[df['data_registro'].dt.month == meses_map[filtro_mes]]
            
    if df.empty:
        st.warning("Nada encontrado com estes filtros.")
        return

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
                    capa = row['capa_url'] if row['capa_url'] else "https://placehold.co/300x450"
                    st.image(capa) 
                    st.markdown(f"**{row['titulo']}**")
                    
                    nota_show = int(row['nota'])
                    if row['status'] == "Concluído":
                        if nota_show >= 75: st.success(f"🏆 {nota_show}")
                        elif nota_show >= 50: st.warning(f"😐 {nota_show}")
                        else: st.error(f"💔 {nota_show}")
                    elif row['status'] == "Abandonado": st.error("💀 Abandonado")
                    else: st.info("⏳ Em Andamento")
                    
                    if categoria_db == "Série":
                        if st.button("📺 Episódios", key=f"btn_ep_{row['id']}"):
                            st.session_state.serie_manager_id = row['id']
                            st.rerun()
                    
                    with st.expander("Detalhes"):
                        if categoria_db in ["Jogo", "Livro", "Série"] and pd.notnull(row['data_inicio']):
                            di = row['data_inicio'].strftime('%d/%m/%Y')
                            dfim = row['data_fim'].strftime('%d/%m/%Y') if pd.notnull(row['data_fim']) else "..."
                            st.caption(f"🗓️ {di} a {dfim}")
                        else:
                            dreg = row['data_registro'].strftime('%d/%m/%Y') if pd.notnull(row['data_registro']) else "-"
                            st.caption(f"📅 {dreg}")
                        st.write(row['comentario'])
                        card_data = gerar_card(row['titulo'], row['nota'], row['comentario'], capa, row['nickname'])
                        st.download_button("📸 Card", card_data, f"card_{row['id']}.png", "image/png", key=f"dl_{row['id']}")
                    
                    if st.button("✏️ Editar", key=f"btn_edit_{row['id']}"):
                        st.session_state.edit_id = row['id']
                        st.rerun()

    with tab_analytics:
        c1, c2, c3 = st.columns(3)
        c1.metric("Total", len(df))
        c2.metric("Concluídos", len(df[df['status'] == "Concluído"]))
        media = df[df['status'] == "Concluído"]['nota'].mean()
        c3.metric("Média Geral", f"{media:.1f}" if pd.notnull(media) else "-")
        st.divider()
        g1, g2 = st.columns(2)
        g1.plotly_chart(px.pie(df, names='status', title="Status", hole=0.5))
        g2.plotly_chart(px.bar(df['plataforma'].value_counts(), title="Plataformas", orientation='h'))

# --- INICIALIZAÇÃO ---
init_db()

# --- SIDEBAR ---
st.sidebar.title("Biblioteca de Wan Shi Tong")
page = st.sidebar.radio("Ir para", ["Registrar Novo", "🎮 Jogos", "🎬 Filmes", "📺 Séries", "📖 Livros"])
st.sidebar.markdown("---")
st.sidebar.subheader("📅 Filtro Global")
ano_atual = datetime.now().year
lista_anos = ["Todos"] + list(range(2024, ano_atual + 2))
try: idx_p = lista_anos.index(ano_atual)
except: idx_p = 0
filtro_ano = st.sidebar.selectbox("Ano", lista_anos, index=idx_p)
meses = ["Todos", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
filtro_mes = st.sidebar.selectbox("Mês", meses)

if page == "Registrar Novo":
    st.title("➕ Novo Registro")
    if 'msg_sucesso' in st.session_state and st.session_state.msg_sucesso: st.success(st.session_state.msg_sucesso)
    if 'msg_erro' in st.session_state and st.session_state.msg_erro: 
        for e in st.session_state.msg_erro: st.error(e)
    c1, c2 = st.columns(2)
    with c1:
        st.text_input("Título", key="novo_titulo")
        tp = st.selectbox("Categoria", ["Jogo", "Filme", "Série", "Livro"], key="novo_tipo")
        if tp == "Jogo": l = ["Steam", "Epic", "Ubisoft", "GOG", "Xbox", "PS", "Switch"]
        elif tp == "Livro": l = ["Kindle", "Físico", "Audiobook"]
        else: l = ["Netflix", "Prime Video", "Disney+", "Max", "Apple TV", "Cinema", "Stremio"]
        st.selectbox("Plataforma", l, key="nova_plataforma")
    with c2:
        st.selectbox("Status", ["Concluído", "Em Andamento", "Abandonado"], key="novo_status")
        if tp in ["Jogo", "Livro", "Série"]:
            cd1, cd2 = st.columns(2)
            cd1.date_input("Início", value=None, key="nova_data_inicio")
            cd2.date_input("Fim/Conclusão", datetime.now(), key="nova_data_fim")
        else:
            st.date_input("Data Assistido", datetime.now(), key="nova_data_fim")
        st.text_input("URL Capa", key="nova_capa")
    st.markdown("---")
    st.text_input("Seu Nick", key="novo_nick")
    if tp == "Série":
        st.info("Para Séries, adicione a nota 0 agora. A nota real será calculada quando você adicionar episódios na aba 'Séries'.")
        st.slider("Nota (0-100)", 0, 100, 0, key="nova_nota", disabled=True)
    else:
        st.slider("Nota (0-100)", 0, 100, 0, key="nova_nota")
    st.text_area("Comentário", key="novo_comentario")
    st.button("💾 Salvar Registro", type="primary", on_click=salvar_novo_registro)
else:
    mapa = {"🎮 Jogos": "Jogo", "🎬 Filmes": "Filme", "📺 Séries": "Série", "📖 Livros": "Livro"}
    render_categoria_page(page, mapa[page], filtro_ano, filtro_mes)
import streamlit as st
import pandas as pd
import plotly.express as px
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO
from datetime import datetime
from sqlalchemy import text
import hashlib
import textwrap  # Importante para quebrar o texto no card

# --- VERSÃO ---
APP_VERSION = "7.0 (Card Inteligente)"
DEV_NAME = "FzR0"

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(page_title="Wan Shi Tong Library", layout="wide", page_icon="🦉")

# --- CSS ---
st.markdown("""
<style>
    .stMetric {background-color: #1E1E1E; border: 1px solid #333; border-radius: 8px;}
    div[data-testid="stExpander"] {background-color: #161616; border: 1px solid #333; border-radius: 8px;}
</style>
""", unsafe_allow_html=True)

# --- ESTADO E INICIALIZAÇÃO DE VARIÁVEIS ---
if 'user' not in st.session_state: st.session_state.user = None
if 'edit_id' not in st.session_state: st.session_state.edit_id = None
if 'serie_manager_id' not in st.session_state: st.session_state.serie_manager_id = None
if 'search_results' not in st.session_state: st.session_state.search_results = [] 
if 'msg_sucesso' not in st.session_state: st.session_state.msg_sucesso = None
if 'msg_erro' not in st.session_state: st.session_state.msg_erro = None

# Inicializa variáveis dos widgets de cadastro
if 'novo_titulo' not in st.session_state: st.session_state.novo_titulo = ""
if 'novo_capa' not in st.session_state: st.session_state.novo_capa = ""
if 'novo_sinopse_texto' not in st.session_state: st.session_state.novo_sinopse_texto = ""
if 'novo_comentario' not in st.session_state: st.session_state.novo_comentario = ""
if 'novo_tipo_manual' not in st.session_state: st.session_state.novo_tipo_manual = "Filme"
if 'nova_plataforma' not in st.session_state: st.session_state.nova_plataforma = "Cinema"
if 'novo_status' not in st.session_state: st.session_state.novo_status = "Em Andamento"
if 'nova_nota' not in st.session_state: st.session_state.nova_nota = 75

# --- CONSTANTES ---
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
        s.execute(text('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT NOT NULL);'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS midia (id SERIAL PRIMARY KEY, titulo TEXT NOT NULL, tipo TEXT NOT NULL, plataforma TEXT, status TEXT NOT NULL, nota REAL, comentario TEXT, data_registro DATE, capa_url TEXT, nickname TEXT, data_inicio DATE, data_fim DATE, travar_nota INTEGER DEFAULT 0, dono TEXT);'''))
        s.execute(text('''CREATE TABLE IF NOT EXISTS episodios (id SERIAL PRIMARY KEY, serie_id INTEGER, episodio_num INTEGER, titulo_ep TEXT, nota REAL, data_assistido DATE, FOREIGN KEY(serie_id) REFERENCES midia(id) ON DELETE CASCADE);'''))
        try:
            s.execute(text("ALTER TABLE midia ADD COLUMN sinopse TEXT"))
        except: pass
        s.commit()

# --- INTEGRAÇÃO COM APIS ---
def buscar_tmdb(query, categoria):
    api_key = st.secrets.get("api", {}).get("tmdb_key")
    if not api_key: st.warning("⚠️ Chave TMDB não configurada."); return []
    
    tipo = "movie" if categoria == "Filme" else "tv"
    url = f"https://api.themoviedb.org/3/search/{tipo}?api_key={api_key}&query={query}&language=pt-BR"
    
    lista_final = []
    try:
        resp = requests.get(url)
        data = resp.json()
        if data.get('results'):
            for item in data['results'][:10]:
                titulo = item.get('title') if categoria == "Filme" else item.get('name')
                dt_str = item.get('release_date') if categoria == "Filme" else item.get('first_air_date')
                ano = dt_str[:4] if dt_str else "N/A"
                
                poster = item.get('poster_path')
                capa = f"https://image.tmdb.org/t/p/w500{poster}" if poster else ""
                
                lista_final.append({
                    "label": f"{titulo} ({ano})",
                    "titulo": titulo,
                    "sinopse": item.get('overview', ''),
                    "capa": capa,
                    "data_str": dt_str
                })
    except Exception as e: st.error(f"Erro TMDB: {e}")
    return lista_final

def buscar_google_books(query):
    url = f"https://www.googleapis.com/books/v1/volumes?q={query}&langRestrict=pt&maxResults=10"
    lista_final = []
    try:
        resp = requests.get(url)
        data = resp.json()
        if 'items' in data:
            for item in data['items']:
                info = item['volumeInfo']
                titulo = info.get('title', '')
                dt_str = info.get('publishedDate', '')
                ano = dt_str[:4] if dt_str else "N/A"
                
                imgs = info.get('imageLinks', {})
                capa = imgs.get('thumbnail') or imgs.get('smallThumbnail') or ""
                
                lista_final.append({
                    "label": f"{titulo} ({ano})",
                    "titulo": titulo,
                    "sinopse": info.get('description', ''),
                    "capa": capa,
                    "data_str": dt_str
                })
    except Exception as e: st.error(f"Erro G.Books: {e}")
    return lista_final

def executar_busca(termo, categoria):
    if not termo: return
    res = []
    if categoria in ["Filme", "Série"]:
        with st.spinner("Pesquisando TMDB..."): res = buscar_tmdb(termo, categoria)
    elif categoria == "Livro":
        with st.spinner("Pesquisando Google Books..."): res = buscar_google_books(termo)
    
    if res:
        st.session_state.search_results = res
    else:
        st.session_state.search_results = []
        st.toast("Nenhum resultado encontrado.", icon="❌")

def confirmar_selecao(item, categoria):
    st.session_state.novo_titulo = item['titulo']
    st.session_state.novo_sinopse_texto = item['sinopse']
    st.session_state.novo_capa = item['capa']
    st.session_state.novo_tipo_manual = categoria
    
    if categoria == "Filme": st.session_state.nova_plataforma = "Cinema"
    elif categoria == "Série": st.session_state.nova_plataforma = "Netflix"
    elif categoria == "Jogo": st.session_state.nova_plataforma = "PC"
    elif categoria == "Livro": st.session_state.nova_plataforma = "Físico"
    
    if item['data_str']:
        try:
            if len(item['data_str']) == 4: dt = datetime.strptime(item['data_str'], "%Y").date()
            else: dt = datetime.strptime(item['data_str'][:10], "%Y-%m-%d").date()
        except: pass
    
    st.session_state.search_results = [] 
    st.toast(f"Dados importados: {item['titulo']}", icon="✅")

# --- AUTENTICAÇÃO ---
def hash_pass(password): return hashlib.sha256(password.encode()).hexdigest()
def register_user(username, password):
    user_clean, pass_hash = username.strip().lower(), hash_pass(password)
    try:
        with conn.session as s:
            if s.execute(text("SELECT username FROM users WHERE username=:u"), {"u": user_clean}).fetchone(): st.error("Usuário existe."); return False
            s.execute(text("INSERT INTO users (username, password) VALUES (:u, :p)"), {"u": user_clean, "p": pass_hash}); s.commit()
        st.success("Cadastrado!"); return True
    except: return False
def login_user(username, password):
    u, p = username.strip().lower(), hash_pass(password)
    try:
        if not conn.query("SELECT * FROM users WHERE username=:u AND password=:p", params={"u": u, "p": p}, ttl=0).empty:
            st.session_state.user = u; st.rerun()
        else: st.error("Dados incorretos.")
    except Exception as e: st.error(f"Erro login: {e}")

# --- CRUD ---
def add_midia(titulo, tipo, plataforma, status, nota, comentario, sinopse, data_reg, capa_url, nickname, d_ini, d_fim, dono):
    try:
        with conn.session as s:
            s.execute(text('''INSERT INTO midia (titulo, tipo, plataforma, status, nota, comentario, sinopse, data_registro, capa_url, nickname, data_inicio, data_fim, dono) VALUES (:t, :tp, :p, :s, :n, :c, :sin, :dr, :url, :nick, :di, :df, :owner)'''),
                {"t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, "c": comentario, "sin": sinopse, "dr": data_reg, "url": capa_url, "nick": nickname, "di": d_ini, "df": d_fim, "owner": dono})
            s.commit()
        st.cache_data.clear()
    except Exception as e: st.error(f"Erro save: {e}")

def update_midia(id_item, titulo, tipo, plataforma, status, nota, comentario, sinopse, data_reg, capa_url, nickname, d_ini, d_fim, travar_nota, dono):
    trava_int = 1 if travar_nota else 0
    try:
        with conn.session as s:
            s.execute(text('''UPDATE midia SET titulo=:t, tipo=:tp, plataforma=:p, status=:s, nota=:n, comentario=:c, sinopse=:sin, data_registro=:dr, capa_url=:url, nickname=:nick, data_inicio=:di, data_fim=:df, travar_nota=:lock WHERE id=:id AND dono=:owner'''),
                {"t": titulo, "tp": tipo, "p": plataforma, "s": status, "n": nota, "c": comentario, "sin": sinopse, "dr": data_reg, "url": capa_url, "nick": nickname, "di": d_ini, "df": d_fim, "lock": trava_int, "id": id_item, "owner": dono})
            s.commit()
        st.cache_data.clear()
    except Exception as e: st.error(f"Erro update: {e}")

def delete_midia(id_item, dono):
    try:
        with conn.session as s:
            if s.execute(text("SELECT id FROM midia WHERE id=:id AND dono=:owner"), {"id": id_item, "owner": dono}).fetchone():
                s.execute(text('DELETE FROM episodios WHERE serie_id=:id'), {"id": id_item})
                s.execute(text('DELETE FROM midia WHERE id=:id'), {"id": id_item}); s.commit()
            else: st.error("Erro permissão.")
        st.cache_data.clear()
    except Exception as e: st.error(f"Erro delete: {e}")

def get_data(dono, tipo_filtro=None):
    query, params = "SELECT * FROM midia WHERE dono = :owner", {"owner": dono}
    if tipo_filtro: query += " AND tipo = :tp"; params["tp"] = tipo_filtro
    df = conn.query(query, params=params, ttl=0)
    if not df.empty:
        for col in ['data_registro', 'data_inicio', 'data_fim']: df[col] = pd.to_datetime(df[col], errors='coerce')
        if 'sinopse' not in df.columns: df['sinopse'] = ""
        df['ano'], df['mes_nome'] = df['data_registro'].dt.year, df['data_registro'].dt.month_name()
        df['nickname'] = df['nickname'].fillna("")
        df['nota'] = pd.to_numeric(df['nota'], errors='coerce').fillna(0.0)
    return df

# --- EPISODIOS ---
def add_episodio(serie_id, ep_num, titulo, nota, data):
    with conn.session as s:
        s.execute(text('INSERT INTO episodios (serie_id, episodio_num, titulo_ep, nota, data_assistido) VALUES (:sid, :enum, :tit, :nt, :dt)'),
            {"sid": serie_id, "enum": ep_num, "tit": titulo, "nt": nota, "dt": data}); s.commit()
    st.cache_data.clear(); recalcular_nota_serie(serie_id)

def recalcular_nota_serie(serie_id):
    df_midia = conn.query("SELECT travar_nota FROM midia WHERE id=:id", params={"id": serie_id}, ttl=0)
    if not df_midia.empty and df_midia.iloc[0]['travar_nota'] == 1: return
    res = conn.query("SELECT AVG(nota) as media, MIN(data_assistido) as inicio, MAX(data_assistido) as fim FROM episodios WHERE serie_id=:id", params={"id": serie_id}, ttl=0)
    if not res.empty:
        media, ini, fim = res.iloc[0]['media'] or 0, res.iloc[0]['inicio'], res.iloc[0]['fim']
        with conn.session as s:
            if ini and fim: s.execute(text("UPDATE midia SET nota=:n, data_inicio=:di, data_fim=:df WHERE id=:id"), {"n": float(media), "di": ini, "df": fim, "id": serie_id})
            else: s.execute(text("UPDATE midia SET nota=:n WHERE id=:id"), {"n": float(media), "id": serie_id})
            s.commit()

def get_episodios(serie_id):
    df = conn.query("SELECT * FROM episodios WHERE serie_id=:id ORDER BY episodio_num", params={"id": serie_id}, ttl=0)
    if not df.empty: df['data_assistido'] = pd.to_datetime(df['data_assistido'])
    return df

def salvar_edicao_tabela_eps(serie_id, edits):
    if not edits: return
    with conn.session as s:
        df_orig = get_episodios(serie_id)
        for idx, chg in edits['edited_rows'].items():
            if int(idx) < len(df_orig):
                ep_id = int(df_orig.iloc[int(idx)]['id'])
                for k, v in chg.items():
                    if k == "data_assistido": s.execute(text("UPDATE episodios SET data_assistido=:v WHERE id=:id"), {"v": pd.to_datetime(v).date(), "id": ep_id})
                    else: s.execute(text(f"UPDATE episodios SET {k}=:v WHERE id=:id"), {"v": v, "id": ep_id})
        for idx in edits['deleted_rows']:
             if int(idx) < len(df_orig): s.execute(text("DELETE FROM episodios WHERE id=:id"), {"id": int(df_orig.iloc[int(idx)]['id'])})
        s.commit()
    st.cache_data.clear(); recalcular_nota_serie(serie_id); st.toast("Atualizado!")

# --- CARD ---
def gerar_card(titulo, nota, comentario, url_imagem, nickname, sinopse_bd):
    # Lógica: Se não tem comentário, usa a sinopse. Se não tem nenhum, fica vazio.
    texto_para_exibir = comentario if comentario and comentario.strip() else sinopse_bd if sinopse_bd else ""
    
    try: img = Image.open(BytesIO(requests.get(url_imagem, timeout=3).content)).convert("RGBA")
    except: img = Image.new('RGB', (400, 600), color='#2b2b2b')
    largura = 400
    img = img.resize((largura, int(float(img.size[1]) * (largura / float(img.size[0])))), Image.Resampling.LANCZOS)
    card = Image.new('RGB', (largura, img.size[1] + 160), (15, 15, 15)); card.paste(img, (0, 0))
    draw = ImageDraw.Draw(card)
    
    # Nota no topo
    if nota and nota > 0:
        c_bg, c_tx = ('#FFD700', '#000') if nota >= 75 else ('#C0C0C0', '#000') if nota >= 50 else ('#B22222', '#FFF')
        draw.ellipse((largura-90, 20, largura-20, 90), fill=c_bg)
        try: fnt = ImageFont.truetype("arial.ttf", 35)
        except: fnt = ImageFont.load_default()
        draw.text((largura-55, 55), str(int(nota)), fill=c_tx, font=fnt, anchor="mm")
        
    try: f_t, f_c, f_n = ImageFont.truetype("arial.ttf", 26), ImageFont.truetype("arial.ttf", 16), ImageFont.truetype("arial.ttf", 14)
    except: f_t = f_c = f_n = ImageFont.load_default()
    
    y = img.size[1] + 20
    draw.text((15, y), f"{titulo[:30]}", fill="#FFF", font=f_t)
    
    # --- CORREÇÃO: QUEBRA DE LINHA NO COMENTÁRIO/SINOPSE ---
    # Envolve o texto para caber em aprox 45 caracteres por linha (ajuste fino para largura 400px)
    linhas = textwrap.wrap(f"\"{texto_para_exibir}\"", width=45)
    
    # Limita a 3 linhas para não estourar verticalmente o card se o texto for enorme
    if len(linhas) > 3:
        linhas = linhas[:3]
        linhas[-1] += "..."
        
    y_texto = y + 40
    for linha in linhas:
        draw.text((15, y_texto), linha, fill="#CCC", font=f_c)
        y_texto += 20 # Espaçamento entre linhas
        
    if nickname: 
        bb = draw.textbbox((0,0), f"- {nickname}", font=f_n)
        draw.text((largura - (bb[2]-bb[0]) - 15, y + 130), f"- {nickname.title()}", fill="#999", font=f_n)
    
    buf = BytesIO(); card.save(buf, format="PNG"); return buf.getvalue()

# --- ACTIONS & CALLBACKS ---
def ativar_edicao(id_item):
    """Callback para ativar a edição limpando o estado anterior"""
    keys_edicao = [
        "edit_titulo", "edit_tipo", "edit_plataforma", "edit_status", 
        "edit_nota", "edit_comentario", "edit_capa", "edit_nick", 
        "edit_travar", "edit_sinopse", "edit_data_inicio", "edit_data_fim"
    ]
    for key in keys_edicao:
        if key in st.session_state:
            del st.session_state[key]
            
    st.session_state.edit_id = id_item

def salvar_novo_registro():
    t = st.session_state.get('novo_titulo', '')
    tp = st.session_state.get('novo_tipo_manual', 'Filme')
    p = st.session_state.get('nova_plataforma', 'Outros')
    s = st.session_state.get('novo_status', 'Em Andamento')
    n = st.session_state.get('nova_nota', 0)
    c = st.session_state.get('novo_comentario', '')
    url, nick = st.session_state.get('novo_capa', ''), st.session_state.user
    sin = st.session_state.get('novo_sinopse_texto', '')
    d_ini = st.session_state.get('nova_data_inicio')
    d_fim = st.session_state.get('nova_data_fim', datetime.now().date())
    
    erros = []
    if not t.strip(): erros.append("Título obrigatório.")
    # CORREÇÃO: Removida a obrigatoriedade de comentário
    if s == "Concluído" and tp != "Série" and n == 0: erros.append("Se for 'Concluído', é necessário dar uma Nota.")
    
    if erros: 
        st.session_state.msg_erro = erros
        st.session_state.msg_sucesso = None
    else:
        add_midia(t, tp, p, s, n, c, sin, datetime.now().date(), url, nick, d_ini, d_fim, st.session_state.user)
        for k in ['novo_titulo', 'novo_comentario', 'novo_capa', 'novo_sinopse_texto']: 
            if k in st.session_state: st.session_state[k] = ""
        st.session_state.msg_sucesso = f"✅ {t} salvo!"
        st.session_state.msg_erro = None

def atualizar_registro():
    id_e = st.session_state.edit_id
    t = st.session_state.get('edit_titulo', '')
    tp = st.session_state.get('edit_tipo', '')
    p = st.session_state.get('edit_plataforma', '')
    s = st.session_state.get('edit_status', '')
    n = st.session_state.get('edit_nota', 0)
    c = st.session_state.get('edit_comentario', '')
    url = st.session_state.get('edit_capa', '')
    nick = st.session_state.get('edit_nick', '')
    tr = st.session_state.get('edit_travar', False)
    sin = st.session_state.get('edit_sinopse', '')
    d_ini = st.session_state.get('edit_data_inicio')
    d_fim = st.session_state.get('edit_data_fim')
    
    orig = conn.query("SELECT data_registro FROM midia WHERE id=:id", params={"id": id_e}, ttl=0)
    dr = orig.iloc[0]['data_registro'] if not orig.empty else datetime.now().date()
    
    if not t.strip(): 
        st.session_state.msg_erro_edit = ["Título obrigatório."]
        return

    update_midia(id_e, t, tp, p, s, n, c, sin, dr, url, nick, d_ini, d_fim, tr, st.session_state.user)
    
    st.session_state.msg_sucesso_edit = f"✅ {t} atualizado!"
    st.session_state.edit_id = None

def render_categoria_page(tit, cat, f_ano, f_mes):
    st.header(f"{tit}")
    if st.session_state.serie_manager_id and cat == "Série":
        info = conn.query("SELECT * FROM midia WHERE id=:id AND dono=:o", params={"id": st.session_state.serie_manager_id, "o": st.session_state.user}, ttl=0)
        if not info.empty:
            with st.container(border=True):
                st.markdown(f"### 📺 Episódios: **{info.iloc[0]['titulo']}**")
                c1, c2, c3, c4, c5 = st.columns([1,3,1.5,1.5,1])
                with c1: st.number_input("Ep Nº", 1, value=1, key="ep_num")
                with c2: st.text_input("Título", key="ep_tit")
                with c3: st.date_input("Data", datetime.now(), key="ep_data")
                with c4: st.number_input("Nota", 0, 100, 80, key="ep_nota")
                with c5: 
                    st.write(""); st.write("")
                    st.button("➕", on_click=lambda: (add_episodio(st.session_state.serie_manager_id, st.session_state.ep_num, st.session_state.ep_tit, st.session_state.ep_nota, st.session_state.ep_data), st.session_state.update({"ep_tit": ""})))
                eps = get_episodios(st.session_state.serie_manager_id)
                if not eps.empty:
                    st.data_editor(eps[['episodio_num', 'titulo_ep', 'nota', 'data_assistido']], 
                        column_config={"episodio_num": st.column_config.NumberColumn("#", width="small"), "data_assistido": st.column_config.DateColumn("Data", format="DD/MM/YYYY")},
                        use_container_width=True, num_rows="dynamic", key="editor_eps",
                        on_change=lambda: salvar_edicao_tabela_eps(st.session_state.serie_manager_id, st.session_state.editor_eps))
                if st.button("Fechar"): st.session_state.serie_manager_id = None; st.rerun()
            st.markdown("---")

    if st.session_state.edit_id:
        row = conn.query("SELECT * FROM midia WHERE id=:id AND dono=:o", params={"id": st.session_state.edit_id, "o": st.session_state.user}, ttl=0)
        if not row.empty:
            r = row.iloc[0]
            if r['tipo'] == cat:
                with st.expander(f"✏️ Editando: {r['titulo']}", expanded=True):
                    c1, c2 = st.columns(2)
                    with c1:
                        st.text_input("Título", value=r['titulo'], key="edit_titulo")
                        st.text_input("Categoria", value=r['tipo'], disabled=True, key="edit_tipo")
                        lp = MAPA_PLATAFORMAS.get(r['tipo'], ["Outros"])
                        ix = lp.index(r['plataforma']) if r['plataforma'] in lp else 0
                        st.selectbox("Plataforma", lp, index=ix, key="edit_plataforma")
                    with c2:
                        ls = ["Concluído", "Em Andamento", "Abandonado"]
                        st.selectbox("Status", ls, index=ls.index(r['status']) if r['status'] in ls else 1, key="edit_status")
                        di = pd.to_datetime(r['data_inicio']).date() if r['data_inicio'] else None
                        df = pd.to_datetime(r['data_fim']).date() if r['data_fim'] else datetime.now().date()
                        if cat in ["Jogo", "Livro", "Série"]:
                            cc1, cc2 = st.columns(2)
                            cc1.date_input("Início", value=di, key="edit_data_inicio")
                            cc2.date_input("Fim", value=df, key="edit_data_fim")
                        else: st.date_input("Data Assistido", value=df, key="edit_data_fim")
                        st.text_input("Capa URL", value=r['capa_url'], key="edit_capa")
                    
                    st.text_area("Sinopse (App)", value=r['sinopse'] if r['sinopse'] else "", key="edit_sinopse")
                    st.text_input("Nick", value=r['nickname'], key="edit_nick")
                    if cat == "Série":
                        lk, nt = st.columns([1, 2])
                        lk.checkbox("Travar Nota?", value=bool(r['travar_nota']), key="edit_travar")
                        nt.slider("Nota", 0, 100, int(r['nota']), key="edit_nota")
                    else: st.slider("Nota", 0, 100, int(r['nota']), key="edit_nota")
                    st.text_area("Comentário Pessoal", value=r['comentario'], key="edit_comentario")
                    b1, b2, b3 = st.columns([1,1,3])
                    b1.button("Salvar", type="primary", on_click=atualizar_registro)
                    b2.button("Apagar", on_click=lambda: (delete_midia(st.session_state.edit_id, st.session_state.user), st.session_state.update({"edit_id": None})))
                    if b3.button("Cancelar"): st.session_state.edit_id = None; st.rerun()
                st.divider()

    df = get_data(st.session_state.user, cat)
    if df.empty: st.info("Vazio."); return
    if f_ano != "Todos": df = df[df['data_registro'].dt.year == int(f_ano)]
    if f_mes != "Todos":
        m_map = {"Janeiro": 1, "Fevereiro": 2, "Março": 3, "Abril": 4, "Maio": 5, "Junho": 6, "Julho": 7, "Agosto": 8, "Setembro": 9, "Outubro": 10, "Novembro": 11, "Dezembro": 12}
        if f_mes in m_map: df = df[df['data_registro'].dt.month == m_map[f_mes]]
    if df.empty: st.warning("Filtro sem resultados."); return

    t1, t2 = st.tabs(["Biblioteca", "Analytics"])
    with t1:
        c_sort, _ = st.columns([1,3])
        with c_sort:
            s_map = {"Recente (Conclusão)": "end_date_desc", "Antigo (Conclusão)": "end_date_asc", "Melhor Nota": "score_desc", "Pior Nota": "score_asc", "A-Z": "title_asc"}
            op = st.selectbox("Ordenar", list(s_map.keys()), key=f"s_{cat}")
            sop = s_map[op]
        
        if sop == "end_date_desc": df = df.sort_values("data_fim", ascending=False)
        elif sop == "end_date_asc": df = df.sort_values("data_fim", ascending=True)
        elif sop == "score_desc": df = df.sort_values("nota", ascending=False)
        elif sop == "score_asc": df = df.sort_values("nota", ascending=True)
        elif sop == "title_asc": df = df.sort_values("titulo", ascending=True)
        
        cols = st.columns(5)
        for i, r in df.reset_index(drop=True).iterrows():
            with cols[i % 5]:
                with st.container(border=True):
                    st.image(r['capa_url'] if r['capa_url'] else "https://placehold.co/300x450")
                    st.markdown(f"**{r['titulo']}**")
                    ns = int(r['nota'])
                    if r['status'] == "Concluído": 
                        color = "green" if ns >= 75 else "orange" if ns >= 50 else "red"
                        st.markdown(f":{color}[**{ns}**]")
                    else: st.caption(r['status'])
                    if cat == "Série" and st.button("Eps", key=f"ep_{r['id']}"): st.session_state.serie_manager_id = r['id']; st.rerun()
                    with st.expander("Ver"):
                        st.caption(f"🗓️ Fim: {r['data_fim'].strftime('%d/%m/%Y') if pd.notnull(r['data_fim']) else '-'}")
                        if r['sinopse']: 
                            st.markdown(f"_{r['sinopse']}_")
                            st.divider()
                        if r['comentario']: st.markdown(f"💬 **Nota:** {r['comentario']}")
                        
                        st.button("✏️", key=f"e_{r['id']}", on_click=ativar_edicao, args=(r['id'],))
                        
                        # Passamos a sinopse também para a função de gerar card
                        cdata = gerar_card(r['titulo'], r['nota'], r['comentario'], r['capa_url'], r['nickname'], r['sinopse'])
                        st.download_button("📸", cdata, f"c_{r['id']}.png", key=f"d_{r['id']}")

    with t2:
        m1, m2, m3 = st.columns(3)
        m1.metric("Total", len(df))
        conc = df[df['status'] == "Concluído"]
        m2.metric("Concluídos", len(conc))
        m3.metric("Média", f"{conc['nota'].mean():.1f}" if not conc.empty else "-")
        st.divider()
        g1, g2 = st.columns(2)
        g1.plotly_chart(px.pie(df, names='status', title="Status", hole=0.4))
        g2.plotly_chart(px.bar(df['plataforma'].value_counts(), title="Plataformas", orientation='h'))

# --- MAIN ---
init_db()
if not st.session_state.user:
    c1,c2,c3 = st.columns([1,1,1])
    with c2:
        st.title("🦉 Wan Shi Tong")
        t1, t2 = st.tabs(["Entrar", "Criar"])
        with t1:
            with st.form("l"):
                u, p = st.text_input("User"), st.text_input("Pass", type="password")
                if st.form_submit_button("Go") and u and p: login_user(u, p)
        with t2:
            with st.form("r"):
                u, p = st.text_input("New User"), st.text_input("New Pass", type="password")
                if st.form_submit_button("Reg") and u and p: 
                    if register_user(u, p): st.info("Login please.")
else:
    st.sidebar.title(f"Olá, {st.session_state.user.title()}")
    if st.sidebar.button("Sair"): st.session_state.user = None; st.rerun()
    st.sidebar.markdown("---")
    pg = st.sidebar.radio("Ir", ["Registrar Novo", "🎮 Jogos", "🎬 Filmes", "📺 Séries", "📖 Livros"])
    st.sidebar.markdown("---"); st.sidebar.caption(f"v{APP_VERSION} by {DEV_NAME}")
    
    fa = st.sidebar.selectbox("Ano", ["Todos"] + list(range(2024, datetime.now().year + 2)))
    fm = st.sidebar.selectbox("Mês", ["Todos", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"])

    if pg == "Registrar Novo":
        st.title("➕ Novo")
        
        # --- EXIBE AS MENSAGENS DE SUCESSO E ERRO ---
        if 'msg_sucesso' in st.session_state and st.session_state.msg_sucesso: 
            st.success(st.session_state.msg_sucesso)
            st.session_state.msg_sucesso = None # Limpa para não aparecer na próxima
            
        if 'msg_erro' in st.session_state and st.session_state.msg_erro: 
            for erro in st.session_state.msg_erro:
                st.error(f"❌ {erro}")
            st.session_state.msg_erro = None # Limpa para não aparecer na próxima

        # BUSCA SELETIVA
        bc1, bc2 = st.columns([3, 1])
        term = bc1.text_input("🔍 Busca Automática")
        cat_search = bc2.selectbox("Tipo Busca", ["Filme", "Série", "Livro"])
        if bc2.button("Buscar"): executar_busca(term, cat_search)
        
        # EXIBE RESULTADOS PARA SELEÇÃO
        if st.session_state.search_results:
            st.info("Selecione o resultado correto abaixo:")
            opts = {item['label']: item for item in st.session_state.search_results}
            sel = st.selectbox("Resultados Encontrados:", list(opts.keys()))
            if st.button("Utilizar Dados Selecionados"):
                confirmar_selecao(opts[sel], cat_search)
                st.rerun() 

        st.divider()

        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Título", key="novo_titulo")
            opt_tp = ["Jogo", "Filme", "Série", "Livro"]
            tp = st.selectbox("Categoria", opt_tp, key="novo_tipo_manual")
            st.session_state.novo_tipo = tp 
            st.selectbox("Plataforma", MAPA_PLATAFORMAS.get(tp, ["Outros"]), key="nova_plataforma")
            if tp in ["Jogo", "Livro", "Série"]:
                st.date_input("Data Início", value=None, key="nova_data_inicio")

        with c2:
            st.selectbox("Status", ["Concluído", "Em Andamento", "Abandonado"], key="novo_status")
            st.text_input("Capa URL", key="novo_capa")
            st.slider("Nota", 0, 100, 75, key="nova_nota")
        
        st.text_area("Sinopse Automática", height=150, key="novo_sinopse_texto")
        st.text_area("Seu Comentário", key="novo_comentario")
        st.button("Salvar", type="primary", on_click=salvar_novo_registro)
    else:
        mp = {"🎮 Jogos": "Jogo", "🎬 Filmes": "Filme", "📺 Séries": "Série", "📖 Livros": "Livro"}
        render_categoria_page(pg, mp[pg], fa, fm)

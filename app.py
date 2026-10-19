import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(
    page_title="TikTok Tag Counter",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

PROFILE_URL = "https://www.tiktok.com/@cortesbatalhasdosfamosos"
PROFILE_USERNAME = "cortesbatalhasdosfamosos"
TARGET_TAG = "Casalcheck2Clips5K"
ACTOR_ID = "poidata~tiktok-scraper"

# Visual identity
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: radial-gradient(ellipse at top left, #171c2e 0%, #0b0d13 48%, #0b0d13 100%); }
    [data-testid="stSidebar"] { background: #10131d; border-right: 1px solid #252a3a; }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1500px; }
    .hero {
        padding: 1.6rem 1.8rem; border: 1px solid #2a3044; border-radius: 22px;
        background: linear-gradient(120deg, rgba(124,58,237,.22), rgba(14,165,233,.10));
        margin-bottom: 1.3rem;
    }
    .hero-kicker { color: #a5b4fc; text-transform: uppercase; letter-spacing: .15em; font-size: .72rem; font-weight: 800; }
    .hero-title { color: #f8fafc; font-size: clamp(1.8rem, 3vw, 2.7rem); font-weight: 800; margin: .25rem 0 .35rem 0; }
    .hero-sub { color: #b6bfd2; font-size: .98rem; }
    .metric-card {
        background: linear-gradient(145deg, #171c2b, #111520); border: 1px solid #2a3044;
        border-radius: 18px; padding: 1.05rem 1.15rem; min-height: 126px;
        box-shadow: 0 8px 25px rgba(0,0,0,.12);
    }
    .metric-label { color: #aab4c8; font-size: .82rem; font-weight: 600; margin-bottom: .55rem; }
    .metric-value { color: #f8fafc; font-size: clamp(1.45rem, 2.2vw, 2.1rem); font-weight: 800; line-height: 1.1; }
    .metric-note { color: #8290a8; font-size: .72rem; margin-top: .45rem; }
    .section-title { color: #f1f5f9; font-size: 1.25rem; font-weight: 750; margin: 1.5rem 0 .7rem; }
    .tag-pill { display:inline-block; background:#252047; color:#c4b5fd; border:1px solid #51418a;
        padding:.28rem .7rem; border-radius:999px; font-size:.8rem; font-weight:700; }
    .profile-link { color:#93c5fd !important; text-decoration:none; font-weight:600; }
    div.stButton > button[kind="primary"] { border-radius: 12px; font-weight: 700; min-height: 2.8rem; }
    div[data-testid="stDataFrame"] { border: 1px solid #2a3044; border-radius: 14px; overflow: hidden; }
    .small-muted { color:#8d99af; font-size:.82rem; }
</style>
""", unsafe_allow_html=True)

def fmt_num(value):
    try:
        if value is None or value == "":
            return 0
        if isinstance(value, str):
            value = value.replace(",", "").replace(".", "") if value.count(",") == 1 and value.count(".") == 0 else value.replace(",", "")
        return int(float(value))
    except (ValueError, TypeError):
        return 0

def get_first(item, keys, default=0):
    for key in keys:
        value = item.get(key)
        if value is not None and value != "":
            return value
    return default

def normalized_tags(item):
    found = set()
    tags = item.get("hashtags")
    if isinstance(tags, list):
        for tag in tags:
            name = tag.get("name", "") if isinstance(tag, dict) else str(tag)
            name = str(name).strip().lstrip("#").casefold()
            if name:
                found.add(name)
    caption = str(item.get("text") or item.get("description") or item.get("video_description") or item.get("caption") or "")
    found.update(m.group(1).casefold() for m in re.finditer(r"(?<!\w)#([\w]+)", caption, flags=re.UNICODE))
    return found, caption

def author_username(item):
    author = item.get("authorMeta") or item.get("author") or {}
    if isinstance(author, dict):
        name = author.get("name") or author.get("uniqueId") or author.get("username") or ""
    else:
        name = str(author)
    return str(item.get("author_username") or item.get("uniqueId") or name).lstrip("@").casefold()

def video_url(item):
    url = item.get("webVideoUrl") or item.get("video_url") or item.get("share_url") or ""
    ident = item.get("id") or item.get("video_id")
    if not url and ident:
        url = f"https://www.tiktok.com/@{PROFILE_USERNAME}/video/{ident}"
    return url

def collect(token, max_items):
    endpoint = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
    payload = {
        "profiles": [PROFILE_USERNAME],
        "maxItems": int(max_items),
        "maxItemsPerQuery": min(int(max_items), 1000),
        "sortBy": "latest",
        "downloadVideos": False,
        "includeComments": False,
        "includeSubtitles": False,
    }
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        params={"format": "json", "clean": "true"},
        json=payload,
        timeout=300,
    )
    if not response.ok:
        raise RuntimeError(f"Apify retornou HTTP {response.status_code}: {response.text[:1000]}")
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("A resposta da coleta veio em formato inesperado. Confira o Actor e o token.")
    return data

def make_rows(raw_items):
    videos, seen = [], set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        # Skip explicit non-video records when the source labels record type.
        if item.get("type") and str(item.get("type")).casefold() not in ("video", "post"):
            continue
        author = author_username(item)
        if author and author != PROFILE_USERNAME.casefold():
            continue
        tags, caption = normalized_tags(item)
        if TARGET_TAG.casefold() not in tags:
            continue
        ident = str(item.get("id") or item.get("video_id") or video_url(item)).strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        created = item.get("createTimeISO") or item.get("published_at") or item.get("createTime") or item.get("create_time") or ""
        if isinstance(created, (int, float)):
            created = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        videos.append({
            "Data": str(created),
            "Perfil": "@" + (author or PROFILE_USERNAME),
            "Legenda": caption,
            "Link": video_url(item),
            "ID": ident,
            "Visualizações": fmt_num(get_first(item, ["playCount", "play_count", "plays", "viewCount", "views"])),
            "Curtidas": fmt_num(get_first(item, ["diggCount", "digg_count", "likes", "likeCount"])),
            "Comentários": fmt_num(get_first(item, ["commentCount", "comment_count", "comments"])),
            "Compartilhamentos": fmt_num(get_first(item, ["shareCount", "share_count", "shares"])),
        })
    return videos

def metric_card(label, value, note, emoji):
    return f"""
    <div class="metric-card">
      <div class="metric-label">{emoji} &nbsp; {label}</div>
      <div class="metric-value">{value:,}</div>
      <div class="metric-note">{note}</div>
    </div>
    """

with st.sidebar:
    st.markdown("## ⚙️ Configuração")
    st.markdown(f"[↗ Abrir perfil TikTok]({PROFILE_URL})")
    st.markdown(f"Hashtag: `#{TARGET_TAG}`")
    apify_token = st.text_input("Token da API do Apify", type="password", help="Não compartilhe este token.")
    max_items = st.select_slider(
        "Máximo de vídeos a coletar",
        options=[100, 200, 500, 1000, 2000, 5000],
        value=1000,
        format_func=lambda x: f"{x:,}".replace(",", ".") + " vídeos"
    )
    st.caption("Limite maior pode aumentar o tempo e o custo da coleta.")
    run_search = st.button("🔎 Buscar vídeos", type="primary", use_container_width=True)

st.markdown("""
<div class="hero">
  <div class="hero-kicker">Painel de desempenho · TikTok</div>
  <div class="hero-title">🎬 TikTok Tag Counter</div>
  <div class="hero-sub">Acompanhe os vídeos do perfil, filtre pela hashtag e veja o alcance total da campanha.</div>
  <br><span class="tag-pill">#Casalcheck2Clips5K</span>
</div>
""", unsafe_allow_html=True)

if run_search:
    if not apify_token.strip():
        st.error("Informe seu token do Apify na barra lateral para iniciar a busca.")
    else:
        with st.spinner("Buscando publicações e calculando as métricas..."):
            try:
                raw_items = collect(apify_token.strip(), max_items)
                st.session_state["results"] = make_rows(raw_items)
                st.session_state["raw_count"] = len(raw_items)
                st.session_state["searched"] = True
            except requests.Timeout:
                st.error("A coleta excedeu o tempo limite. Tente novamente com um limite menor.")
            except Exception as exc:
                st.error(f"Não foi possível concluir a busca: {exc}")

if "results" not in st.session_state:
    st.markdown("### Seu resumo aparecerá aqui")
    st.info("Informe o token do Apify à esquerda e clique em **Buscar vídeos** para calcular os totais.")
    st.markdown(f'<p class="small-muted">Perfil monitorado: <a class="profile-link" href="{PROFILE_URL}" target="_blank">@{PROFILE_USERNAME}</a></p>', unsafe_allow_html=True)
else:
    results = st.session_state["results"]
    totals = {
        "Visualizações": sum(r["Visualizações"] for r in results),
        "Curtidas": sum(r["Curtidas"] for r in results),
        "Comentários": sum(r["Comentários"] for r in results),
        "Compartilhamentos": sum(r["Compartilhamentos"] for r in results),
    }
    st.markdown('<div class="section-title">📊 Resumo geral</div>', unsafe_allow_html=True)
    cols = st.columns(5)
    metrics = [
        ("Vídeos encontrados", len(results), "Vídeos únicos", "🎬"),
        ("Visualizações totais", totals["Visualizações"], "Soma das visualizações", "👁️"),
        ("Curtidas totais", totals["Curtidas"], "Soma das curtidas", "❤️"),
        ("Comentários totais", totals["Comentários"], "Soma dos comentários", "💬"),
        ("Compartilhamentos", totals["Compartilhamentos"], "Soma dos compartilhamentos", "↗️"),
    ]
    for col, (label, value, note, emoji) in zip(cols, metrics):
        with col:
            st.markdown(metric_card(label, value, note, emoji), unsafe_allow_html=True)

    st.markdown('<div class="section-title">📋 Vídeos encontrados</div>', unsafe_allow_html=True)
    st.caption(f"Perfil: @{PROFILE_USERNAME} · Hashtag exata: #{TARGET_TAG} · Itens coletados: {st.session_state.get('raw_count', 0)}")
    if not results:
        st.warning("Nenhum vídeo correspondente foi encontrado nos itens coletados. Isso não garante que não existam outros vídeos: a coleta pode não ter recuperado todas as publicações.")
    else:
        df = pd.DataFrame(results)
        st.dataframe(
            df[["Data", "Perfil", "Legenda", "Link", "Visualizações", "Curtidas", "Comentários", "Compartilhamentos"]],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Abrir vídeo", display_text="Ver no TikTok"),
                "Legenda": st.column_config.TextColumn("Legenda", width="large"),
                "Visualizações": st.column_config.NumberColumn("Visualizações", format="%d"),
                "Curtidas": st.column_config.NumberColumn("Curtidas", format="%d"),
                "Comentários": st.column_config.NumberColumn("Comentários", format="%d"),
                "Compartilhamentos": st.column_config.NumberColumn("Compartilhamentos", format="%d"),
            }
        )
        st.download_button(
            "⬇️ Exportar lista CSV",
            data=df.to_csv(index=False).encode("utf-8-sig"),
            file_name="tiktok_casalcheck2clips5k.csv",
            mime="text/csv"
        )
    st.markdown('<p class="small-muted">Os totais representam apenas os vídeos retornados pelo coletor. Métricas ausentes na fonte podem aparecer como zero.</p>', unsafe_allow_html=True)

st.divider()
st.caption("TikTok Tag Counter · Use o token do Apify com segurança. A coleta depende da disponibilidade e dos limites do serviço externo.")

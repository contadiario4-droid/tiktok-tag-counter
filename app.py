import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="TikTok Tag Counter", page_icon="🎬", layout="wide")

DEFAULT_PROFILE = "cortesbatalhasdosfamosos"
DEFAULT_TAG = "Casalcheck2Clips5K"
ACTOR_ID = "poidata~tiktok-scraper"

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: Inter, sans-serif; }
.stApp { background: radial-gradient(ellipse at top left, #171c2e 0%, #0b0d13 48%, #0b0d13 100%); }
[data-testid="stSidebar"] { background: #10131d; border-right: 1px solid #252a3a; }
.block-container { max-width: 1500px; padding-top: 2rem; }
.hero { padding: 1.6rem 1.8rem; border: 1px solid #2a3044; border-radius: 22px; background: linear-gradient(120deg, rgba(124,58,237,.22), rgba(14,165,233,.10)); margin-bottom: 1.3rem; }
.kicker { color:#a5b4fc; text-transform:uppercase; letter-spacing:.15em; font-size:.72rem; font-weight:800; }
.hero-title { color:#f8fafc; font-size:clamp(1.8rem,3vw,2.7rem); font-weight:800; margin:.25rem 0; }
.sub { color:#b6bfd2; }
.metric { background:linear-gradient(145deg,#171c2b,#111520); border:1px solid #2a3044; border-radius:18px; padding:1rem; min-height:120px; }
.metric-label { color:#aab4c8; font-size:.82rem; font-weight:600; margin-bottom:.5rem; }
.metric-value { color:#f8fafc; font-size:clamp(1.4rem,2.2vw,2rem); font-weight:800; }
.metric-note { color:#8290a8; font-size:.72rem; margin-top:.4rem; }
.section { color:#f1f5f9; font-size:1.25rem; font-weight:750; margin:1.5rem 0 .7rem; }
div.stButton>button, div.stDownloadButton>button { border-radius:12px; font-weight:700; min-height:2.7rem; }
</style>
""", unsafe_allow_html=True)

def n(value):
    try:
        if value is None or value == "":
            return 0
        if isinstance(value, str):
            value = value.replace(",", "")
        return int(float(value))
    except (ValueError, TypeError):
        return 0

def first(item, keys, default=0):
    for key in keys:
        v = item.get(key)
        if v is not None and v != "":
            return v
    return default

def tags_and_caption(item):
    found = set()
    raw_tags = item.get("hashtags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            name = tag.get("name", "") if isinstance(tag, dict) else str(tag)
            if name.strip():
                found.add(name.strip().lstrip("#").casefold())
    caption = str(item.get("text") or item.get("description") or item.get("video_description") or item.get("caption") or item.get("title") or "")
    found.update(m.group(1).casefold() for m in re.finditer(r"(?<!\w)#([\w]+)", caption, flags=re.UNICODE))
    return found, caption

def get_author(item):
    author = item.get("authorMeta") or item.get("author") or {}
    if isinstance(author, dict):
        name = author.get("name") or author.get("uniqueId") or author.get("username") or ""
    else:
        name = str(author)
    return str(item.get("author_username") or item.get("uniqueId") or name).lstrip("@").casefold()

def get_avatar_url(item):
    """Tenta extrair a foto do perfil dos metadados retornados pelo coletor."""
    author = item.get("authorMeta") or item.get("author") or item.get("author_info") or {}
    if not isinstance(author, dict):
        return ""
    for key in ("avatar", "avatarUrl", "avatar_url", "avatarThumb", "avatarLarger", "profilePicture", "profile_picture", "cover"):
        value = author.get(key)
        if isinstance(value, str) and value.startswith("https://"):
            return value
        if isinstance(value, dict):
            for nested_key in ("url_list", "urlList", "urls"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    for url in nested:
                        if isinstance(url, str) and url.startswith("https://"):
                            return url
            for nested_key in ("url", "uri"):
                url = value.get(nested_key)
                if isinstance(url, str) and url.startswith("https://"):
                    return url
    return ""

def estimate_suspicious_views(video_rows):
    """Heurística exploratória; não confirma bots nem views compradas."""
    views = sum(row["Visualizações"] for row in video_rows)
    likes = sum(row["Curtidas"] for row in video_rows)
    comments = sum(row["Comentários"] for row in video_rows)
    shares = sum(row["Compartilhamentos"] for row in video_rows)
    interactions = likes + comments + shares
    if views <= 0:
        return {"suspect": 0, "risk": "Indeterminado", "rate": 0.0, "reason": "Não há visualizações válidas para avaliar."}
    rate = interactions / views
    # Regra inicial conservadora e explícita: abaixo de 0,5% de interações totais,
    # calcula apenas uma estimativa de sinal fraco, limitada a 80% das views.
    if rate < 0.005:
        fraction = min(0.80, max(0.0, (0.005 - rate) / 0.005))
        risk = "Alto" if rate < 0.001 else "Médio"
        reason = "Taxa de interações baixa em relação às visualizações. Isso pode ter várias causas legítimas e não comprova fraude."
    elif rate < 0.01:
        fraction = 0.0
        risk = "Baixo"
        reason = "A taxa de interações não acionou a regra inicial de alerta. Isso não garante autenticidade."
    else:
        fraction = 0.0
        risk = "Baixo"
        reason = "A taxa de interações não acionou a regra inicial de alerta. Isso não garante autenticidade."
    return {"suspect": round(views * fraction), "risk": risk, "rate": rate * 100, "reason": reason}

def get_url(item, username):
    url = item.get("webVideoUrl") or item.get("video_url") or item.get("share_url") or ""
    video_id = item.get("id") or item.get("video_id")
    if not url and video_id:
        url = f"https://www.tiktok.com/@{username}/video/{video_id}"
    return url

def collect(token, username, limit):
    # Confirme na página do Actor se o esquema de entrada abaixo ainda é o atual.
    endpoint = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
    payload = {
        "profiles": [username],
        "maxItems": int(limit),
        "maxItemsPerQuery": min(int(limit), 1000),
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
        raise RuntimeError(f"Apify retornou HTTP {response.status_code}: {response.text[:700]}")
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("Resposta inesperada do coletor. Verifique o Actor configurado.")
    return data

def parse_items(raw_items, username, tag):
    found, seen = [], set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        author = get_author(item)
        if author and author != username.casefold():
            continue
        item_tags, caption = tags_and_caption(item)
        if tag.casefold() not in item_tags:
            continue
        url = get_url(item, username)
        ident = str(item.get("id") or item.get("video_id") or url).strip()
        if not ident or ident in seen:
            continue
        seen.add(ident)
        created = item.get("createTimeISO") or item.get("published_at") or item.get("createTime") or item.get("create_time") or ""
        if isinstance(created, (int, float)):
            created = datetime.fromtimestamp(created, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        avatar_url = get_avatar_url(item)
        found.append({
            "Data": str(created),
            "Perfil": "@" + username,
            "Foto do perfil": avatar_url,
            "Legenda": caption,
            "Link": url,
            "Visualizações": n(first(item, ["playCount", "play_count", "plays", "viewCount", "views"])),
            "Curtidas": n(first(item, ["diggCount", "digg_count", "likes", "likeCount"])),
            "Comentários": n(first(item, ["commentCount", "comment_count", "comments"])),
            "Compartilhamentos": n(first(item, ["shareCount", "share_count", "shares"])),
        })
    return found

def metric(label, value, note, emoji):
    return f'<div class="metric"><div class="metric-label">{emoji} &nbsp; {label}</div><div class="metric-value">{value:,}</div><div class="metric-note">{note}</div></div>'

with st.sidebar:
    st.markdown("## 🔎 Fazer uma busca")
    profile_input = st.text_input("Perfil do TikTok (@)", value="@" + DEFAULT_PROFILE, placeholder="@seuperfil")
    hashtag_input = st.text_input("Hashtag", value="#" + DEFAULT_TAG, placeholder="#SuaHashtag")
    max_items = st.select_slider("Máximo de itens solicitados", options=[100, 200, 500, 1000, 2000, 5000], value=1000, format_func=lambda x: f"{x:,}".replace(",", "."))
    st.caption("O limite é uma solicitação máxima, não uma garantia. Coletas grandes podem consumir mais créditos.")
    search = st.button("🔎 Buscar vídeos", type="primary", use_container_width=True)
    st.divider()
    st.caption("O token fica no servidor, não é solicitado aos visitantes.")

st.markdown(f"""
<div class="hero">
 <div class="kicker">Painel público de desempenho</div>
 <div class="hero-title">🎬 TikTok Tag Counter</div>
 <div class="sub">Consulte vídeos por perfil e hashtag, confira os totais e exporte os resultados.</div>
</div>
""", unsafe_allow_html=True)

if search:
    username = profile_input.strip().lstrip("@").strip()
    tag = hashtag_input.strip().lstrip("#").strip()
    if not username or not re.fullmatch(r"[A-Za-z0-9._]{2,24}", username):
        st.error("Digite um @ válido do TikTok.")
    elif not tag or not re.fullmatch(r"[\w]+", tag, flags=re.UNICODE):
        st.error("Digite uma hashtag válida, sem espaços.")
    else:
        try:
            token = st.secrets["APIFY_TOKEN"]
        except Exception:
            token = ""
        if not token:
            st.error("O administrador ainda precisa configurar APIFY_TOKEN em Streamlit → Manage app → Settings → Secrets. Não peça o token aos visitantes.")
        else:
            with st.spinner(f"Consultando @{username} e filtrando #{tag}..."):
                try:
                    raw = collect(str(token).strip(), username, max_items)
                    st.session_state["results"] = parse_items(raw, username, tag)
                    st.session_state["raw_count"] = len(raw)
                    st.session_state["profile_avatar"] = next((get_avatar_url(item) for item in raw if isinstance(item, dict) and get_avatar_url(item)), "")
                    st.session_state["current_profile"] = username
                    st.session_state["current_tag"] = tag
                    st.session_state["searched"] = True
                except requests.Timeout:
                    st.error("A coleta excedeu o tempo limite. Tente um limite menor.")
                except Exception as e:
                    st.error(f"Não foi possível concluir a busca: {e}")

if "results" not in st.session_state:
    st.markdown("### Comece sua consulta")
    st.info("Informe qualquer perfil público do TikTok e a hashtag desejada na barra lateral. Os totais aparecerão após a coleta.")
else:
    results = st.session_state["results"]
    profile_col, profile_info_col = st.columns([1, 5], vertical_alignment="center")
    with profile_col:
        avatar = st.session_state.get("profile_avatar", "")
        if avatar:
            st.image(avatar, width=112)
        else:
            st.markdown("<div style='width:96px;height:96px;border-radius:50%;background:#252a3a;display:flex;align-items:center;justify-content:center;font-size:2.5rem'>🎬</div>", unsafe_allow_html=True)
    with profile_info_col:
        st.markdown(f"### @{st.session_state['current_profile']}")
        st.markdown(f"[Abrir perfil no TikTok](https://www.tiktok.com/@{st.session_state['current_profile']})")
        if not avatar:
            st.caption("O coletor não retornou uma foto de perfil nesta busca; isso pode variar conforme a disponibilidade dos dados.")
    totals = {
        "Visualizações": sum(x["Visualizações"] for x in results),
        "Curtidas": sum(x["Curtidas"] for x in results),
        "Comentários": sum(x["Comentários"] for x in results),
        "Compartilhamentos": sum(x["Compartilhamentos"] for x in results),
    }
    st.markdown('<div class="section">📊 Resumo geral</div>', unsafe_allow_html=True)
    st.caption(f'Perfil: @{st.session_state["current_profile"]} · Hashtag: #{st.session_state["current_tag"]} · Itens retornados pelo coletor: {st.session_state.get("raw_count", 0)}')
    cols = st.columns(5)
    data = [
        ("Vídeos encontrados", len(results), "Vídeos únicos", "🎬"),
        ("Visualizações totais", totals["Visualizações"], "Soma das visualizações", "👁️"),
        ("Curtidas totais", totals["Curtidas"], "Soma das curtidas", "❤️"),
        ("Comentários totais", totals["Comentários"], "Soma dos comentários", "💬"),
        ("Compartilhamentos", totals["Compartilhamentos"], "Soma dos compartilhamentos", "↗️"),
    ]
    for col, (label, value, note, emoji) in zip(cols, data):
        with col:
            st.markdown(metric(label, value, note, emoji), unsafe_allow_html=True)

    st.markdown('<div class="section">🕵️ Análise de visualizações suspeitas</div>', unsafe_allow_html=True)
    suspicious = estimate_suspicious_views(results)
    risk_color = {"Baixo": "#22c55e", "Médio": "#f59e0b", "Alto": "#ef4444"}.get(suspicious["risk"], "#94a3b8")
    suspect_cols = st.columns(3)
    with suspect_cols[0]:
        st.metric("Estimativa de visualizações suspeitas", f'{suspicious["suspect"]:,}'.replace(",", "."))
    with suspect_cols[1]:
        st.markdown(f'<div class="metric"><div class="metric-label">Nível de risco</div><div class="metric-value" style="color:{risk_color}">{suspicious["risk"]}</div><div class="metric-note">Sinal heurístico, não uma confirmação</div></div>', unsafe_allow_html=True)
    with suspect_cols[2]:
        st.metric("Interações / visualizações", f'{suspicious["rate"]:.2f}%')
    st.info(suspicious["reason"] + " A estimativa usa somente os totais públicos retornados pelo coletor; não identifica pessoas, bots ou compras de views. O limite inicial de 0,5% é uma regra heurística configurável, não um padrão oficial do TikTok.")

    st.markdown('<div class="section">📋 Vídeos encontrados</div>', unsafe_allow_html=True)
    if not results:
        st.warning("Nenhum vídeo correspondente foi encontrado nos itens retornados. Isso não prova que não existam outros vídeos.")
    else:
        df = pd.DataFrame(results)
        display_df = df.drop(columns=["Foto do perfil"], errors="ignore")
        st.dataframe(display_df, use_container_width=True, hide_index=True, column_config={
            "Link": st.column_config.LinkColumn("Vídeo", display_text="Abrir no TikTok"),
            "Legenda": st.column_config.TextColumn("Legenda", width="large"),
        })
        export_df = display_df
        st.download_button("⬇️ Exportar CSV", data=export_df.to_csv(index=False).encode("utf-8-sig"), file_name="tiktok_tag_counter.csv", mime="text/csv")

st.divider()
st.caption("As métricas e a cobertura dependem do que o coletor consegue acessar. Conteúdos privados, removidos ou não retornados ficam de fora; métricas ausentes podem aparecer como zero.")

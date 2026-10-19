import re
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="TikTok Tag Counter", page_icon="🎬", layout="wide")

PROFILE_URL = "https://www.tiktok.com/@cortesbatalhasdosfamosos"
PROFILE_USERNAME = "cortesbatalhasdosfamosos"
TARGET_TAG = "Casalcheck2Clips5K"
ACTOR_ID = "poidata~tiktok-scraper"

st.title("🎬 TikTok Tag Counter")
st.caption("Lista vídeos do perfil que contêm a hashtag exata e remove duplicados.")

with st.sidebar:
    st.header("Configuração")
    apify_token = st.text_input(
        "Token da API do Apify",
        type="password",
        help="Cole seu token do Apify. Ele é usado apenas nesta execução e não é salvo pelo app."
    )
    max_items = st.select_slider(
        "Máximo de vídeos a coletar",
        options=[20, 50, 100, 200, 500],
        value=100
    )
    st.markdown(f"**Perfil:** [@{PROFILE_USERNAME}]({PROFILE_URL})")
    st.markdown(f"**Hashtag:** `#{TARGET_TAG}`")
    run_search = st.button("Buscar vídeos", type="primary", use_container_width=True)

def normalized_tags(item):
    """Return normalized hashtag names from either structured hashtags or caption text."""
    found = set()
    tags = item.get("hashtags")
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                name = tag.get("name", "")
            else:
                name = str(tag)
            name = str(name).strip().lstrip("#").casefold()
            if name:
                found.add(name)
    caption = str(item.get("text") or item.get("description") or item.get("video_description") or "")
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
    if not url and item.get("id"):
        url = f"https://www.tiktok.com/@{PROFILE_USERNAME}/video/{item['id']}"
    return url

def collect():
    endpoint = f"https://api.apify.com/v2/acts/{ACTOR_ID}/run-sync-get-dataset-items"
    payload = {
        "profiles": [PROFILE_USERNAME],
        "maxItems": int(max_items),
        "maxItemsPerQuery": min(int(max_items), 200),
        "sortBy": "latest",
        "downloadVideos": False,
        "includeComments": False,
        "includeSubtitles": False,
    }
    response = requests.post(
        endpoint,
        headers={"Authorization": f"Bearer {apify_token}", "Content-Type": "application/json"},
        params={"format": "json", "clean": "true"},
        json=payload,
        timeout=300,
    )
    if not response.ok:
        detail = response.text[:1000]
        raise RuntimeError(f"Apify retornou HTTP {response.status_code}: {detail}")
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError("A resposta da coleta veio em formato inesperado. Confira o Actor e o token.")
    return data

if run_search:
    if not apify_token.strip():
        st.error("Cole seu token do Apify na barra lateral para iniciar a busca.")
    else:
        with st.spinner("Coletando vídeos públicos do perfil. Isso pode levar alguns minutos..."):
            try:
                raw_items = collect()
                videos = []
                seen = set()
                for item in raw_items:
                    if not isinstance(item, dict) or item.get("type", "video") != "video":
                        continue
                    author = author_username(item)
                    # The scraper should return the requested profile, but verify it when author metadata exists.
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
                        "Visualizações": item.get("playCount", item.get("plays", item.get("play_count", 0))) or 0,
                        "Curtidas": item.get("diggCount", item.get("likes", item.get("digg_count", 0))) or 0,
                        "Comentários": item.get("commentCount", item.get("comments", item.get("comment_count", 0))) or 0,
                        "Compartilhamentos": item.get("shareCount", item.get("shares", item.get("share_count", 0))) or 0,
                    })
                st.session_state["results"] = videos
                st.session_state["raw_count"] = len(raw_items)
            except requests.Timeout:
                st.error("A coleta excedeu o tempo limite. Tente novamente com um limite menor.")
            except Exception as exc:
                st.error(f"Não foi possível concluir a busca: {exc}")

results = st.session_state.get("results")
if results is not None:
    st.subheader("Resultados")
    a, b, c = st.columns(3)
    a.metric("Vídeos com a hashtag", len(results))
    b.metric("Itens retornados pela coleta", st.session_state.get("raw_count", 0))
    c.metric("Duplicados removidos", max(0, st.session_state.get("raw_count", 0) - len({r["ID"] for r in results})))
    if not results:
        st.info(
            "Nenhum vídeo correspondente foi encontrado nos itens coletados. "
            "Isso não prova que o perfil não tenha vídeos com a hashtag: o coletor pode não ter alcançado todas as publicações."
        )
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
        csv = df.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Baixar lista em CSV", data=csv,
                           file_name="tiktok_casalcheck2clips5k.csv",
                           mime="text/csv")
    st.caption("A contagem cobre somente os itens que o coletor conseguiu retornar nesta execução.")
else:
    st.info("Insira seu token do Apify e clique em “Buscar vídeos” para gerar a lista.")
    st.markdown(
        """
        **Como usar**
        1. Crie uma conta no Apify e gere um API token.
        2. Cole o token no campo da barra lateral.
        3. Escolha o limite de coleta e clique em **Buscar vídeos**.
        4. Confira a lista e exporte o CSV.
        """
    )

st.divider()
st.caption("Privacidade: o token é informado no campo protegido e não é gravado pelo código do aplicativo. Hospede o site em ambiente confiável e não compartilhe seu token.")

import re, time, requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

st.set_page_config(page_title="TikTok Tag Counter", page_icon="🎬", layout="wide")
DEFAULT_PROFILE = "cortesbatalhasdosfamosos"
DEFAULT_TAG = "Casalcheck2Clips5K"
ACTOR_ID = "poidata~tiktok-scraper"
UI_REFRESH_SECONDS = 5
MIN_SECONDS_BETWEEN_COLLECTIONS = 60
HTTP_TIMEOUT = 20

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] {font-family:Inter,sans-serif}
.stApp {background:radial-gradient(ellipse at top left,#171c2e 0%,#0b0d13 48%,#0b0d13 100%)}
[data-testid="stSidebar"] {background:#10131d;border-right:1px solid #252a3a}
.block-container {max-width:1500px;padding-top:2rem}
.hero {padding:1.6rem 1.8rem;border:1px solid #2a3044;border-radius:22px;background:linear-gradient(120deg,rgba(124,58,237,.22),rgba(14,165,233,.10));margin-bottom:1.3rem}
.kicker {color:#a5b4fc;text-transform:uppercase;letter-spacing:.15em;font-size:.72rem;font-weight:800}
.hero-title {color:#f8fafc;font-size:clamp(1.8rem,3vw,2.7rem);font-weight:800;margin:.25rem 0}
.sub {color:#b6bfd2}
.metric {background:linear-gradient(145deg,#171c2b,#111520);border:1px solid #2a3044;border-radius:18px;padding:1rem;min-height:115px}
.metric-label {color:#aab4c8;font-size:.82rem;font-weight:600;margin-bottom:.5rem}
.metric-value {color:#f8fafc;font-size:clamp(1.4rem,2.2vw,2rem);font-weight:800}
.metric-note {color:#8290a8;font-size:.72rem;margin-top:.4rem}
.section {color:#f1f5f9;font-size:1.25rem;font-weight:750;margin:1.5rem 0 .7rem}
div.stButton>button,div.stDownloadButton>button {border-radius:12px;font-weight:700;min-height:2.7rem}
.live-pill {display:inline-block;padding:.3rem .65rem;border-radius:999px;background:rgba(34,197,94,.12);color:#4ade80;border:1px solid rgba(34,197,94,.3);font-weight:700;font-size:.8rem}
</style>""", unsafe_allow_html=True)

def n(v):
    try: return int(float(v.replace(",", "") if isinstance(v,str) else v)) if v not in (None,"") else 0
    except (ValueError,TypeError): return 0

def first(item, keys, default=0):
    return next((item[k] for k in keys if item.get(k) not in (None,"")), default)

def tags_caption(item):
    tags=set()
    raw=item.get("hashtags")
    if isinstance(raw,list):
        for x in raw:
            val=x.get("name","") if isinstance(x,dict) else str(x)
            if val.strip(): tags.add(val.strip().lstrip("#").casefold())
    caption=str(item.get("text") or item.get("description") or item.get("video_description") or item.get("caption") or item.get("title") or "")
    tags.update(m.group(1).casefold() for m in re.finditer(r"(?<!\w)#([\w]+)",caption,flags=re.UNICODE))
    return tags,caption

def author_dict(item):
    for key in ("authorMeta","author","author_info","authorInfo","author_meta"):
        val=item.get(key)
        if isinstance(val,dict): return val
    return {}

def author_name(item):
    a=author_dict(item)
    name=(a.get("name") or a.get("uniqueId") or a.get("username") or a.get("unique_id") or "") if a else ""
    return str(item.get("author_username") or item.get("authorUniqueId") or item.get("uniqueId") or name).lstrip("@").casefold()

def avatar_url(item):
    a=author_dict(item)
    for key in ("avatar","avatarUrl","avatar_url","avatarThumb","avatarLarger","profilePicture","profile_picture","cover"):
        v=a.get(key)
        if isinstance(v,str) and v.startswith("https://"): return v
        if isinstance(v,dict):
            for nk in ("url_list","urlList","urls"):
                arr=v.get(nk)
                if isinstance(arr,list):
                    for u in arr:
                        if isinstance(u,str) and u.startswith("https://"): return u
            for nk in ("url","uri"):
                u=v.get(nk)
                if isinstance(u,str) and u.startswith("https://"): return u
    return ""

def parse_account_date(item):
    a=author_dict(item)
    keys=("createTime","create_time","createdAt","created_at","accountCreatedAt","account_created_at","registerTime","registration_date")
    raw=next((a.get(k) for k in keys if a.get(k) not in (None,"")),None)
    if raw is None: raw=next((item.get(k) for k in keys if item.get(k) not in (None,"")),None)
    if raw in (None,""): return None
    try:
        if isinstance(raw,(int,float)) or (isinstance(raw,str) and raw.strip().isdigit()):
            val=float(raw)
            if val>10_000_000_000: val/=1000
            return datetime.fromtimestamp(val,tz=timezone.utc)
        dt=datetime.fromisoformat(str(raw).strip().replace("Z","+00:00"))
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError): return None

def account_info(item):
    a=author_dict(item)
    created=parse_account_date(item)
    age=(datetime.now(timezone.utc)-created).total_seconds()/86400 if created else None
    return {"Conta criada em":created.strftime("%Y-%m-%d") if created else "Não informado",
        "Idade da conta (dias)":round(age,1) if age is not None and age>=0 else None,
        "Seguidores":n(first(a,["fans","followerCount","followers","followersCount","follower_count"],0)),
        "Seguindo":n(first(a,["following","followingCount","following_count"],0)),
        "Vídeos do perfil":n(first(a,["video","videoCount","video_count","awemeCount"],0)),
        "_age_days":age}

def apify_headers(token):
    return {"Authorization":f"Bearer {token}","Content-Type":"application/json"}

def start_collection(token, username, limit):
    """Starts an Apify run quickly; does not wait for the whole scrape to finish."""
    endpoint=f"https://api.apify.com/v2/acts/{ACTOR_ID}/runs"
    payload={"profiles":[username],"maxItems":int(limit),"maxItemsPerQuery":min(int(limit),1000),
        "sortBy":"latest","downloadVideos":False,"includeComments":False,"includeSubtitles":False}
    response=requests.post(endpoint,headers=apify_headers(token),json=payload,timeout=HTTP_TIMEOUT)
    if not response.ok:
        raise RuntimeError(f"Apify HTTP {response.status_code}: {response.text[:400]}")
    data=response.json().get("data",{})
    run_id=data.get("id")
    if not run_id: raise RuntimeError("Apify não retornou o ID da execução.")
    return {"id":run_id,"dataset_id":data.get("defaultDatasetId"),"status":data.get("status","READY")}

def poll_collection(token, run_id):
    response=requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}",
        headers=apify_headers(token),timeout=HTTP_TIMEOUT)
    if not response.ok: raise RuntimeError(f"Erro consultando execução Apify: HTTP {response.status_code}")
    return response.json().get("data",{})

def get_dataset(token, dataset_id, limit):
    if not dataset_id: raise RuntimeError("Execução finalizada sem dataset associado.")
    response=requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items",
        headers=apify_headers(token),params={"format":"json","clean":"true","limit":int(limit)},timeout=HTTP_TIMEOUT)
    if not response.ok: raise RuntimeError(f"Erro baixando resultados: HTTP {response.status_code}")
    data=response.json()
    if not isinstance(data,list): raise RuntimeError("A Apify devolveu um formato inesperado.")
    return data

def parse_items(raw, username, tag):
    out=[]; seen=set()
    for item in raw:
        if not isinstance(item,dict): continue
        author=author_name(item)
        if author and author != username.casefold(): continue
        tags,caption=tags_caption(item)
        if tag.casefold() not in tags: continue
        url=item.get("webVideoUrl") or item.get("video_url") or item.get("share_url") or ""
        vid=item.get("id") or item.get("video_id")
        if not url and vid: url=f"https://www.tiktok.com/@{username}/video/{vid}"
        ident=str(vid or url).strip()
        if not ident or ident in seen: continue
        seen.add(ident)
        created=item.get("createTimeISO") or item.get("published_at") or item.get("createTime") or item.get("create_time") or ""
        if isinstance(created,(int,float)): created=datetime.fromtimestamp(created,tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        ai=account_info(item)
        out.append({"Data do vídeo":str(created),"Perfil":"@"+username,"Foto do perfil":avatar_url(item),
            "Legenda":caption,"Link":url,"Visualizações":n(first(item,["playCount","play_count","plays","viewCount","views"])),
            "Curtidas":n(first(item,["diggCount","digg_count","likes","likeCount"])),
            "Comentários":n(first(item,["commentCount","comment_count","comments"])),
            "Compartilhamentos":n(first(item,["shareCount","share_count","shares"])),
            "Conta criada em":ai["Conta criada em"],"Idade da conta (dias)":ai["Idade da conta (dias)"],
            "Seguidores":ai["Seguidores"],"Seguindo":ai["Seguindo"],"Vídeos do perfil":ai["Vídeos do perfil"],
            "_age_days":ai["_age_days"]})
    return out

def analyze(rows,new_days,low_pct,min_views):
    views=sum(r["Visualizações"] for r in rows)
    interactions=sum(r["Curtidas"]+r["Comentários"]+r["Compartilhamentos"] for r in rows)
    recent=[r for r in rows if r.get("_age_days") is not None and 0<=r["_age_days"]<=new_days]
    unknown=sum(1 for r in rows if r.get("_age_days") is None)
    low=[]
    for r in rows:
        v=r["Visualizações"]; i=r["Curtidas"]+r["Comentários"]+r["Compartilhamentos"]
        if v>=min_views and v>0 and i/v*100<low_pct: low.append(r)
    combined=[]
    for r in rows:
        age=r.get("_age_days"); v=r["Visualizações"]
        i=r["Curtidas"]+r["Comentários"]+r["Compartilhamentos"]
        signals=int(age is not None and 0<=age<=new_days)
        signals+=int(v>=min_views and v>0 and i/v*100<low_pct)
        signals+=int(r.get("Seguidores",0)==0 and r.get("Vídeos do perfil",0)<=1)
        if signals>=2: combined.append(r)
    return views,interactions,recent,unknown,low,combined

def metric(label,value,note,emoji):
    return f'<div class="metric"><div class="metric-label">{emoji} &nbsp; {label}</div><div class="metric-value">{value:,}</div><div class="metric-note">{note}</div></div>'

with st.sidebar:
    st.markdown("## 🔎 Fazer uma busca")
    profile_input=st.text_input("Perfil do TikTok (@)",value="@"+DEFAULT_PROFILE,placeholder="@seuperfil")
    hashtag_input=st.text_input("Hashtag",value="#"+DEFAULT_TAG,placeholder="#SuaHashtag")
    max_items=st.select_slider("Máximo de itens por coleta",options=[100,200,500,1000,2000,5000],value=500,
        format_func=lambda x:f"{x:,}".replace(",","."))
    st.caption("Coletas menores tendem a terminar mais rápido e gastar menos créditos.")
    search=st.button("🔎 Buscar vídeos",type="primary",use_container_width=True)
    st.divider()
    st.caption("O token fica nos Secrets do Streamlit.")

st.markdown("""<div class="hero"><div class="kicker">Painel de desempenho</div>
<div class="hero-title">🎬 TikTok Tag Counter</div>
<div class="sub">Busca mais leve, atualização de status e filtros de sinais suspeitos.</div></div>""",unsafe_allow_html=True)

for k,v in [("monitoring",False),("results",None),("active_run",None),("collection_error",""),("last_collection_at",0.0)]:
    if k not in st.session_state: st.session_state[k]=v

def token_from_secrets():
    try: return str(st.secrets.get("APIFY_TOKEN","")).strip()
    except Exception: return ""

if search:
    username=profile_input.strip().lstrip("@").strip(); tag=hashtag_input.strip().lstrip("#").strip()
    if not username or not re.fullmatch(r"[A-Za-z0-9._]{2,24}",username): st.error("Digite um @ válido do TikTok.")
    elif not tag or not re.fullmatch(r"[\w]+",tag,flags=re.UNICODE): st.error("Digite uma hashtag válida, sem espaços.")
    elif not token_from_secrets(): st.error("Configure APIFY_TOKEN em Streamlit → Manage app → Settings → Secrets.")
    else:
        try:
            run=start_collection(token_from_secrets(),username,max_items)
            st.session_state["current_profile"]=username; st.session_state["current_tag"]=tag
            st.session_state["active_limit"]=max_items; st.session_state["active_run"]=run
            st.session_state["collection_error"]=""
            st.info("Coleta iniciada. O painel vai buscar o resultado sem manter a página presa esperando.")
        except Exception as e: st.error(f"Não foi possível iniciar a coleta: {e}")

if st.session_state.get("results") is None and st.session_state.get("active_run") is None:
    st.info("Faça uma busca para carregar os vídeos. Depois, você pode iniciar/parar o monitoramento automático.")
else:
    ctr=st.columns([2,2,4])
    with ctr[0]:
        if not st.session_state["monitoring"]:
            if st.button("▶️ Iniciar monitoramento",type="primary",use_container_width=True):
                st.session_state["monitoring"]=True; st.rerun()
        elif st.button("⏸️ Parar monitoramento",use_container_width=True):
            st.session_state["monitoring"]=False; st.rerun()
    with ctr[1]:
        if st.button("🔄 Coletar agora",use_container_width=True):
            if not st.session_state.get("current_profile"):
                st.warning("Faça uma busca primeiro.")
            else:
                try:
                    run=start_collection(token_from_secrets(),st.session_state["current_profile"],max_items)
                    st.session_state["active_run"]=run; st.session_state["active_limit"]=max_items
                    st.session_state["collection_error"]=""
                except Exception as e: st.session_state["collection_error"]=str(e)

    @st.fragment(run_every="5s")
    def dashboard():
        token=token_from_secrets()
        run=st.session_state.get("active_run")
        # Poll running actor without blocking the whole app for the full scrape.
        if run and token:
            try:
                status_data=poll_collection(token,run["id"])
                status=status_data.get("status","")
                st.session_state["active_run"].update(status=status,dataset_id=status_data.get("defaultDatasetId") or run.get("dataset_id"))
                if status in ("SUCCEEDED",):
                    raw=get_dataset(token,st.session_state["active_run"].get("dataset_id"),st.session_state.get("active_limit",500))
                    rows=parse_items(raw,st.session_state["current_profile"],st.session_state["current_tag"])
                    st.session_state["results"]=rows
                    st.session_state["raw_count"]=len(raw)
                    st.session_state["profile_avatar"]=next((avatar_url(x) for x in raw if isinstance(x,dict) and avatar_url(x)),"")
                    st.session_state["last_collection_at"]=time.time()
                    st.session_state["last_collection_label"]=datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S")
                    st.session_state["active_run"]=None
                    st.session_state["collection_error"]=""
                elif status in ("FAILED","ABORTED","TIMED-OUT"):
                    st.session_state["collection_error"]=f"A execução Apify terminou com status {status}."
                    st.session_state["active_run"]=None
            except Exception as e:
                st.session_state["collection_error"]=str(e)
        # Auto-start the next run only after the previous run finishes and cooldown elapsed.
        if st.session_state.get("monitoring") and st.session_state.get("active_run") is None and st.session_state.get("current_profile"):
            elapsed=time.time()-st.session_state.get("last_collection_at",0)
            if elapsed>=MIN_SECONDS_BETWEEN_COLLECTIONS and not st.session_state.get("collection_error"):
                try:
                    newrun=start_collection(token,st.session_state["current_profile"],st.session_state.get("active_limit",500))
                    st.session_state["active_run"]=newrun
                except Exception as e: st.session_state["collection_error"]=str(e)

        run=st.session_state.get("active_run")
        if run:
            st.info(f"Coleta Apify: {run.get('status','iniciando')}. A tela continua responsiva enquanto aguardamos.")
        if st.session_state.get("collection_error"):
            st.warning("A coleta apresentou um erro. Os dados anteriores foram preservados. Detalhe: "+st.session_state["collection_error"][:300])
        rows=st.session_state.get("results") or []
        avatar=st.session_state.get("profile_avatar","")
        p1,p2=st.columns([1,5],vertical_alignment="center")
        with p1:
            if avatar: st.image(avatar,width=96)
            else: st.markdown("### 🎬")
        with p2:
            if st.session_state.get("current_profile"):
                st.markdown(f"### @{st.session_state['current_profile']}")
                st.markdown(f"[Abrir perfil no TikTok](https://www.tiktok.com/@{st.session_state['current_profile']})")
                st.caption("Última coleta concluída: "+st.session_state.get("last_collection_label","aguardando primeira coleta"))
        stat=st.columns(3)
        with stat[0]:
            st.markdown('<span class="live-pill">● MONITORAMENTO '+("ATIVO" if st.session_state["monitoring"] else "PAUSADO")+'</span>',unsafe_allow_html=True)
        with stat[1]: st.caption("Tela verifica status a cada 5 segundos")
        with stat[2]: st.caption("Nova coleta: no máximo a cada 60 segundos")
        if rows:
            views,inter,recent,unknown,low,combined=analyze(rows,30,.5,10000)
            totals={k:sum(r[k] for r in rows) for k in ("Visualizações","Curtidas","Comentários","Compartilhamentos")}
            st.markdown('<div class="section">📊 Resumo geral</div>',unsafe_allow_html=True)
            cols=st.columns(5)
            cards=[("Vídeos",len(rows),"Correspondentes","🎬"),("Visualizações",totals["Visualizações"],"Total observado","👁️"),
                ("Curtidas",totals["Curtidas"],"Total observado","❤️"),("Comentários",totals["Comentários"],"Total observado","💬"),
                ("Compartilhamentos",totals["Compartilhamentos"],"Total observado","↗️")]
            for col,(label,val,note,emoji) in zip(cols,cards):
                with col: st.markdown(metric(label,val,note,emoji),unsafe_allow_html=True)
            with st.expander("⚙️ Filtros de sinais suspeitos",expanded=False):
                f1,f2,f3=st.columns(3)
                with f1: new_days=st.selectbox("Conta com até", [7,14,30,60,90],index=2,format_func=lambda x:f"{x} dias")
                with f2: low_pct=st.slider("Engajamento abaixo de (%)",.1,5.0,.5,.1)
                with f3: min_views=st.number_input("Mínimo de visualizações",min_value=100,max_value=1000000,value=10000,step=1000)
                views,inter,recent,unknown,low,combined=analyze(rows,new_days,low_pct,min_views)
                a,b,c,d=st.columns(4)
                a.metric("Contas recentes",len(recent)); b.metric("Engajamento baixo",len(low))
                c.metric("Sinais combinados",len(combined)); d.metric("Idade não informada",unknown)
                st.caption("Esses sinais não comprovam compra de visualizações. A idade da conta só pode ser filtrada quando a Apify a fornecer.")
                for title,subset in [("Contas recém-criadas",recent),("Views altas + poucas interações",low),("Dois ou mais sinais",combined)]:
                    st.markdown("#### "+title)
                    if subset:
                        viewdf=pd.DataFrame(subset).drop(columns=["_age_days","Foto do perfil"],errors="ignore")
                        st.dataframe(viewdf,use_container_width=True,hide_index=True,column_config={"Link":st.column_config.LinkColumn("Vídeo",display_text="Abrir no TikTok")})
                    else: st.caption("Nenhum item corresponde aos critérios com os dados disponíveis.")
            st.markdown('<div class="section">📋 Vídeos encontrados</div>',unsafe_allow_html=True)
            df=pd.DataFrame(rows).drop(columns=["_age_days","Foto do perfil"],errors="ignore")
            st.dataframe(df,use_container_width=True,hide_index=True,column_config={"Link":st.column_config.LinkColumn("Vídeo",display_text="Abrir no TikTok"),"Legenda":st.column_config.TextColumn("Legenda",width="large")})
            st.download_button("⬇️ Exportar CSV",data=df.to_csv(index=False).encode("utf-8-sig"),file_name="tiktok_tag_counter.csv",mime="text/csv")
        elif not run:
            st.info("Ainda não há resultados carregados. Faça uma busca para iniciar.")
        if st.session_state["monitoring"]:
            st.caption("Deixe esta página aberta para monitorar. Se a coleta demorar, o app acompanha o status em vez de esperar a resposta completa.")
    dashboard()

st.divider()
st.caption("O painel verifica o status a cada 5 s; a Apify recebe uma nova coleta a cada 60 s no máximo, e a coleta pode levar mais tempo. O código usa execução assíncrona da Apify para manter a interface mais responsiva. O esquema de entrada do Actor foi herdado do app anterior e precisa ser confirmado se a Apify retornar erro.")

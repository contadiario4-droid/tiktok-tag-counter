# TikTok Tag Counter

Painel web Streamlit que coleta vídeos públicos do perfil `@cortesbatalhasdosfamosos`, filtra a hashtag exata `#Casalcheck2Clips5K`, remove IDs duplicados, soma visualizações/curtidas/comentários/compartilhamentos e exporta CSV.

## Executar localmente

1. Instale Python 3.10 ou superior.
2. Abra um terminal nesta pasta.
3. Instale dependências:

   ```bash
   pip install -r requirements.txt
   ```

4. Inicie:

   ```bash
   streamlit run app.py
   ```

5. Crie uma conta no Apify, gere um API token e informe-o no campo protegido da barra lateral.

## Publicar na web

1. Envie `app.py` e `requirements.txt` para um repositório privado ou público no GitHub.
2. Crie um app em https://share.streamlit.io/ e selecione esse repositório e `app.py`.
3. O usuário informa o token do Apify na interface. Para um uso pessoal, é mais seguro guardar o token em Secrets do Streamlit e ler via `st.secrets`, em vez de expor o campo de token a todos os visitantes.

## Limites importantes

- Usa o Actor `poidata/tiktok-scraper` no Apify; o serviço e a coleta podem ter custos, limites e alterações de schema.
- O limite selecionado é um teto de coleta, não garantia de capturar todos os vídeos do perfil.
- Só filtra as publicações que o coletor devolveu. Vídeos removidos, privados, restritos, não indexados ou que não puderam ser carregados podem ficar de fora.
- A hashtag é verificada nas hashtags estruturadas e no texto da legenda. Não identifica hashtags que apareçam apenas dentro do vídeo ou em comentários.
- A autenticação oficial do TikTok tem requisitos de autorização; não é usada diretamente por este protótipo.

"""
5_post.py
Posta o vídeo final no TikTok via Content Posting API.
Usa caption e hashtags gerados pelo LLM no roteiro.

Documentação oficial:
https://developers.tiktok.com/doc/content-posting-api-get-started
"""

import os
import json
import logging
import time
import requests
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR     = Path(__file__).parent.parent / "data"
ROTEIRO_FILE = DATA_DIR / "roteiro_atual.json"
LOG_FILE     = DATA_DIR / "historico_posts.json"

TIKTOK_API_BASE = "https://open.tiktokapis.com/v2"

MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 10


# ─── Utilitários ─────────────────────────────────────────────────────────────

def com_retry(nome: str, func, *args, **kwargs):
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            log.info(f"[{nome}] Tentativa {tentativa}/{MAX_TENTATIVAS}")
            resultado = func(*args, **kwargs)
            log.info(f"[{nome}] Sucesso na tentativa {tentativa}")
            return resultado
        except Exception as e:
            log.warning(f"[{nome}] Tentativa {tentativa} falhou: {e}")
            if tentativa < MAX_TENTATIVAS:
                log.info(f"[{nome}] Aguardando {ESPERA_ENTRE_TENTATIVAS}s...")
                time.sleep(ESPERA_ENTRE_TENTATIVAS)
            else:
                raise


def montar_caption(roteiro: dict) -> str:
    """
    Monta a caption final: texto + hashtags.
    TikTok aceita até 2.200 chars, mas o ideal é 150 + hashtags.
    """
    caption = roteiro.get("caption_post", "")
    hashtags = roteiro.get("hashtags", [])

    # Hashtags obrigatórias do nicho
    hashtags_base = [
        "#direitodoconsumidor",
        "#cdcbrasil",
        "#direitosdobrasil",
        "#procon",
        "#consumidor",
    ]

    # Junta sem duplicatas, mantendo as do LLM primeiro
    todas = list(dict.fromkeys(hashtags + hashtags_base))

    hashtags_str = " ".join(todas[:10])  # TikTok recomenda até 10 hashtags
    caption_final = f"{caption}\n\n{hashtags_str}"

    # Garante o limite de 2.200 chars
    return caption_final[:2200]


# ─── TikTok Content Posting API ──────────────────────────────────────────────

def iniciar_upload(access_token: str, tamanho_bytes: int) -> dict:
    """
    Passo 1: inicializa o upload e obtém a URL de envio do vídeo.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
        "post_info": {
            "title": "",          # será preenchido depois
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": tamanho_bytes,
            "chunk_size": tamanho_bytes,   # upload em um único chunk
            "total_chunk_count": 1,
        },
    }
    resp = requests.post(
        f"{TIKTOK_API_BASE}/post/publish/video/init/",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("error", {}).get("code") != "ok":
        raise RuntimeError(f"Erro ao iniciar upload: {data}")

    return data["data"]


def enviar_video(upload_url: str, video_path: Path) -> None:
    """
    Passo 2: envia o arquivo de vídeo para a URL de upload.
    """
    tamanho = video_path.stat().st_size
    with open(video_path, "rb") as f:
        headers = {
            "Content-Type": "video/mp4",
            "Content-Range": f"bytes 0-{tamanho - 1}/{tamanho}",
            "Content-Length": str(tamanho),
        }
        resp = requests.put(
            upload_url,
            headers=headers,
            data=f,
            timeout=120,
        )
    resp.raise_for_status()
    log.info(f"Vídeo enviado: status {resp.status_code}")


def publicar_post(access_token: str, publish_id: str, caption: str) -> dict:
    """
    Passo 3: finaliza a publicação com a caption.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    payload = {
        "publish_id": publish_id,
        "post_info": {
            "title": caption,
            "privacy_level": "PUBLIC_TO_EVERYONE",
        },
    }
    resp = requests.post(
        f"{TIKTOK_API_BASE}/post/publish/status/fetch/",
        headers=headers,
        json={"publish_id": publish_id},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def postar_no_tiktok(video_path: Path, caption: str) -> str:
    """
    Fluxo completo de postagem com 3 tentativas.
    Retorna o publish_id do vídeo postado.
    """
    access_token = os.environ.get("TIKTOK_ACCESS_TOKEN")
    if not access_token:
        raise ValueError("TIKTOK_ACCESS_TOKEN não encontrado nos secrets")

    tamanho = video_path.stat().st_size
    log.info(f"Iniciando postagem: {video_path.name} ({tamanho / 1024 / 1024:.1f} MB)")

    def _fluxo_completo():
        # 1. Inicia upload
        log.info("Passo 1/3: inicializando upload...")
        dados_upload = iniciar_upload(access_token, tamanho)
        upload_url  = dados_upload["upload_url"]
        publish_id  = dados_upload["publish_id"]
        log.info(f"publish_id: {publish_id}")

        # 2. Envia o vídeo
        log.info("Passo 2/3: enviando vídeo...")
        enviar_video(upload_url, video_path)

        # 3. Aguarda processamento do TikTok (normalmente 5–15s)
        log.info("Passo 3/3: aguardando processamento (15s)...")
        time.sleep(15)

        # 4. Verifica status
        status = publicar_post(access_token, publish_id, caption)
        log.info(f"Status da publicação: {status}")

        return publish_id

    return com_retry("TikTok API", _fluxo_completo)


# ─── Histórico de posts ───────────────────────────────────────────────────────

def salvar_historico(roteiro: dict, publish_id: str):
    """
    Salva um registro do post no histórico local.
    Útil para análise de performance futura.
    """
    if LOG_FILE.exists():
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            historico = json.load(f)
    else:
        historico = []

    historico.insert(0, {
        "publish_id": publish_id,
        "tema": roteiro.get("tema"),
        "gancho": roteiro.get("gancho"),
        "caption": roteiro.get("caption_post"),
        "hashtags": roteiro.get("hashtags"),
        "llm_usado": roteiro.get("llm_usado"),
        "tts_provedor": roteiro.get("tts_provedor"),
        "duracao_segundos": roteiro.get("duracao_segundos"),
        "data_post": __import__("datetime").datetime.now().isoformat(),
    })

    # Mantém histórico dos últimos 90 posts
    historico = historico[:90]

    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(historico, f, ensure_ascii=False, indent=2)

    log.info(f"Histórico atualizado: {len(historico)} posts registrados")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Iniciando postagem no TikTok ===")

    # 1. Carrega roteiro
    if not ROTEIRO_FILE.exists():
        raise FileNotFoundError(f"Roteiro não encontrado: {ROTEIRO_FILE}")
    with open(ROTEIRO_FILE, "r", encoding="utf-8") as f:
        roteiro = json.load(f)

    # 2. Verifica vídeo
    video_path = Path(roteiro.get("video_path", DATA_DIR / "video_final.mp4"))
    if not video_path.exists():
        raise FileNotFoundError(f"Vídeo não encontrado: {video_path}")

    # 3. Monta caption
    caption = montar_caption(roteiro)
    log.info(f"Caption ({len(caption)} chars):\n{caption}")

    # 4. Posta
    publish_id = postar_no_tiktok(video_path, caption)
    log.info(f"Vídeo publicado com sucesso! publish_id: {publish_id}")

    # 5. Salva no histórico
    salvar_historico(roteiro, publish_id)

    log.info("=== Postagem concluída ===")
    print(json.dumps({
        "status": "ok",
        "publish_id": publish_id,
        "tema": roteiro.get("tema"),
        "caption_chars": len(caption),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

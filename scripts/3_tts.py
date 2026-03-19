"""
3_tts.py
Gera narração em PT-BR via cascade de TTS com 3 tentativas por provedor:
Kokoro → edge-tts → ElevenLabs → gTTS

Saída: data/audio_narrado.mp3
"""

import os
import json
import logging
import asyncio
import time
import requests
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
ROTEIRO_FILE = DATA_DIR / "roteiro_atual.json"
OUTPUT_AUDIO = DATA_DIR / "audio_narrado.mp3"

MAX_TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS = 5  # segundos


# ─── Utilitário de retry ──────────────────────────────────────────────────────

def com_retry(nome: str, func, *args, **kwargs):
    """
    Executa func até MAX_TENTATIVAS vezes antes de desistir.
    Retorna o resultado ou lança exceção na última tentativa.
    """
    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            log.info(f"[{nome}] Tentativa {tentativa}/{MAX_TENTATIVAS}")
            resultado = func(*args, **kwargs)
            log.info(f"[{nome}] Sucesso na tentativa {tentativa}")
            return resultado
        except Exception as e:
            log.warning(f"[{nome}] Tentativa {tentativa} falhou: {e}")
            if tentativa < MAX_TENTATIVAS:
                log.info(f"[{nome}] Aguardando {ESPERA_ENTRE_TENTATIVAS}s antes de tentar novamente...")
                time.sleep(ESPERA_ENTRE_TENTATIVAS)
            else:
                log.error(f"[{nome}] Todas as {MAX_TENTATIVAS} tentativas falharam.")
                raise


# ─── Nível 1: Kokoro (tts.ai) ────────────────────────────────────────────────

def _kokoro_call(texto: str) -> Path:
    api_key = os.environ.get("KOKORO_API_KEY")
    if not api_key:
        raise ValueError("KOKORO_API_KEY não encontrada")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "kokoro",
        "input": texto,
        "voice": "bf_alice",   # voz feminina, natural, PT-BR compatível
        "response_format": "mp3",
        "speed": 1.05,         # levemente mais rápido — ritmo de TikTok
    }
    resp = requests.post(
        "https://api.tts.ai/v1/audio/speech",
        headers=headers,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    OUTPUT_AUDIO.write_bytes(resp.content)
    return OUTPUT_AUDIO


def kokoro_tts(texto: str) -> Path:
    return com_retry("Kokoro", _kokoro_call, texto)


# ─── Nível 2: edge-tts (Microsoft Neural) ────────────────────────────────────

def _edge_call(texto: str) -> Path:
    import edge_tts

    async def _gerar():
        communicate = edge_tts.Communicate(
            texto,
            voice="pt-BR-FranciscaNeural",
            rate="+8%",    # levemente mais rápido
            pitch="+0Hz",
        )
        await communicate.save(str(OUTPUT_AUDIO))

    asyncio.run(_gerar())

    if not OUTPUT_AUDIO.exists() or OUTPUT_AUDIO.stat().st_size == 0:
        raise RuntimeError("edge-tts gerou arquivo vazio")
    return OUTPUT_AUDIO


def edge_tts_tts(texto: str) -> Path:
    return com_retry("edge-tts", _edge_call, texto)


# ─── Nível 3: ElevenLabs ─────────────────────────────────────────────────────

def _elevenlabs_call(texto: str) -> Path:
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY não encontrada")

    # Rachel — voz feminina clara, excelente para PT-BR
    VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": texto,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.80,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }
    resp = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
        headers=headers,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    OUTPUT_AUDIO.write_bytes(resp.content)
    return OUTPUT_AUDIO


def elevenlabs_tts(texto: str) -> Path:
    return com_retry("ElevenLabs", _elevenlabs_call, texto)


# ─── Nível 4: gTTS (Google Translate — fallback final) ───────────────────────

def _gtts_call(texto: str) -> Path:
    from gtts import gTTS

    tts = gTTS(text=texto, lang="pt", tld="com.br", slow=False)
    tts.save(str(OUTPUT_AUDIO))

    if not OUTPUT_AUDIO.exists() or OUTPUT_AUDIO.stat().st_size == 0:
        raise RuntimeError("gTTS gerou arquivo vazio")
    return OUTPUT_AUDIO


def gtts_tts(texto: str) -> Path:
    return com_retry("gTTS", _gtts_call, texto)


# ─── Cascade principal ────────────────────────────────────────────────────────

PROVIDERS = [
    ("Kokoro (tts.ai)",         kokoro_tts),
    ("edge-tts (Microsoft)",    edge_tts_tts),
    ("ElevenLabs",              elevenlabs_tts),
    ("gTTS (fallback final)",   gtts_tts),
]


def gerar_audio(texto: str) -> tuple[Path, str]:
    """
    Percorre os provedores em ordem.
    Cada um tem MAX_TENTATIVAS tentativas antes de passar para o próximo.
    Retorna (caminho_do_audio, nome_do_provedor_usado).
    """
    for nome, func in PROVIDERS:
        try:
            log.info(f"=== Iniciando provedor: {nome} ===")
            caminho = func(texto)
            log.info(f"Audio gerado com sucesso: {caminho} ({caminho.stat().st_size / 1024:.1f} KB)")
            return caminho, nome
        except Exception as e:
            log.error(f"Provedor {nome} esgotou todas as tentativas: {e}")
            log.info("Passando para o próximo provedor...")
            continue

    raise RuntimeError(
        "FALHA CRÍTICA: todos os 4 provedores TTS falharam após "
        f"{MAX_TENTATIVAS} tentativas cada."
    )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Iniciando geração de áudio ===")

    # 1. Carrega o roteiro
    if not ROTEIRO_FILE.exists():
        raise FileNotFoundError(f"Roteiro não encontrado: {ROTEIRO_FILE}")

    with open(ROTEIRO_FILE, "r", encoding="utf-8") as f:
        roteiro = json.load(f)

    texto = roteiro.get("roteiro_completo", "")
    if not texto:
        raise ValueError("Campo 'roteiro_completo' vazio no roteiro.")

    log.info(f"Texto a narrar ({len(texto)} chars):")
    log.info(texto[:200] + "..." if len(texto) > 200 else texto)

    # 2. Gera o áudio via cascade
    caminho, provedor_usado = gerar_audio(texto)

    # 3. Salva metadados para o próximo script
    roteiro["audio_path"] = str(caminho)
    roteiro["tts_provedor"] = provedor_usado
    with open(ROTEIRO_FILE, "w", encoding="utf-8") as f:
        json.dump(roteiro, f, ensure_ascii=False, indent=2)

    log.info(f"Metadados de áudio salvos em {ROTEIRO_FILE}")
    log.info(f"Provedor TTS usado: {provedor_usado}")
    log.info("=== Áudio concluído ===")

    print(json.dumps({
        "status": "ok",
        "audio": str(caminho),
        "provedor": provedor_usado,
        "tamanho_kb": round(caminho.stat().st_size / 1024, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

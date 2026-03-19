"""
4_video_assembly.py
Monta o vídeo final para TikTok:
1. Busca footage de fundo na Pexels API
2. Corta e loopa para durar o áudio inteiro
3. Adiciona overlay escuro para legibilidade
4. Queima as legendas animadas palavra por palavra
5. Adiciona marca d'água discreta do canal
6. Exporta em 1080x1920 (formato vertical TikTok)

Saída: data/video_final.mp4
"""

import os
import json
import logging
import math
import re
import subprocess
import tempfile
import time
import requests
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR   = Path(__file__).parent.parent / "data"
ROTEIRO_FILE  = DATA_DIR / "roteiro_atual.json"
AUDIO_FILE    = DATA_DIR / "audio_narrado.mp3"
VIDEO_OUTPUT  = DATA_DIR / "video_final.mp4"
TEMP_DIR      = DATA_DIR / "tmp"
TEMP_DIR.mkdir(exist_ok=True)

# Dimensões TikTok
W, H = 1080, 1920

# Fonte para legendas — usa a do sistema no Actions (DejaVu é sempre disponível)
FONT = "DejaVu-Sans-Bold"
FONT_SIZE = 72          # grande o suficiente para ler no celular
CAPTION_COLOR = "white"
CAPTION_STROKE = "black"
CAPTION_STROKE_WIDTH = 4

# Posição vertical das legendas: 60% da tela (baixo-centro)
CAPTION_Y_RATIO = 0.60

# Palavras por legenda (palavra a palavra = mais impacto)
WORDS_PER_CAPTION = 2

# Overlay escuro sobre o vídeo de fundo (melhora legibilidade)
OVERLAY_OPACITY = 0.45


# ─── Utilitários ─────────────────────────────────────────────────────────────

def rodar_ffprobe(caminho: str, campo: str) -> str:
    """Usa ffprobe para ler metadados do arquivo de mídia."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", caminho,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    for stream in data.get("streams", []):
        if campo in stream:
            return stream[campo]
    return ""


def duracao_audio(caminho: Path) -> float:
    """Retorna duração do áudio em segundos."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(caminho),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def segmentar_texto(texto: str, palavras_por_bloco: int = WORDS_PER_CAPTION) -> list[str]:
    """
    Divide o texto em blocos de N palavras para as legendas.
    Respeita pontuação: quebra antes de vírgula e ponto.
    """
    palavras = texto.split()
    blocos = []
    atual = []

    for palavra in palavras:
        atual.append(palavra)
        # Quebra no limite de palavras OU após pontuação forte
        if len(atual) >= palavras_por_bloco or palavra.endswith((".", "!", "?", ",")):
            blocos.append(" ".join(atual))
            atual = []

    if atual:
        blocos.append(" ".join(atual))

    return blocos


def distribuir_legendas(blocos: list[str], duracao_total: float) -> list[dict]:
    """
    Distribui os blocos ao longo da duração do áudio.
    Cada bloco dura proporcionalmente ao número de caracteres.
    """
    total_chars = sum(len(b) for b in blocos)
    legendas = []
    tempo_atual = 0.2  # pequeno delay inicial

    for bloco in blocos:
        proporcao = len(bloco) / total_chars
        duracao_bloco = proporcao * (duracao_total - 0.5)
        duracao_bloco = max(duracao_bloco, 0.4)  # mínimo 0.4s por bloco

        legendas.append({
            "texto": bloco,
            "inicio": round(tempo_atual, 3),
            "fim": round(tempo_atual + duracao_bloco, 3),
        })
        tempo_atual += duracao_bloco

    return legendas


# ─── Pexels: busca footage ────────────────────────────────────────────────────

PEXELS_TERMOS_POR_TEMA = {
    "default": ["brasil cidade", "escritório moderno", "pessoa celular", "contrato assinar"],
    "plano de saúde": ["hospital corredor", "médico tablet", "saúde brasil"],
    "produto defeito": ["compras loja", "consumidor mercado", "produto embalagem"],
    "cobrança": ["banco digital", "pagamento celular", "cartão crédito"],
    "entrega": ["entrega motoboy", "caixa entrega", "logística brasil"],
}


def buscar_video_pexels(tema: str) -> Path:
    """
    Busca um vídeo de fundo relevante no Pexels.
    Tenta termos relacionados ao tema, depois termos genéricos.
    """
    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise ValueError("PEXELS_API_KEY não encontrada")

    headers = {"Authorization": api_key}

    # Seleciona os termos de busca mais relevantes para o tema
    termos = PEXELS_TERMOS_POR_TEMA["default"]
    for chave, lista in PEXELS_TERMOS_POR_TEMA.items():
        if chave != "default" and chave in tema.lower():
            termos = lista + PEXELS_TERMOS_POR_TEMA["default"]
            break

    for termo in termos:
        try:
            log.info(f"Buscando footage Pexels: '{termo}'")
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                headers=headers,
                params={
                    "query": termo,
                    "orientation": "portrait",
                    "size": "large",
                    "per_page": 10,
                },
                timeout=20,
            )
            resp.raise_for_status()
            videos = resp.json().get("videos", [])

            if not videos:
                continue

            # Prefere vídeos com pelo menos 15s e sem rostos dominantes
            candidatos = [
                v for v in videos
                if v.get("duration", 0) >= 15
            ]
            if not candidatos:
                candidatos = videos

            video = candidatos[0]

            # Pega o arquivo HD (1080p se disponível, senão o maior)
            arquivos = sorted(
                video.get("video_files", []),
                key=lambda x: x.get("width", 0),
                reverse=True,
            )
            url_video = None
            for arq in arquivos:
                if arq.get("width", 0) >= 720:
                    url_video = arq["link"]
                    break

            if not url_video:
                url_video = arquivos[0]["link"]

            # Download
            destino = TEMP_DIR / f"footage_{termo.replace(' ', '_')}.mp4"
            log.info(f"Baixando: {url_video}")
            with requests.get(url_video, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(destino, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)

            log.info(f"Footage baixado: {destino} ({destino.stat().st_size / 1024 / 1024:.1f} MB)")
            return destino

        except Exception as e:
            log.warning(f"Falha no termo '{termo}': {e}")
            time.sleep(2)
            continue

    raise RuntimeError("Não foi possível baixar footage do Pexels")


# ─── Montagem com FFmpeg ──────────────────────────────────────────────────────

def preparar_fundo(footage: Path, duracao_alvo: float) -> Path:
    """
    Recorta/loopa o footage para durar exatamente duracao_alvo.
    Redimensiona para 1080x1920 (crop centralizado).
    """
    saida = TEMP_DIR / "fundo_preparado.mp4"

    # Verifica duração do footage
    dur_footage = float(rodar_ffprobe(str(footage), "duration") or 30)
    log.info(f"Footage original: {dur_footage:.1f}s → alvo: {duracao_alvo:.1f}s")

    # Se footage for mais curto que o áudio, loopa
    if dur_footage < duracao_alvo:
        loops = math.ceil(duracao_alvo / dur_footage)
        log.info(f"Footage curto, aplicando {loops} loops")
        lista_loop = TEMP_DIR / "lista_loop.txt"
        with open(lista_loop, "w") as f:
            for _ in range(loops):
                f.write(f"file '{footage.resolve()}'\n")
        footage_loopado = TEMP_DIR / "footage_loopado.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(lista_loop), "-c", "copy", str(footage_loopado),
        ], check=True, capture_output=True)
        footage = footage_loopado

    # Crop + resize para 1080x1920 + corta no tempo certo
    cmd = [
        "ffmpeg", "-y",
        "-i", str(footage),
        "-t", str(duracao_alvo + 0.5),
        "-vf", (
            f"crop=ih*{W}/{H}:ih,"      # crop para proporção 9:16
            f"scale={W}:{H},"           # escala para 1080x1920
            "setsar=1"
        ),
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-an",
        str(saida),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    log.info(f"Fundo preparado: {saida}")
    return saida


def gerar_drawtext_filtro(legendas: list[dict]) -> str:
    """
    Gera o filtro drawtext do FFmpeg para todas as legendas.
    Cada legenda aparece e desaparece no tempo certo.
    Efeito: texto branco com contorno preto espesso — padrão TikTok.
    """
    partes = []

    for leg in legendas:
        # Escapa caracteres especiais para o FFmpeg
        texto = leg["texto"]
        texto = texto.replace("'", "\\'").replace(":", "\\:").replace(",", "\\,")

        inicio = leg["inicio"]
        fim = leg["fim"]

        filtro = (
            f"drawtext="
            f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:"
            f"text='{texto}':"
            f"fontsize={FONT_SIZE}:"
            f"fontcolor={CAPTION_COLOR}:"
            f"borderw={CAPTION_STROKE_WIDTH}:"
            f"bordercolor={CAPTION_STROKE}:"
            f"x=(w-text_w)/2:"             # centralizado horizontalmente
            f"y=h*{CAPTION_Y_RATIO}:"      # posição vertical
            f"enable='between(t,{inicio},{fim})'"
        )
        partes.append(filtro)

    return ",".join(partes)


def montar_video_final(
    fundo: Path,
    audio: Path,
    legendas: list[dict],
    tema: str,
) -> Path:
    """
    Combina fundo + overlay + audio + legendas em um único ffmpeg pass.
    """
    drawtext = gerar_drawtext_filtro(legendas)

    # Marca d'água discreta no canto superior direito
    watermark = (
        f"drawtext="
        f"fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:"
        f"text='@descodificandocdc':"
        f"fontsize=28:"
        f"fontcolor=white@0.6:"
        f"borderw=1:"
        f"bordercolor=black@0.4:"
        f"x=w-text_w-30:"
        f"y=40"
    )

    # Filtro completo: overlay escuro + legendas + marca d'água
    vf = (
        f"colorchannelmixer=aa={1 - OVERLAY_OPACITY},"  # overlay escuro
        f"{drawtext},"
        f"{watermark}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(fundo),
        "-i", str(audio),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",           # qualidade um pouco melhor para o vídeo final
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",            # para quando o áudio acabar
        "-movflags", "+faststart",  # otimizado para streaming
        str(VIDEO_OUTPUT),
    ]

    log.info("Montando vídeo final com FFmpeg...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        log.error(f"FFmpeg stderr: {result.stderr[-2000:]}")
        raise RuntimeError(f"FFmpeg falhou com código {result.returncode}")

    log.info(f"Vídeo final: {VIDEO_OUTPUT} ({VIDEO_OUTPUT.stat().st_size / 1024 / 1024:.1f} MB)")
    return VIDEO_OUTPUT


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Iniciando montagem do vídeo ===")

    # 1. Carrega roteiro
    if not ROTEIRO_FILE.exists():
        raise FileNotFoundError(f"Roteiro não encontrado: {ROTEIRO_FILE}")
    with open(ROTEIRO_FILE, "r", encoding="utf-8") as f:
        roteiro = json.load(f)

    tema = roteiro.get("tema", "direito do consumidor")
    texto_narrado = roteiro.get("roteiro_completo", "")

    if not AUDIO_FILE.exists():
        raise FileNotFoundError(f"Áudio não encontrado: {AUDIO_FILE}")

    # 2. Duração do áudio
    dur = duracao_audio(AUDIO_FILE)
    log.info(f"Duração do áudio: {dur:.1f}s")

    # 3. Gera estrutura das legendas
    blocos = segmentar_texto(texto_narrado)
    legendas = distribuir_legendas(blocos, dur)
    log.info(f"Legendas geradas: {len(legendas)} blocos")

    # 4. Baixa footage do Pexels
    footage = buscar_video_pexels(tema)

    # 5. Prepara fundo (crop + resize + loop se necessário)
    fundo = preparar_fundo(footage, dur)

    # 6. Monta o vídeo final
    video = montar_video_final(fundo, AUDIO_FILE, legendas, tema)

    # 7. Salva metadados para o script de postagem
    roteiro["video_path"] = str(video)
    roteiro["duracao_segundos"] = round(dur, 1)
    roteiro["legendas_count"] = len(legendas)
    with open(ROTEIRO_FILE, "w", encoding="utf-8") as f:
        json.dump(roteiro, f, ensure_ascii=False, indent=2)

    # 8. Limpa temporários
    for arq in TEMP_DIR.glob("*"):
        try:
            arq.unlink()
        except Exception:
            pass

    log.info("=== Montagem concluída ===")
    print(json.dumps({
        "status": "ok",
        "video": str(video),
        "duracao_s": round(dur, 1),
        "tamanho_mb": round(video.stat().st_size / 1024 / 1024, 1),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()

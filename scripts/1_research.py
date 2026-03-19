"""
1_research.py
Pesquisa tendências de direito do consumidor no Brasil
e atualiza a fila de temas em data/topics_queue.json
"""

import json
import time
import random
import logging
from datetime import datetime
from pathlib import Path
from pytrends.request import TrendReq

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ─── Configuração ────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)
QUEUE_FILE = DATA_DIR / "topics_queue.json"

# Temas-semente: o que o brasileiro realmente busca
SEED_TOPICS = [
    "direito do consumidor",
    "plano de saúde negou",
    "loja não quer trocar produto",
    "cobrança indevida",
    "cancelar contrato",
    "produto com defeito",
    "entrega atrasada",
    "nota fiscal obrigatória",
    "banco cobrou taxa indevida",
    "cdc direitos",
    "procon reclamação",
    "como pedir reembolso",
    "negativação indevida",
    "golpe no pix como recuperar",
]

# Ângulos virais para cada tema — o que transforma um tema genérico em vídeo viral
ANGLE_TEMPLATES = [
    "A maioria das pessoas aceita calada, mas {tema} tem solução pelo CDC",
    "{tema}: o que a empresa não quer que você saiba",
    "Você foi lesado em {tema}? Veja exatamente o que fazer",
    "Se aconteceu {tema} com você, a empresa é obrigada a...",
    "{tema}: seus direitos em menos de 60 segundos",
    "Erro que todo brasileiro comete com {tema}",
    "Passou por {tema}? A lei está do seu lado",
]


# ─── Funções ─────────────────────────────────────────────────────────────────

def buscar_tendencias(termos: list[str]) -> dict[str, int]:
    """
    Consulta o Google Trends via pytrends.
    Retorna {termo: score} onde score é o interesse relativo (0–100).
    """
    pytrends = TrendReq(hl="pt-BR", tz=-180, timeout=(10, 25))
    scores = {}

    # pytrends aceita no máximo 5 termos por vez
    for i in range(0, len(termos), 5):
        batch = termos[i : i + 5]
        try:
            pytrends.build_payload(batch, cat=0, timeframe="now 7-d", geo="BR")
            df = pytrends.interest_over_time()
            if df.empty:
                log.warning(f"Sem dados para batch: {batch}")
                continue
            for termo in batch:
                if termo in df.columns:
                    scores[termo] = int(df[termo].mean())
            # Respeito para não ser bloqueado
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            log.error(f"Erro no batch {batch}: {e}")
            time.sleep(10)

    return scores


def buscar_termos_relacionados(termo_base: str) -> list[str]:
    """
    Busca termos em alta relacionados ao tema base.
    Isso simula o 'Content Gap' do Creator Search Insights.
    """
    pytrends = TrendReq(hl="pt-BR", tz=-180, timeout=(10, 25))
    novos_termos = []
    try:
        pytrends.build_payload([termo_base], timeframe="now 7-d", geo="BR")
        sugestoes = pytrends.related_queries()
        df_top = sugestoes.get(termo_base, {}).get("top")
        df_rising = sugestoes.get(termo_base, {}).get("rising")

        if df_rising is not None and not df_rising.empty:
            # "rising" = crescendo agora = gap de conteúdo
            novos_termos += df_rising["query"].tolist()[:5]
        if df_top is not None and not df_top.empty:
            novos_termos += df_top["query"].tolist()[:3]

        time.sleep(random.uniform(2, 4))
    except Exception as e:
        log.error(f"Erro buscando relacionados para '{termo_base}': {e}")

    return novos_termos


def selecionar_melhor_tema(scores: dict[str, int]) -> dict:
    """
    Escolhe o tema com maior score e monta o objeto completo
    com o ângulo viral mais adequado.
    """
    if not scores:
        # Fallback para um tema evergreen se trends falhar
        tema = random.choice(SEED_TOPICS)
        score = 0
        log.warning("Usando tema evergreen por fallback")
    else:
        tema = max(scores, key=scores.get)
        score = scores[tema]

    angulo = random.choice(ANGLE_TEMPLATES).replace("{tema}", tema)

    return {
        "tema": tema,
        "angulo": angulo,
        "score_tendencia": score,
        "data_pesquisa": datetime.now().isoformat(),
        "status": "pendente",
    }


def atualizar_fila(novo_tema: dict):
    """
    Adiciona o tema à fila e remove os já publicados (mantém máx. 7).
    """
    if QUEUE_FILE.exists():
        with open(QUEUE_FILE, "r", encoding="utf-8") as f:
            fila = json.load(f)
    else:
        fila = []

    # Evita duplicatas: não adiciona se o tema já está pendente
    temas_pendentes = [t["tema"] for t in fila if t["status"] == "pendente"]
    if novo_tema["tema"] not in temas_pendentes:
        fila.insert(0, novo_tema)
        log.info(f"Tema adicionado à fila: {novo_tema['tema']}")
    else:
        log.info(f"Tema já está na fila: {novo_tema['tema']}")

    # Mantém no máximo 7 temas na fila
    fila = fila[:7]

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(fila, f, ensure_ascii=False, indent=2)

    log.info(f"Fila salva em {QUEUE_FILE} ({len(fila)} temas)")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Iniciando pesquisa de tendências ===")

    # 1. Score dos temas-semente
    log.info("Buscando scores dos temas-semente...")
    scores = buscar_tendencias(SEED_TOPICS)
    log.info(f"Scores obtidos: {len(scores)} temas")

    # 2. Expandir com termos relacionados ao melhor tema atual
    if scores:
        top_tema = max(scores, key=scores.get)
        log.info(f"Buscando termos relacionados a: {top_tema}")
        relacionados = buscar_termos_relacionados(top_tema)
        if relacionados:
            log.info(f"Termos relacionados encontrados: {relacionados}")
            scores_extras = buscar_tendencias(relacionados[:5])
            scores.update(scores_extras)

    # 3. Selecionar o melhor e salvar
    melhor = selecionar_melhor_tema(scores)
    log.info(f"Tema selecionado: {melhor['tema']} (score: {melhor['score_tendencia']})")
    log.info(f"Ângulo: {melhor['angulo']}")

    atualizar_fila(melhor)
    log.info("=== Pesquisa concluída ===")

    # Retorna para o próximo script poder usar
    print(json.dumps(melhor, ensure_ascii=False))


if __name__ == "__main__":
    main()

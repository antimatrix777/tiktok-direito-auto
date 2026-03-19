"""
2_script_gen.py
Gera roteiro profissional para TikTok via cascade de LLMs:
Groq → Mistral → OpenRouter

Saída: data/roteiro_atual.json com roteiro, caption e hashtags
"""

import os
import json
import logging
import requests
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
QUEUE_FILE = DATA_DIR / "topics_queue.json"
OUTPUT_FILE = DATA_DIR / "roteiro_atual.json"

# ─── Prompt do sistema ────────────────────────────────────────────────────────
# Este é o coração do pipeline. Define voz, estrutura e qualidade dos vídeos.

SYSTEM_PROMPT = """
Você é um roteirista especialista em conteúdo viral para TikTok brasileiro.
Seu nicho é direito do consumidor — você transforma leis complexas em conteúdo
acessível, urgente e altamente compartilhável.

PERSONA DO CANAL:
- Tom: amigo que sabe direito, não advogado formal
- Linguagem: PT-BR coloquial, direto, sem juridiquês
- Postura: empoderador — "você tem direitos, use-os"
- Nunca usa: "outrossim", "doravante", "conforme supracitado"
- Sempre usa: "olha", "calma", "você sabia que", "é seu direito"

ESTRUTURA OBRIGATÓRIA DO ROTEIRO (5 blocos):
1. GANCHO (3-5 segundos): frase de impacto que ataca uma dor real.
   Exemplos de gancho bom:
   - "A loja recusou sua troca e você foi embora? Erro grave."
   - "Plano de saúde negou seu exame? Eles são OBRIGADOS a cobrir."
   - "Você pagou por isso. A empresa te deve. Ponto."
   Nunca começar com: "Hoje vou falar sobre", "Olá pessoal", "Neste vídeo"

2. PROMESSA (5 segundos): o que a pessoa vai aprender/conseguir ao assistir até o fim.
   Exemplo: "Nos próximos 40 segundos você vai saber exatamente o que fazer."

3. DESENVOLVIMENTO (20-30 segundos): 3 passos claros e acionáveis.
   Cada passo começa com verbo no imperativo: "Exija...", "Fotografe...", "Registre..."
   Mencione o artigo do CDC de forma natural: "o artigo 18 do CDC garante que..."

4. PROVA LEGAL (5 segundos): cite a lei de forma simples e poderosa.
   Exemplo: "Isso está no Código de Defesa do Consumidor, lei 8.078. É seu direito."

5. CTA (3-5 segundos): call-to-action que gera engajamento.
   Exemplos: "Salva esse vídeo antes de precisar", "Manda pra alguém que passou por isso",
   "Comenta aqui se isso já aconteceu com você"

REGRAS DE QUALIDADE:
- Duração total: 45 a 60 segundos de fala (aprox. 120-160 palavras)
- Cada frase tem no máximo 12 palavras (legendas cabem na tela)
- Use dados reais do CDC quando possível
- Urgência sem alarmismo
- Empatia real — o brasileiro JÁ sofreu com isso

FORMATO DE SAÍDA (JSON obrigatório, sem nenhum texto fora do JSON):
{
  "gancho": "texto do gancho",
  "promessa": "texto da promessa",
  "desenvolvimento": [
    "Passo 1: texto",
    "Passo 2: texto",
    "Passo 3: texto"
  ],
  "prova_legal": "texto da prova legal",
  "cta": "texto do CTA",
  "roteiro_completo": "texto corrido de tudo acima, para narração",
  "caption_post": "legenda do post no TikTok (máx 150 chars, sem hashtags)",
  "hashtags": ["#direitodoconsumidor", "#cdcbrasil", "#direitosdobrasil"],
  "duracao_estimada_segundos": 50
}
"""

USER_PROMPT_TEMPLATE = """
Crie um roteiro viral para TikTok sobre o seguinte tema:

TEMA: {tema}
ÂNGULO: {angulo}

Lembre-se: o vídeo deve fazer o brasileiro sentir que foi empoderado ao assistir.
Retorne APENAS o JSON, sem nenhum texto antes ou depois.
"""

# ─── LLM Cascade ─────────────────────────────────────────────────────────────

def chamar_groq(prompt_usuario: str) -> str:
    """Nível 1 — Groq (Llama 3.3 70B, mais rápido e capaz)"""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY não encontrada")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_usuario},
        ],
        "temperature": 0.85,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chamar_mistral(prompt_usuario: str) -> str:
    """Nível 2 — Mistral (mistral-small-latest)"""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY não encontrada")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "mistral-small-latest",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_usuario},
        ],
        "temperature": 0.85,
        "max_tokens": 1000,
        "response_format": {"type": "json_object"},
    }
    resp = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def chamar_openrouter(prompt_usuario: str) -> str:
    """Nível 3 — OpenRouter (meta-llama/llama-3.1-8b-instruct:free)"""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY não encontrada")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/tiktok-direito-auto",
    }
    payload = {
        "model": "meta-llama/llama-3.1-8b-instruct:free",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt_usuario},
        ],
        "temperature": 0.85,
        "max_tokens": 1000,
    }
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ─── Cascade principal ────────────────────────────────────────────────────────

PROVIDERS = [
    ("Groq (Llama 3.3 70B)", chamar_groq),
    ("Mistral (small-latest)", chamar_mistral),
    ("OpenRouter (Llama 3.1 8B)", chamar_openrouter),
]


def gerar_roteiro(tema: dict) -> dict:
    """
    Tenta gerar o roteiro em cascade.
    Retorna o JSON do roteiro parseado.
    """
    prompt_usuario = USER_PROMPT_TEMPLATE.format(
        tema=tema["tema"],
        angulo=tema["angulo"],
    )

    for nome, func in PROVIDERS:
        try:
            log.info(f"Tentando LLM: {nome}")
            resposta_raw = func(prompt_usuario)

            # Limpa possível markdown que alguns modelos adicionam
            resposta_limpa = resposta_raw.strip()
            if resposta_limpa.startswith("```"):
                resposta_limpa = resposta_limpa.split("```")[1]
                if resposta_limpa.startswith("json"):
                    resposta_limpa = resposta_limpa[4:]

            roteiro = json.loads(resposta_limpa)

            # Validação mínima dos campos obrigatórios
            campos = ["gancho", "promessa", "desenvolvimento",
                      "prova_legal", "cta", "roteiro_completo",
                      "caption_post", "hashtags"]
            for campo in campos:
                if campo not in roteiro:
                    raise ValueError(f"Campo obrigatório ausente: {campo}")

            log.info(f"Roteiro gerado com sucesso via {nome}")
            roteiro["llm_usado"] = nome
            return roteiro

        except Exception as e:
            log.warning(f"Falha em {nome}: {e}")
            continue

    raise RuntimeError("Todos os LLMs falharam. Verifique as API keys.")


# ─── Fila de temas ────────────────────────────────────────────────────────────

def pegar_proximo_tema() -> dict:
    """Pega o primeiro tema pendente da fila."""
    if not QUEUE_FILE.exists():
        raise FileNotFoundError(f"Fila não encontrada: {QUEUE_FILE}")

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        fila = json.load(f)

    pendentes = [t for t in fila if t["status"] == "pendente"]
    if not pendentes:
        raise ValueError("Nenhum tema pendente na fila. Rode 1_research.py primeiro.")

    return pendentes[0]


def marcar_tema_processado(tema: dict):
    """Atualiza o status do tema na fila para 'processado'."""
    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        fila = json.load(f)

    for item in fila:
        if item["tema"] == tema["tema"] and item["status"] == "pendente":
            item["status"] = "processado"
            item["data_processamento"] = datetime.now().isoformat()
            break

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(fila, f, ensure_ascii=False, indent=2)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    log.info("=== Iniciando geração de roteiro ===")

    # 1. Pega o tema da fila
    tema = pegar_proximo_tema()
    log.info(f"Tema selecionado: {tema['tema']}")
    log.info(f"Ângulo: {tema['angulo']}")

    # 2. Gera o roteiro via cascade de LLMs
    roteiro = gerar_roteiro(tema)

    # 3. Adiciona metadados úteis para os próximos scripts
    roteiro["tema"] = tema["tema"]
    roteiro["angulo"] = tema["angulo"]
    roteiro["data_geracao"] = datetime.now().isoformat()

    # 4. Salva o roteiro
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(roteiro, f, ensure_ascii=False, indent=2)

    log.info(f"Roteiro salvo em {OUTPUT_FILE}")

    # 5. Marca tema como processado na fila
    marcar_tema_processado(tema)

    # Log do resultado para visualização no Actions
    log.info("─── ROTEIRO GERADO ───")
    log.info(f"GANCHO: {roteiro['gancho']}")
    log.info(f"CTA: {roteiro['cta']}")
    log.info(f"CAPTION: {roteiro['caption_post']}")
    log.info(f"LLM usado: {roteiro['llm_usado']}")
    log.info("=== Roteiro concluído ===")

    print(json.dumps({"status": "ok", "tema": tema["tema"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

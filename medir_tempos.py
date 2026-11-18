#!/usr/bin/env python3
"""
medir_tempos.py

Programa de medição do teste de tempo de resposta do Roboldo em diferentes
redes (Metodologia, Seção 4.5.2). Uma execução = um cenário de rede (R1, R2
ou R3): o programa faz sozinho todas as chamadas da série e grava os
resultados em uma pasta própria.

O que ele mede, por chamada:
    T_LLM  tempo entre o envio do áudio ao Gemini e a chegada da resposta
    T_TTS  tempo de síntese de voz do texto falado (Edge-TTS); o áudio é
           gerado e salvo, mas não é tocado
O T_sil (2,5 s) é uma configuração fixa do programa principal e o T_ser é
medido à parte, com o robô conectado.

A chamada ao modelo reproduz a do programa principal (googleapi.py): mesmas
instruções de sistema (template.txt), mesmo áudio WAV enviado como bytes,
mesma frase fixa e a mesma extração dos códigos de comando. Cada chamada é
um pedido sem histórico, equivalente a uma sessão de conversa nova.

Instalação:
    pip install google-genai edge-tts python-dotenv numpy

Uso típico (um comando por cenário):
    python medir_tempos.py --teste --cenario R1          # 1 rodada, para conferir
    python medir_tempos.py --cenario R1                  # série completa
    python medir_tempos.py --cenario R2 --plano resultados/R1_.../plano.json
    python medir_tempos.py --retomar resultados/R2_...   # continua uma série

Outros: --simular (testa o programa sem usar a API nem a rede),
        --intervalo, --timeout, --rodadas, --modelo, --semente.

Pasta gerada (resultados/<cenario>_<data>_<hora>/):
    medicoes.csv, respostas.jsonl, plano.json, manifesto_execucao.json
"""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import platform
import random
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

# ==============================================================================
# 1. Constantes (iguais às do programa principal, quando aplicável)
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent

T_SIL_S = 2.5                                   # SILENCE_DURATION do googleapi.py
INSTRUCAO_FIXA = "Por favor, responda a este áudio mantendo o contexto da nossa conversa."
MODELO_PADRAO = "gemini-3.5-flash-lite"
VOZ_PADRAO = "pt-BR-AntonioNeural"
TTS_RATE = "+10%"
TTS_PITCH = "+15Hz"

CENARIOS = {
    "R1": "Wi-Fi da universidade",
    "R2": "Wi-Fi roteado por dados móveis (3G)",
    "R3": "Wi-Fi residencial",
}
AUDIO_IDS = ["A1", "A2", "A3"]

# Formato rigoroso: expressão (a-f) + gesto disponível para a IA + espaço + fala
FORMATO_VALIDO = re.compile(r"^[a-f][ABCDEFHIZ] \S")

CAMPOS = [
    "cenario", "ordem", "rodada", "aquecimento", "audio_id", "repeticao", "inicio",
    "t_llm_s", "t_tts_s", "t_llm_tts_s", "t_total_sem_ser_s",
    "sucesso", "etapa_erro", "categoria_erro", "codigo_http", "mensagem_erro", "tempo_ate_erro_s",
    "tokens_entrada", "tokens_saida", "tokens_raciocinio", "tokens_total",
    "resposta_chars", "texto_falado_chars", "codigos_parser", "fallback_parser",
    "formato_valido", "tts_bytes",
]

ERROS_FATAIS_HTTP = (400, 401, 403, 404)


# ==============================================================================
# 2. Estruturas e utilidades
# ==============================================================================
@dataclass
class ResultadoLLM:
    texto: str
    tokens: dict = field(default_factory=dict)
    motivo_vazio: str = ""


class ErroSimulado(Exception):
    """Erro fictício usado apenas no modo --simular."""
    def __init__(self, code, status, message):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message


def agora_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_bytes(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho: Path) -> str:
    return sha256_bytes(Path(caminho).read_bytes())


def arredondar(valor, casas=4):
    return round(valor, casas) if isinstance(valor, float) else valor


def numero_ou_none(texto):
    texto = (texto or "").strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def extrair_comandos_e_texto(resposta: str):
    """
    Cópia fiel de extrair_comandos_e_texto() de googleapi.py, com um indicador
    a mais: True quando o programa principal cairia no padrão de segurança.
    """
    resposta_limpa = resposta.strip()
    partes = resposta_limpa.split(' ', 1)

    if len(partes) > 0 and len(partes[0]) >= 2 and partes[0][0].isalpha() and partes[0][1].isalpha():
        emocao = partes[0][0]
        acao = partes[0][1]
        texto = partes[1].strip() if len(partes) > 1 else ""
        return emocao, acao, texto, False

    return 'd', 'Z', resposta_limpa, True


def classificar_erro(exc: Exception, etapa: str):
    """Devolve (categoria, código HTTP) para o erro ocorrido na etapa."""
    codigo = getattr(exc, "code", None)
    status = str(getattr(exc, "status", "") or "")
    nome = type(exc).__name__

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or "Timeout" in nome:
        return "tempo_esgotado", codigo
    if etapa == "tts":
        return "falha_na_sintese", codigo
    if isinstance(codigo, int):
        if codigo == 429 or status == "RESOURCE_EXHAUSTED":
            return "limite_de_uso", codigo
        if codigo in (500, 502, 503, 504) or status in ("UNAVAILABLE", "INTERNAL", "DEADLINE_EXCEEDED"):
            return "servidor_congestionado", codigo
        if 400 <= codigo < 500:
            return "erro_de_requisicao", codigo
    if isinstance(exc, (ConnectionError, OSError)) or any(
            t in nome for t in ("Connect", "Network", "Read", "Remote", "Protocol")):
        return "falha_de_conexao", codigo
    return "erro_desconhecido", codigo


# ==============================================================================
# 3. Verificações iniciais, plano de chamadas e manifesto
# ==============================================================================
def verificar_audios(pasta_audios: Path) -> dict:
    """Confere os áudios gravados contra o manifesto da gravação (SHA-256)."""
    caminho_man = pasta_audios / "manifesto.json"
    if not caminho_man.exists():
        sys.exit(f"[Erro] {caminho_man} não encontrado. Rode antes o gravar_audios.py.")
    manifesto = json.loads(caminho_man.read_text(encoding="utf-8"))

    audios = {}
    for aid in AUDIO_IDS:
        info = manifesto.get("audios", {}).get(aid)
        if not info:
            sys.exit(f"[Erro] O áudio {aid} não está no manifesto da gravação.")
        caminho = pasta_audios / info["arquivo"]
        if not caminho.exists():
            sys.exit(f"[Erro] Arquivo não encontrado: {caminho}")
        dados = caminho.read_bytes()
        if sha256_bytes(dados) != info["sha256"]:
            sys.exit(f"[Erro] O arquivo {caminho.name} foi alterado desde a gravação "
                     f"(SHA-256 diferente do manifesto).")
        audios[aid] = {
            "arquivo": info["arquivo"],
            "bytes": dados,
            "sha256": info["sha256"],
            "tamanho_bytes": len(dados),
            "fala_s": info.get("fala_s"),
            "arquivo_s": info.get("arquivo_s"),
        }
    return audios


def gerar_plano(rodadas: int, semente: int) -> list:
    """
    Plano: 1 chamada de aquecimento (ordem 0, descartada) + N rodadas, cada uma
    com os três áudios em ordem sorteada.
    """
    rng = random.Random(semente)
    plano = [{"ordem": 0, "rodada": 0, "audio_id": "A1", "repeticao": 0, "aquecimento": True}]
    contagem = {a: 0 for a in AUDIO_IDS}
    ordem = 0
    for rodada in range(1, rodadas + 1):
        ids = AUDIO_IDS[:]
        rng.shuffle(ids)
        for aid in ids:
            ordem += 1
            contagem[aid] += 1
            plano.append({"ordem": ordem, "rodada": rodada, "audio_id": aid,
                          "repeticao": contagem[aid], "aquecimento": False})
    return plano


def ler_csv(caminho: Path) -> list:
    if not caminho.exists():
        return []
    with open(caminho, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def anexar_csv(caminho: Path, linha: dict) -> None:
    novo = not caminho.exists()
    with open(caminho, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS)
        if novo:
            w.writeheader()
        w.writerow({c: arredondar(linha.get(c, "")) for c in CAMPOS})
        f.flush()


def anexar_jsonl(caminho: Path, registro: dict) -> None:
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
        f.flush()


def estatisticas(valores: list):
    if not valores:
        return None
    a = np.array(valores, dtype=float)
    q1, mediana, q3, p90 = np.percentile(a, [25, 50, 75, 90])
    return {
        "n": int(a.size),
        "mediana": round(float(mediana), 3),
        "q1": round(float(q1), 3),
        "q3": round(float(q3), 3),
        "iqr": round(float(q3 - q1), 3),
        "media": round(float(a.mean()), 3),
        "dp": round(float(a.std(ddof=1)), 3) if a.size > 1 else 0.0,
        "min": round(float(a.min()), 3),
        "max": round(float(a.max()), 3),
        "p90": round(float(p90), 3),
    }


def resumir(linhas: list) -> dict:
    """Resumo das chamadas medidas (sem o aquecimento)."""
    medidas = [l for l in linhas if str(l.get("aquecimento")) != "1"]
    sucessos = [l for l in medidas if str(l.get("sucesso")) == "1"]
    falhas = [l for l in medidas if str(l.get("sucesso")) != "1"]

    por_categoria = {}
    for l in falhas:
        chave = f"{l.get('etapa_erro')}:{l.get('categoria_erro')}"
        por_categoria[chave] = por_categoria.get(chave, 0) + 1

    def serie(grupo, campo):
        valores = []
        for l in grupo:
            v = numero_ou_none(str(l.get(campo, "")))
            if v is not None:
                valores.append(v)
        return estatisticas(valores)

    metricas = ["t_llm_s", "t_tts_s", "t_llm_tts_s", "t_total_sem_ser_s"]
    resumo = {
        "chamadas_medidas": len(medidas),
        "sucessos": len(sucessos),
        "falhas": len(falhas),
        "falhas_por_categoria": por_categoria,
        "formato_valido": sum(1 for l in sucessos if str(l.get("formato_valido")) == "1"),
        "fallback_do_parser": sum(1 for l in sucessos if str(l.get("fallback_parser")) == "1"),
        "geral": {m: serie(sucessos, m) for m in metricas},
        "por_audio": {},
    }
    for aid in AUDIO_IDS:
        grupo = [l for l in sucessos if l.get("audio_id") == aid]
        resumo["por_audio"][aid] = {"sucessos": len(grupo),
                                    **{m: serie(grupo, m) for m in metricas}}
    return resumo


def versao_pacote(nome: str) -> str:
    try:
        from importlib.metadata import version
        return version(nome)
    except Exception:
        return "desconhecida"


def escrever_manifesto(ctx, status: str, fim: str = "") -> None:
    linhas = ler_csv(ctx.pasta / "medicoes.csv")
    manifesto = {
        "cenario": ctx.cenario,
        "descricao_cenario": CENARIOS.get(ctx.cenario, ""),
        "modo_teste": ctx.teste,
        "modo_simulacao": ctx.simular,
        "status": status,
        "inicio": ctx.inicio_iso,
        "fim": fim,
        "retomadas": ctx.retomadas,
        "observacao": ctx.observacao,
        "fast_com": ctx.fast,
        "modelo": ctx.modelo,
        "parametros": {
            "rodadas": ctx.rodadas,
            "audios_por_rodada": len(AUDIO_IDS),
            "semente": ctx.semente,
            "intervalo_s": ctx.intervalo,
            "timeout_s": ctx.timeout,
            "pausa_apos_falhas_seguidas": ctx.pausa_falhas,
            "t_sil_s": T_SIL_S,
            "instrucao_fixa": INSTRUCAO_FIXA,
            "voz_tts": ctx.voz,
            "tts_rate": TTS_RATE,
            "tts_pitch": TTS_PITCH,
            "sessao": "nova a cada chamada (sem histórico)",
            "tentativas_apos_erro": 0,
        },
        "template_txt_sha256": ctx.template_sha256,
        "audios": {aid: {k: v for k, v in info.items() if k != "bytes"}
                   for aid, info in ctx.audios.items()},
        "ambiente": {
            "python": sys.version.split()[0],
            "sistema": platform.platform(),
            "google_genai": versao_pacote("google-genai"),
            "edge_tts": versao_pacote("edge-tts"),
            "numpy": np.__version__,
        },
        "resumo": resumir(linhas),
    }
    (ctx.pasta / "manifesto_execucao.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")


# ==============================================================================
# 4. Backends: chamada real (Gemini + Edge-TTS) e simulada
# ==============================================================================
def descrever_resposta_vazia(resp) -> str:
    partes = []
    try:
        pf = getattr(resp, "prompt_feedback", None)
        if pf is not None and getattr(pf, "block_reason", None):
            partes.append(f"bloqueio do pedido: {pf.block_reason}")
        candidatos = getattr(resp, "candidates", None) or []
        if candidatos and getattr(candidatos[0], "finish_reason", None):
            partes.append(f"finish_reason: {candidatos[0].finish_reason}")
    except Exception:
        pass
    return "; ".join(partes) or "resposta sem texto"


def criar_backend_real(modelo: str, instrucao_sistema: str, voz: str):
    from google import genai
    from google.genai import types
    import edge_tts

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        sys.exit("[Erro] GOOGLE_API_KEY não encontrada (arquivo .env ou variável de ambiente).")

    client = genai.Client(api_key=api_key)
    config = types.GenerateContentConfig(system_instruction=instrucao_sistema)

    async def llm(audio_bytes: bytes) -> ResultadoLLM:
        conteudo = types.Content(role="user", parts=[
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            types.Part(text=INSTRUCAO_FIXA),
        ])
        resp = await client.aio.models.generate_content(
            model=modelo, contents=[conteudo], config=config)
        try:
            texto = (resp.text or "").strip()
        except Exception:
            texto = ""
        um = getattr(resp, "usage_metadata", None)
        tokens = {
            "entrada": getattr(um, "prompt_token_count", None),
            "saida": getattr(um, "candidates_token_count", None),
            "raciocinio": getattr(um, "thoughts_token_count", None),
            "total": getattr(um, "total_token_count", None),
        }
        return ResultadoLLM(texto, tokens, "" if texto else descrever_resposta_vazia(resp))

    async def tts(texto: str, caminho: Path) -> int:
        comunicador = edge_tts.Communicate(texto, voz, rate=TTS_RATE, pitch=TTS_PITCH)
        await comunicador.save(str(caminho))
        return Path(caminho).stat().st_size

    async def fechar():
        try:
            await client.aio.aclose()
        except Exception:
            pass

    return llm, tts, fechar


def criar_backend_simulado(semente: int):
    """Backend fictício: permite testar o programa sem API, rede ou chave."""
    rng = random.Random(semente + 1)

    async def llm(audio_bytes: bytes) -> ResultadoLLM:
        await asyncio.sleep(rng.uniform(0.02, 0.10))
        s = rng.random()
        if s < 0.05:
            raise ErroSimulado(503, "UNAVAILABLE", "The model is overloaded. Please try again later.")
        if s < 0.08:
            raise ErroSimulado(429, "RESOURCE_EXHAUSTED", "Quota exceeded.")
        if s < 0.10:
            await asyncio.sleep(30)  # estoura o tempo limite
        if s < 0.12:
            return ResultadoLLM("", {}, "bloqueio do pedido: SAFETY")
        texto = rng.choice(["aA Oi! Tudo bem, e com você?", "cF Que legal! Veja esses passos!",
                            "Olá! Resposta sem os códigos.", "eZ Sabe por que o livro ficou triste? Muitos problemas!"])
        tokens = {"entrada": 1200 + len(audio_bytes) // 200, "saida": len(texto) // 3,
                  "raciocinio": 0, "total": 1300}
        return ResultadoLLM(texto, tokens)

    async def tts(texto: str, caminho: Path) -> int:
        await asyncio.sleep(rng.uniform(0.01, 0.05))
        if rng.random() < 0.03:
            raise RuntimeError("NoAudioReceived (simulado)")
        Path(caminho).write_bytes(b"\0" * (len(texto) * 900))
        return Path(caminho).stat().st_size

    async def fechar():
        pass

    return llm, tts, fechar


# ==============================================================================
# 5. Uma chamada e o laço da série
# ==============================================================================
def registrar_erro(linha: dict, exc: Exception, etapa: str, decorrido: float) -> None:
    categoria, codigo = classificar_erro(exc, etapa)
    mensagem = " ".join(str(exc).split())[:300] or type(exc).__name__
    linha.update(sucesso=0, etapa_erro=etapa, categoria_erro=categoria,
                 codigo_http=codigo if codigo is not None else "",
                 mensagem_erro=f"{type(exc).__name__}: {mensagem}",
                 tempo_ate_erro_s=decorrido)


async def executar_chamada(ctx, item: dict):
    """Executa uma chamada (modelo + síntese) e devolve (linha, registro_da_resposta)."""
    audio = ctx.audios[item["audio_id"]]
    linha = {c: "" for c in CAMPOS}
    linha.update(cenario=ctx.cenario, ordem=item["ordem"], rodada=item["rodada"],
                 aquecimento=int(item["aquecimento"]), audio_id=item["audio_id"],
                 repeticao=item["repeticao"], inicio=agora_iso(), sucesso=0)
    registro = None

    inicio_chamada = time.perf_counter()

    # --- Etapa 1: modelo de IA ---
    try:
        t0 = time.perf_counter()
        res = await asyncio.wait_for(ctx.llm(audio["bytes"]), timeout=ctx.timeout)
        t_llm = time.perf_counter() - t0
    except Exception as e:
        registrar_erro(linha, e, "llm", time.perf_counter() - inicio_chamada)
        return linha, None

    linha.update(t_llm_s=t_llm,
                 tokens_entrada=res.tokens.get("entrada") if res.tokens else "",
                 tokens_saida=res.tokens.get("saida") if res.tokens else "",
                 tokens_raciocinio=res.tokens.get("raciocinio") if res.tokens else "",
                 tokens_total=res.tokens.get("total") if res.tokens else "")
    for k in ("tokens_entrada", "tokens_saida", "tokens_raciocinio", "tokens_total"):
        if linha[k] is None:
            linha[k] = ""

    if not res.texto.strip():
        registrar_erro(linha, RuntimeError(res.motivo_vazio or "resposta sem texto"),
                       "llm", time.perf_counter() - inicio_chamada)
        linha["categoria_erro"] = "resposta_vazia"
        linha["codigo_http"] = ""
        return linha, None

    emocao, acao, texto, fallback = extrair_comandos_e_texto(res.texto)
    linha.update(resposta_chars=len(res.texto), texto_falado_chars=len(texto),
                 codigos_parser=f"{emocao}{acao}", fallback_parser=int(fallback),
                 formato_valido=int(bool(FORMATO_VALIDO.match(res.texto.strip()))))
    registro = {"ordem": item["ordem"], "audio_id": item["audio_id"],
                "aquecimento": item["aquecimento"], "resposta": res.texto, "texto_falado": texto}

    if not texto.strip():
        registrar_erro(linha, RuntimeError("sem texto falado após separar os comandos"),
                       "llm", time.perf_counter() - inicio_chamada)
        linha["categoria_erro"] = "resposta_vazia"
        linha["codigo_http"] = ""
        return linha, registro

    # --- Etapa 2: síntese de voz (gerada e salva, sem tocar) ---
    try:
        t1 = time.perf_counter()
        tts_bytes = await asyncio.wait_for(ctx.tts(texto, ctx.arquivo_tts), timeout=ctx.timeout)
        t_tts = time.perf_counter() - t1
    except Exception as e:
        registrar_erro(linha, e, "tts", time.perf_counter() - inicio_chamada)
        return linha, registro

    linha.update(t_tts_s=t_tts, t_llm_tts_s=t_llm + t_tts,
                 t_total_sem_ser_s=T_SIL_S + t_llm + t_tts,
                 tts_bytes=tts_bytes, sucesso=1)
    return linha, registro


def descrever_linha(linha: dict) -> str:
    if str(linha["sucesso"]) == "1":
        fmt = "formato ok" if str(linha["formato_valido"]) == "1" else "FORMATO INVÁLIDO"
        return (f"LLM {float(linha['t_llm_s']):.2f} s | TTS {float(linha['t_tts_s']):.2f} s | "
                f"{linha['codigos_parser']} | {fmt}")
    http = f" [{linha['codigo_http']}]" if linha["codigo_http"] != "" else ""
    return f"FALHA ({linha['etapa_erro']}): {linha['categoria_erro']}{http}"


def fmt_minutos(segundos: float) -> str:
    return f"{int(segundos // 60)} min {int(segundos % 60):02d} s"


async def executar(ctx) -> None:
    csv_path = ctx.pasta / "medicoes.csv"
    jsonl_path = ctx.pasta / "respostas.jsonl"

    pendentes = [i for i in ctx.plano if i["ordem"] not in ctx.feitas]
    ja_feitas = len(ctx.feitas)
    total = len(ctx.plano)
    falhas_seguidas = 0
    inicio_serie = time.perf_counter()
    status = "interrompida"

    try:
        for n, item in enumerate(pendentes):
            posicao = ja_feitas + n + 1
            rotulo = "aquecimento" if item["aquecimento"] else f"rodada {item['rodada']}"
            print(f"[{posicao}/{total}] {item['audio_id']} ({rotulo}) ... ", end="", flush=True)

            linha, registro = await executar_chamada(ctx, item)
            anexar_csv(csv_path, linha)
            if registro:
                anexar_jsonl(jsonl_path, registro)
            ctx.feitas.add(item["ordem"])
            print(descrever_linha(linha))

            falhou = str(linha["sucesso"]) != "1"
            falhas_seguidas = falhas_seguidas + 1 if falhou else 0

            if (falhou and linha["categoria_erro"] == "erro_de_requisicao"
                    and str(linha["codigo_http"]).isdigit()
                    and int(linha["codigo_http"]) in ERROS_FATAIS_HTTP):
                print("\n[Erro] Erro de requisição (chave, modelo ou permissão). "
                      "Continuar não adianta; corrija e retome a série.")
                print(f"Mensagem: {linha['mensagem_erro']}")
                status = "abortada_erro_de_requisicao"
                break

            if ctx.pausa_falhas and falhas_seguidas >= ctx.pausa_falhas:
                print(f"\n[Atenção] {falhas_seguidas} falhas seguidas.")
                resp = await asyncio.to_thread(input, "Continuar a série? [S/n] ")
                if resp.strip().lower() == "n":
                    status = "pausada_pelo_usuario"
                    break
                falhas_seguidas = 0

            restantes = len(pendentes) - n - 1
            if restantes > 0:
                decorrido = time.perf_counter() - inicio_serie
                media_ciclo = (decorrido + ctx.intervalo) / (n + 1)
                print(f"      tempo restante estimado: {fmt_minutos(media_ciclo * restantes)}")
                await asyncio.sleep(ctx.intervalo)
        else:
            status = "concluida"
    finally:
        try:
            ctx.arquivo_tts.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            await ctx.fechar()
        except Exception:
            pass
        escrever_manifesto(ctx, status, agora_iso())
        ctx.status_final = status


# ==============================================================================
# 6. Preparação (perguntas, pastas) e programa principal
# ==============================================================================
def impedir_suspensao() -> str:
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
            return "suspensão do Windows bloqueada durante a execução."
        if sys.platform == "darwin":
            subprocess.Popen(["caffeinate", "-i", "-w", str(os.getpid())])
            return "suspensão do macOS bloqueada durante a execução (caffeinate)."
    except Exception:
        pass
    return ("desative a suspensão do computador ou rode com "
            "'systemd-inhibit --what=idle:sleep python3 medir_tempos.py ...'.")


def perguntar_fast(args) -> dict:
    print("\nCaracterização da rede (Fast.com). Pode deixar em branco e preencher depois "
          "no manifesto_execucao.json.")
    campos = [("download_mbps", "Download (Mbps)"), ("upload_mbps", "Upload (Mbps)"),
              ("latencia_ms", "Latência (ms)"), ("latencia_carga_ms", "Latência sob carga (ms)")]
    dados = {}
    for chave, nome in campos:
        dados[chave] = numero_ou_none(input(f"  {nome}: "))
    return dados


def main():
    p = argparse.ArgumentParser(description="Mede o tempo de resposta do Roboldo em um cenário de rede.")
    p.add_argument("--cenario", choices=list(CENARIOS), help="cenário de rede (R1, R2 ou R3)")
    p.add_argument("--retomar", metavar="PASTA", help="continua uma série interrompida")
    p.add_argument("--teste", action="store_true", help="execução curta de 1 rodada, para conferir o programa")
    p.add_argument("--simular", action="store_true", help="não usa API nem rede (testa só o programa)")
    p.add_argument("--rodadas", type=int, default=20, help="rodadas por série (padrão: 20)")
    p.add_argument("--intervalo", type=float, default=10.0, help="segundos entre as chamadas (padrão: 10)")
    p.add_argument("--timeout", type=float, default=60.0, help="tempo limite por etapa, em s (padrão: 60)")
    p.add_argument("--semente", type=int, default=2026, help="semente do sorteio dos áudios (padrão: 2026)")
    p.add_argument("--plano", metavar="ARQUIVO", help="reutiliza o plano.json de outra série")
    p.add_argument("--modelo", help=f"modelo do Gemini (padrão: GEMINI_MODEL ou {MODELO_PADRAO})")
    p.add_argument("--audios", default="audios_teste", help="pasta dos áudios (padrão: audios_teste)")
    p.add_argument("--template", default=str(BASE_DIR / "template.txt"), help="caminho do template.txt")
    p.add_argument("--saida", default="resultados", help="pasta de resultados (padrão: resultados)")
    p.add_argument("--pausa-apos-falhas", type=int, default=5,
                   help="pergunta se continua após N falhas seguidas; 0 desliga (padrão: 5)")
    p.add_argument("--sem-perguntas", action="store_true", help="não pede confirmações nem valores do Fast.com")
    args = p.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv(BASE_DIR / ".env")
    except ImportError:
        print("[Aviso] python-dotenv não instalado; usando só as variáveis de ambiente.")

    retomando = args.retomar is not None
    if not retomando and not args.cenario:
        p.error("informe --cenario (R1, R2 ou R3) ou --retomar PASTA")

    ctx = SimpleNamespace(retomadas=[], observacao="", fast={}, status_final="")

    # --- Configuração: nova série ou retomada ---
    if retomando:
        pasta = Path(args.retomar)
        man_antigo = json.loads((pasta / "manifesto_execucao.json").read_text(encoding="utf-8"))
        par = man_antigo["parametros"]
        ctx.cenario = man_antigo["cenario"]
        ctx.teste = man_antigo.get("modo_teste", False)
        ctx.simular = args.simular or man_antigo.get("modo_simulacao", False)
        ctx.modelo = man_antigo["modelo"]
        ctx.rodadas, ctx.semente = par["rodadas"], par["semente"]
        ctx.intervalo, ctx.timeout = par["intervalo_s"], par["timeout_s"]
        ctx.voz = par["voz_tts"]
        ctx.inicio_iso = man_antigo["inicio"]
        ctx.retomadas = man_antigo.get("retomadas", []) + [agora_iso()]
        ctx.observacao = man_antigo.get("observacao", "")
        ctx.fast = man_antigo.get("fast_com", {})
        plano = json.loads((pasta / "plano.json").read_text(encoding="utf-8"))["sequencia"]
    else:
        ctx.cenario = args.cenario
        ctx.teste = args.teste
        ctx.simular = args.simular
        ctx.modelo = args.modelo or os.getenv("GEMINI_MODEL", MODELO_PADRAO)
        ctx.rodadas = 1 if args.teste else args.rodadas
        ctx.semente = args.semente
        ctx.intervalo, ctx.timeout = args.intervalo, args.timeout
        ctx.voz = os.getenv("TTS_VOICE", VOZ_PADRAO)
        ctx.inicio_iso = agora_iso()
        if args.plano:
            plano = json.loads(Path(args.plano).read_text(encoding="utf-8"))["sequencia"]
            ctx.rodadas = max(i["rodada"] for i in plano)
        else:
            plano = gerar_plano(ctx.rodadas, ctx.semente)
        pasta = None

    ctx.pausa_falhas = args.pausa_apos_falhas
    ctx.plano = plano

    # --- Verificações ---
    ctx.audios = verificar_audios(Path(args.audios))
    template = Path(args.template)
    if not template.exists():
        sys.exit(f"[Erro] template.txt não encontrado em {template}")
    instrucao = template.read_text(encoding="utf-8")
    ctx.template_sha256 = sha256_bytes(template.read_bytes())

    medidas = sum(1 for i in plano if not i["aquecimento"])
    ciclo_estimado = ctx.intervalo + 4
    print("=" * 70)
    print(f"Teste de tempo de resposta - cenário {ctx.cenario}: {CENARIOS.get(ctx.cenario, '')}")
    print("=" * 70)
    print(f"Modelo:     {ctx.modelo}{'  (SIMULAÇÃO: nada é enviado)' if ctx.simular else ''}")
    print(f"Chamadas:   {len(plano)} ({medidas} medidas + {len(plano) - medidas} de aquecimento descartada)")
    print(f"Intervalo:  {ctx.intervalo:g} s | tempo limite: {ctx.timeout:g} s | semente: {ctx.semente}")
    print(f"Duração estimada: cerca de {fmt_minutos(ciclo_estimado * len(plano))}")
    print("Áudios conferidos com o manifesto da gravação (SHA-256 ok).")

    if not retomando:
        if not (args.sem_perguntas or ctx.simular):
            resp = input(f"\nO computador está conectado à rede do cenário {ctx.cenario} "
                         f"({CENARIOS[ctx.cenario]})? [s/N] ").strip().lower()
            if resp != "s":
                sys.exit("Conecte-se à rede correta e rode de novo.")
            if not ctx.teste:
                ctx.fast = perguntar_fast(args)
                ctx.observacao = input("Observação (local, sinal, o que quiser registrar): ").strip()
        pasta = Path(args.saida) / f"{'teste_' if ctx.teste else ''}{ctx.cenario}_{datetime.now():%Y%m%d_%H%M%S}"
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / "plano.json").write_text(
            json.dumps({"semente": ctx.semente, "rodadas": ctx.rodadas, "sequencia": plano},
                       ensure_ascii=False, indent=2), encoding="utf-8")

    ctx.pasta = pasta
    ctx.arquivo_tts = pasta / "_tts_tmp.mp3"
    ctx.feitas = {int(l["ordem"]) for l in ler_csv(pasta / "medicoes.csv")}

    if ctx.simular:
        ctx.llm, ctx.tts, ctx.fechar = criar_backend_simulado(ctx.semente)
    else:
        ctx.llm, ctx.tts, ctx.fechar = criar_backend_real(ctx.modelo, instrucao, ctx.voz)

    print(f"Pasta de resultados: {pasta}")
    print(f"Aviso: {impedir_suspensao()}")
    if ctx.feitas:
        print(f"Retomando: {len(ctx.feitas)} chamadas já feitas.")
    escrever_manifesto(ctx, "em_andamento")
    print()

    try:
        asyncio.run(executar(ctx))
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")

    # --- Resumo final ---
    linhas = ler_csv(pasta / "medicoes.csv")
    r = resumir(linhas)
    print("\n" + "=" * 70)
    print(f"Fim: {ctx.status_final or 'interrompida'} | medidas: {r['chamadas_medidas']} | "
          f"sucessos: {r['sucessos']} | falhas: {r['falhas']}")
    if r["falhas_por_categoria"]:
        print("Falhas por tipo: " + ", ".join(f"{k} ({v})" for k, v in r["falhas_por_categoria"].items()))
    print(f"Formato válido: {r['formato_valido']}/{r['sucessos']} | "
          f"padrão de segurança do parser: {r['fallback_do_parser']}")
    for nome, chave in (("T_LLM", "t_llm_s"), ("T_TTS", "t_tts_s"), ("T_LLM+T_TTS", "t_llm_tts_s")):
        e = r["geral"][chave]
        if e:
            print(f"{nome:12s} mediana {e['mediana']:.2f} s | IQR {e['q1']:.2f}-{e['q3']:.2f} s | "
                  f"min {e['min']:.2f} | max {e['max']:.2f}")
    print(f"Resultados em: {pasta}")
    if ctx.status_final != "concluida":
        print(f"Para continuar de onde parou: python medir_tempos.py --retomar \"{pasta}\"")


if __name__ == "__main__":
    main()
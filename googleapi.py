import os
import wave
import pyaudio
import numpy as np
import pygame
import threading
import time
import serial
import asyncio
import edge_tts
from pathlib import Path
from google import genai
from google.genai import types
from dotenv import load_dotenv

# ==============================================================================
# 1. Configurações e Inicialização de Caminhos
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent
TEMPLATE_PATH = BASE_DIR / "template.txt"
AUDIO_SIM = BASE_DIR / "sim.mp3"
AUDIO_THINKING = BASE_DIR / "pensando.mp3"
AUDIO_MENSAGEM = BASE_DIR / "mensagem.wav"
AUDIO_RESPOSTA = BASE_DIR / "resposta.mp3"

# Carrega variáveis de ambiente do .env
load_dotenv(BASE_DIR / ".env")

api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("\n[ERRO CRÍTICO] A variável GOOGLE_API_KEY não foi encontrada!")
    print("Por favor, crie o arquivo .env baseado no .env.example e adicione sua chave.\n")
    exit(1)

if not TEMPLATE_PATH.exists():
    print(f"\n[ERRO CRÍTICO] Arquivo de instruções '{TEMPLATE_PATH.name}' não encontrado em {BASE_DIR}!\n")
    exit(1)

with open(TEMPLATE_PATH, "r", encoding="utf-8") as arquivo:
    instrucao_sistema = arquivo.read()

# Inicialização do Gemini
MODEL_ID = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
client = genai.Client(api_key=api_key)

chat_roboldo = client.chats.create(
    model=MODEL_ID,
    config=types.GenerateContentConfig(
        system_instruction=instrucao_sistema
    )
)

# Inicializa o mixer do Pygame uma única vez para evitar estalos no áudio
try:
    pygame.mixer.init()
except Exception as e:
    print(f"Aviso: Não foi possível inicializar o dispositivo de áudio do sistema ({e}).")

# ==============================================================================
# 2. Configuração Serial (ESP32 via USB ou Bluetooth)
# ==============================================================================
SERIAL_PORT = os.getenv("SERIAL_PORT")
BAUD_RATE = int(os.getenv("BAUD_RATE"))

try:
    arduino = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
    print(f"Conectado ao ESP32 ({SERIAL_PORT} @ {BAUD_RATE} bps).")
    print("Aguardando o Roboldo iniciar o sistema...")
    time.sleep(3)
except Exception as e:
    print(f"Aviso: ESP32 não detectado em {SERIAL_PORT} ({e}). Modo simulação ativo.")
    arduino = None


def enviar_comando(comando: str):
    """Envia um caractere/comando serial para o ESP32."""
    if arduino:
        try:
            arduino.write(comando.encode())
            time.sleep(0.05)
            if arduino.in_waiting > 0:
                feedback = arduino.readline().decode('utf-8', errors='ignore').strip()
                if feedback:
                    print(f"   [ESP32] {feedback}")
                else:
                    print(f"   [ESP32] OK: '{comando}'")
        except Exception as e:
            print(f"   [Serial] Erro ao enviar comando: {e}")


# ==============================================================================
# 3. Síntese e Reprodução de Áudio
# ==============================================================================
async def text_to_speech_async(text: str, output_file: Path | str = AUDIO_RESPOSTA):
    """Converte texto em áudio MP3 usando Edge-TTS (gratuito e de alta qualidade)."""
    voice = os.getenv("TTS_VOICE", "pt-BR-AntonioNeural")
    communicate = edge_tts.Communicate(text, voice, rate="+10%", pitch="+15Hz")
    await communicate.save(str(output_file))


def text_to_speech(text: str, output_file: Path | str = AUDIO_RESPOSTA):
    """Invoca o sintetizador de voz assíncrono sincronamente."""
    asyncio.run(text_to_speech_async(text, output_file))


def play_audio(filename: Path | str):
    """Reproduz um arquivo de áudio de forma bloqueante usando Pygame."""
    filepath = Path(filename)
    if not filepath.exists():
        print(f"[Áudio] Arquivo não encontrado para reprodução: {filepath}")
        return

    if not pygame.mixer.get_init():
        print(f"[Áudio] Dispositivo de áudio indisponível. Pulando reprodução de: {filepath.name}")
        return

    try:
        pygame.mixer.music.load(str(filepath))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception as e:
        print(f"[Áudio] Erro ao reproduzir {filepath.name}: {e}")


class SomPensando(threading.Thread):
    """
    Thread responsável por tocar 'pensando.mp3' em segundo plano durante
    a requisição ao Gemini, reduzindo a percepção de latência pelo usuário.
    """
    def __init__(self, audio_file: Path | str = AUDIO_THINKING):
        super().__init__(daemon=True)
        self.audio_file = Path(audio_file)
        self._stop_event = threading.Event()

    def run(self):
        if not self.audio_file.exists() or not pygame.mixer.get_init():
            return
        try:
            pygame.mixer.music.load(str(self.audio_file))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy() and not self._stop_event.is_set():
                pygame.time.Clock().tick(10)
        except Exception as e:
            print(f"[Áudio] Erro ao reproduzir pensando.mp3: {e}")

    def parar(self):
        """Interrompe a reprodução suavemente para liberar o mixer para a fala."""
        self._stop_event.set()
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass


# ==============================================================================
# 4. Captura de Áudio do Microfone (WAV)
# ==============================================================================
def capture_audio(filename: Path | str = AUDIO_MENSAGEM) -> Path:
    """Captura áudio do microfone até detectar silêncio contínuo."""
    filepath = Path(filename)
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 44100
    CHUNK = 1024

    SILENCE_DURATION = 2.5
    PRE_CALIBRATION = 10
    MARGIN = 200

    audio = pyaudio.PyAudio()
    stream = None

    try:
        stream = audio.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)

        print("Roboldo calibrando ambiente...")
        noise_levels = []
        for _ in range(PRE_CALIBRATION):
            data = stream.read(CHUNK, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            noise_levels.append(np.abs(audio_data).mean())

        ambient_noise = sum(noise_levels) / len(noise_levels)
        silence_threshold = ambient_noise + MARGIN

        print(f"Ambiente: {int(ambient_noise)} | Limiar definido: {int(silence_threshold)}")
        print("Pode falar! (Roboldo ouvindo...)")

        frames = []
        silent_chunks = 0
        speaking_started = False
        max_chunks = int(30 * RATE / CHUNK)
        current_chunks = 0

        while current_chunks < max_chunks:
            data = stream.read(CHUNK, exception_on_overflow=False)
            frames.append(data)
            current_chunks += 1

            audio_data = np.frombuffer(data, dtype=np.int16)
            volume = np.abs(audio_data).mean()

            if volume > silence_threshold:
                silent_chunks = 0
                speaking_started = True
            else:
                if speaking_started:
                    silent_chunks += 1

            if speaking_started and silent_chunks > int(SILENCE_DURATION * RATE / CHUNK):
                print("Fim da fala detectado.")
                break

        with wave.open(str(filepath), 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(audio.get_sample_size(FORMAT))
            wf.setframerate(RATE)
            wf.writeframes(b''.join(frames))

    finally:
        if stream:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        audio.terminate()

    return filepath


# ==============================================================================
# 5. Processamento com Google Gemini
# ==============================================================================
def generate_gemini_response(audio_path: Path | str) -> str:
    """Envia o áudio gravado para o modelo multimodal Gemini e retorna o texto gerado."""
    with open(audio_path, "rb") as f:
        audio_bytes = f.read()

    response = chat_roboldo.send_message(
        [
            types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            "Por favor, responda a este áudio mantendo o contexto da nossa conversa."
        ]
    )
    return response.text.strip()


def extrair_comandos_e_texto(resposta: str) -> tuple[str, str, str]:
    """
    Extrai a emoção (1ª letra minúscula), ação (2ª letra MAIÚSCULA) e o texto falado.
    Aplica valores neutros caso o formato recebido varie.
    """
    resposta_limpa = resposta.strip()
    partes = resposta_limpa.split(' ', 1)

    if len(partes) > 0 and len(partes[0]) >= 2 and partes[0][0].isalpha() and partes[0][1].isalpha():
        emocao = partes[0][0]
        acao = partes[0][1]
        texto = partes[1].strip() if len(partes) > 1 else ""
        return emocao, acao, texto

    # Padrão de segurança: Neutro
    return 'd', 'Z', resposta_limpa


# ==============================================================================
# 6. Orquestração de Fala e Movimentos (Sem Redundâncias)
# ==============================================================================
def executar_fala_e_gestos(texto: str, emocao: str, acao: str, reset_bracos: bool = False):
    """
    Executa o ciclo completo de expressão do Roboldo:
    1. Gera áudio via TTS
    2. Atualiza a expressão facial
    3. Aciona a boca ('g')
    4. Move os braços ('acao')
    5. Reproduz a fala
    6. Silencia a boca ('h') e mantém a expressão facial
    7. (Opcional) Retorna braços para a posição neutra ('Z')
    """
    print(f"Roboldo: {texto} \n[Rosto: {emocao} | Braço: {acao}]")

    # 1. Gera áudio da fala
    text_to_speech(texto, AUDIO_RESPOSTA)

    # 2. Atualiza a expressão do rosto
    enviar_comando(emocao)

    # 3. Manda a boca começar a falar (piscar)
    enviar_comando("g")

    # 4. Manda o comando dos braços começarem a se mover
    enviar_comando(acao)

    # 5. Toca o áudio enquanto ele se mexe
    play_audio(AUDIO_RESPOSTA)

    # 6. Ao fim do áudio, silencia a boca e mantém a expressão
    enviar_comando("h")
    enviar_comando(emocao)

    # 7. Volta braços à posição inicial se solicitado
    if reset_bracos:
        enviar_comando("Z")


# ==============================================================================
# 7. Loop Principal
# ==============================================================================
def main():
    if arduino:
        arduino.reset_input_buffer()

    enviar_comando('a')  # Começa com rosto feliz
    enviar_comando('Z')  # Começa com braços parados
    print("\n--- Roboldo Ativo (UERN) ---")
    print("Pressione Ctrl+C a qualquer momento para encerrar.\n")

    while True:
        try:
            input('\nPressione ENTER para falar com o Roboldo...')

            play_audio(AUDIO_SIM)
            audio_path = capture_audio()

            print("Roboldo processando...")

            # Inicia o som 'pensando.mp3' em paralelo para não bloquear o envio do áudio
            thread_pensando = SomPensando(AUDIO_THINKING)
            thread_pensando.start()

            try:
                resposta_bruta = generate_gemini_response(audio_path)

                # Interrompe o áudio de 'pensando' assim que a resposta chega
                thread_pensando.parar()

                emocao, acao, texto_final = extrair_comandos_e_texto(resposta_bruta)
                executar_fala_e_gestos(texto_final, emocao, acao)

            except Exception as e:
                thread_pensando.parar()
                print(f"[Erro no fluxo do Gemini] {e}")

                texto_erro = (
                    "Puxa, me desculpe! Meu cérebro digital deu um pequeno curto-circuito "
                    "e está sobrecarregado agora. Você pode repetir daqui a pouquinho?"
                )
                emocao_erro = 'b'  # Rosto triste
                acao_erro = 'D'    # Mãos na cintura (Dúvida/Problema)

                try:
                    executar_fala_e_gestos(texto_erro, emocao_erro, acao_erro, reset_bracos=True)
                except Exception as falha_critica:
                    print(f"Falha crítica no hardware/áudio ao avisar do erro: {falha_critica}")

        except KeyboardInterrupt:
            print("\nEncerrando Roboldo com segurança...")
            enviar_comando('a')
            enviar_comando('Z')
            break


if __name__ == "__main__":
    main()
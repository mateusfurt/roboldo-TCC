import os
import time
import pygame
import serial

# ==========================================
# 1. Configurações Iniciais
# ==========================================
pygame.mixer.init()

PORTA_SERIAL = '/dev/ttyACM0' # No Linux, mude para '/dev/ttyUSB0' ou similar, se necessário
BAUD_RATE = 115200

try:
    arduino = serial.Serial(PORTA_SERIAL, BAUD_RATE, timeout=1) 
    print(f"Conectado ao ESP32. Aguardando 3s...")
    time.sleep(3)
except Exception as e:
    print(f"Aviso: ESP32 não detectado ({e}). Modo Simulação.")
    arduino = None

def enviar_comando(comando):
    if arduino:
        try:
            arduino.write(comando.encode())
        except Exception as e:
            print(f"   [Serial] Erro: {e}")
    else:
        print(f"   [Simulação] Comando enviado: '{comando}'")

# ==========================================
# 2. O Motor de Sincronia de Tempo (O Pulo do Gato)
# ==========================================
def tocar_e_sincronizar(arquivo_audio, eventos_tempo=None):
    if eventos_tempo is None:
        eventos_tempo = []
        
    # Cria uma cópia da lista de eventos para irmos "riscando" o que já foi feito
    eventos_pendentes = eventos_tempo.copy()

    if os.path.exists(arquivo_audio):
        pygame.mixer.music.load(arquivo_audio)
        pygame.mixer.music.play()
        
        # Enquanto a música toca, esse loop roda várias vezes por segundo
        while pygame.mixer.music.get_busy():
            # Pega o tempo atual do áudio em segundos (ex: 2.5s, 4.1s)
            tempo_atual = pygame.mixer.music.get_pos() / 1000.0
            
            # Verifica se chegou a hora de disparar algum evento pendente
            for evento in eventos_pendentes[:]: # [:] cria uma cópia rápida para iterar
                tempo_alvo, comando = evento
                
                if tempo_atual >= tempo_alvo:
                    print(f"   [Tempo {tempo_atual:.1f}s] Disparando ação no meio do áudio: '{comando}'")
                    enviar_comando(comando)
                    eventos_pendentes.remove(evento) # Remove da lista para não disparar de novo
            
            # Limita o loop a 30 verificações por segundo para não travar a CPU
            pygame.time.Clock().tick(30)
    else:
        print(f"   [Erro] Áudio não encontrado: {arquivo_audio}")

# ==========================================
# 3. A Coreografia (Com Eventos Temporais)
# ==========================================
# Formato: (Áudio, Rosto Início, Braço Início, [ (tempo_em_segundos, 'comando'), ... ])
passos_apresentacao = [
    
    # ÁUDIO 1: Sem eventos no meio do áudio, apenas a configuração inicial
    ("audios_demonstracao/01_origem.mp3", 'a', 'Z', [
        (0.0, 'A')
    ]),
    
    # ÁUDIO 2: Coreografia completa acompanhando o texto
    # Texto: "...como feliz (muda rosto), chateado (muda rosto), surpreso (muda rosto)..."
    # Texto: "...celebrar (muda braço), demonstrar sentimentos e até exibir músculos (muda braço)..."
    ("audios_demonstracao/02_funcoes.mp3", 'a', 'Z', [
        (6.5, 'a'),   # Aos 6.5s: rosto feliz
        (7.5, 'b'),   # Aos 7.5s: rosto chateado
        (8.5, 'f'),   # Aos 8.5s: rosto surpreso
        (10.0, 'cB'),  # Aos 12.0s: braços celebram
        (16.5, 'eE'),  # Aos 16.5s: exibe os músculos
    ]),
    
    # ÁUDIO 3: Falar do corpo
    ("audios_demonstracao/03_construcao.mp3", 'a', 'Z', [
        (9.0, 'aD'),
        (10.0, 'g')    # Aos 4.5s (exemplo): põe as mãos na cintura ao falar do feltro
    ]),
    
    # ÁUDIO 4: Despedida ("bateria social")
    ("audios_demonstracao/04_despedida.mp3", 'b', 'Z', [
        (7.0, 'e'),
        (7.5, 'g'),
        (25.0, 'aA')    # Aos 7.0s ("brincadeiras à parte"): volta a ficar feliz
    ])
]

# ==========================================
# 4. Loop Principal
# ==========================================
def rodar_apresentacao():
    if arduino:
        arduino.reset_input_buffer()
        
    print("\n--- INICIANDO MODO DEMONSTRAÇÃO AUTÔNOMA ---")
    enviar_comando('a')
    enviar_comando('Z')
    time.sleep(1)

    for audio, emocao_inicial, acao_inicial, eventos in passos_apresentacao:
        print(f"\n-> Reproduzindo: {os.path.basename(audio)}")
        
        # Seta as posições iniciais antes do áudio começar
        enviar_comando(emocao_inicial) 
        enviar_comando(acao_inicial)   
        enviar_comando("g") # Boca começa a falar
        
        # Toca o áudio e envia os comandos programados no tempo exato
        tocar_e_sincronizar(audio, eventos)
        
        # Ao fim do áudio, silencia a boca e faz uma pausa
        enviar_comando("h")
        time.sleep(1.0)

    print("\n--- Demonstração concluída! ---")
    enviar_comando('a')
    enviar_comando('Z')

if __name__ == "__main__":
    input("Pressione [ENTER] para começar a apresentação...")
    rodar_apresentacao()
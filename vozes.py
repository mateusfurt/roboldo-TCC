import os
import asyncio
import edge_tts

pasta_destino = "audios_demonstracao"
if not os.path.exists(pasta_destino):
    os.makedirs(pasta_destino)

# Roteiro definitivo para a demonstração
roteiro = {
    "01_origem.mp3": "Olá! Prazer em conhecer vocês, eu sou o Roboldo. Sou um robô social de baixo custo que nasceu no Laboratório de Aprendizagem Robótica do campus avançado de Natal, na Universidade do Estado do Rio Grande do Norte. A função de um robô social é ser um agente projetado para conviver e interagir diretamente com seres humanos. O objetivo principal do meu desenvolvimento é ser uma plataforma acessível e de baixo custo, viabilizando o uso de agentes robóticos em diversas pesquisas acadêmicas.",
    
    "02_funcoes.mp3": "Para interagir com vocês, eu tenho várias funções. As matrizes de LED no meu rosto conseguem fazer expressões faciais como feliz, chateado, surpreso e outras. Com os meus braços, eu consigo celebrar, demonstrar sentimentos e até mesmo exibir os meus músculos! E, para completar, por meio da inteligência artificial Azure Neural TTS, eu consigo me comunicar verbalmente com as pessoas.",
    
    "03_construcao.mp3": "E para quem tem curiosidade sobre como eu fui construído, a estrutura do meu corpo é feita com papelão reciclado. Eu sou revestido com feltro azul e preenchido com uma fibra bem fofinha, o que me dá essa aparência de bichinho de pelúcia. Já as partes que contêm os eletrônicos foram impressas em 3D, em P L A, e modeladas para comportar essas peças perfeitamente.",
    
    "04_despedida.mp3": "Eu adoraria bater um papo com vocês agora, mas os meus criadores me colocaram no modo de economia de bateria social hoje! Brincadeiras à parte, vocês podem se aproximar para ver de perto a minha estrutura e tirar quantas fotos quiserem. Ah, e um recado importante: não deixem de passar na área de robótica do evento para participar das pesquisas que os meus colegas de laboratório estão conduzindo! Se tiverem dúvidas sobre mim, a equipe está logo aqui do lado para responder. Um excelente evento a todos!"
}

async def gerar_todos_audios():
    print("Iniciando a geração das falas do Roboldo (Edge-TTS)...\n")
    voice = "pt-BR-AntonioNeural"
    
    for arquivo, texto in roteiro.items():
        caminho_completo = os.path.join(pasta_destino, arquivo)
        print(f"Gerando: {arquivo}...")
        
        # Usando a sua configuração de tom e velocidade
        communicate = edge_tts.Communicate(texto, voice, rate="+10%", pitch="+15Hz")
        await communicate.save(caminho_completo)
        
    print("\nSucesso! Os 4 áudios foram criados na pasta 'audios_demonstracao'.")

if __name__ == "__main__":
    asyncio.run(gerar_todos_audios())
# Roboldo (Robô Social - UERN)

Roboldo é um robô social desenvolvido no LAR (Laboratório de Aprendizagem de Automação e Robótica) da Universidade do Estado do Rio Grande do Norte (UERN). Ele possui um rosto expressivo com matrizes de LED e dois braços mecânicos acionados via ESP32.

---

## 🚀 Como Executar

### 1. Clonar o Repositório
```bash
git clone -b ROBOLDO-IA https://github.com/mateusfurt/Roboldo.git
cd Roboldo/Roboldo-ROBOLDO-IA
```

### 2. Criar e Ativar o Ambiente Virtual
**No Linux:**
```bash
python3 -m venv venv-roboldo
source venv-roboldo/bin/activate
```

**No Windows:**
```bash
python -m venv venv-roboldo
venv-roboldo\Scripts\activate
```

### 3. Instalar as Dependências
```bash
pip install -r requirements.txt
```

### 4. Configurar as Variáveis de Ambiente
Copie o modelo `.env.example` para `.env`:
```bash
cp .env.example .env
```
Abra o arquivo `.env` e insira sua chave da API do Google Gemini:
```env
GOOGLE_API_KEY=sua_chave_do_gemini_aqui
SERIAL_PORT=/dev/ttyACM0
BAUD_RATE=115200
GEMINI_MODEL=gemini-2.5-flash-lite
```

### 5. Executar o Roboldo (Gemini IA)
```bash
python googleapi.py
```

---

## 📁 Estrutura Principal

- `googleapi.py`: Módulo principal de IA com Google Gemini (multimodal com áudio), síntese de voz (Edge-TTS), reprodução em thread paralela de feedback sonoro (`pensando.mp3`) e controle serial do ESP32 (expressões faciais e braços).
- `template.txt`: Instruções de sistema e personalidade do Roboldo (prompt com tabela de comandos de rosto e braço).
- `evento.py`: Modo de apresentação autônoma com coreografia pré-programada sincronizada por tempo.
- `requirements.txt`: Dependências do projeto.
- `.env.example`: Exemplo de configuração de variáveis de ambiente.
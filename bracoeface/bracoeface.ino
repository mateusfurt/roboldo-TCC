/*
 * Código Completo Roboldo: 2 Braços Independentes + Expressões Faciais 
 * --- CONTROLE DUPLO: BLUETOOTH E MONITOR SERIAL ---
 */

#include <ESP32Servo.h>
#include <BluetoothSerial.h>
#include <LedControl.h>

// ==========================================
// Configuração dos Pinos
// ==========================================
// Braço Esquerdo
const int PINO_BASE_ESQ = 32;
const int PINO_OMBRO_ESQ = 25;
const int PINO_COTOVELO_ESQ = 33;

// Braço Direito
const int PINO_BASE_DIR = 19;
const int PINO_OMBRO_DIR = 21;
const int PINO_COTOVELO_DIR = 18;

// Matrizes de LED
#define DIN 27  
#define CLK 12
#define CS 13
#define NUM_DISPLAYS 5

// ==========================================
// Objetos
// ==========================================
Servo baseEsq;
Servo ombroEsq;
Servo cotoveloEsq;
Servo baseDir;
Servo ombroDir;
Servo cotoveloDir;

BluetoothSerial SerialBT;
LedControl lc = LedControl(DIN, CLK, CS, NUM_DISPLAYS);

// ==========================================
// Variáveis do Rosto (LEDs)
// ==========================================
bool executandoFalar = false;

byte neutral_eye[8]     = {B00000000,B00011000,B00111100,B01111110,B01111110,B00111100,B00011000,B00000000};
byte spooky_eye[8]      = {B00111100,B01111110,B11111111,B11111111,B11111111,B11111111,B01111110,B00111100};
byte closed_eye_up[8]   = {B00000000,B00001100,B00011000,B00011000,B00011000,B00011000,B00001100,B00000000};
byte closed_eye_down[8] = {B00000000,B00001100,B00001100,B00000110,B00000110,B00001100,B00001100,B00000000};

byte sad_mouth[24]        = { B00000000, B00000000, B00000000, B00000000, B01100000, B00110000, B00011000, B00001100, B00001110, B00000110, B00000110, B00000110, B00000110, B00000110, B00000110, B00001100,B00001100, B00011000, B00110000, B01100000, B00000000, B00000000, B00000000, B00000000 }; 
byte happy_mouth[24]      = { B00000000, B00000000, B00000000, B00000000, B00000110, B00001100, B00011000, B00110000, B00110000, B01100000, B01100000, B01100000, B01100000, B01100000, B01100000, B00110000, B00110000, B00011000, B00001100, B00000110, B00000000, B00000000, B00000000, B00000000 };
byte lingua_mouth[24]     = { B00000000, B00000000, B00000000, B00111000, B00111110, B00011100, B00011000, B00110000, B00110000, B01100000, B01100000, B01100000, B01100000, B01100000, B01100000, B00110000, B00110000, B00011000, B00001100, B00000110, B00000000, B00000000, B00000000, B00000000 };  
byte very_happy_mouth[24] = { B00000000, B00000000, B00001110, B00111110, B01100110, B01100110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B11000110, B01100110, B01100110, B00111110, B00001110, B00000000, B00000000 };  
byte neutral_mouth[24]    = { B00000000, B00000000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00010000, B00000000, B00000000 };  
byte opened_mouth[24]     = { B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00011100, B00100010, B01000001, B01000001, B00100010, B00011100, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000, B00000000 }; 
byte tongue_mouth[24]     = { B00000000, B00000000, B00000000, B00111000, B00111110, B00011100, B00011000, B00110000, B00110000, B01100000, B01100000, B01100000, B01100000, B01100000, B01100000, B00110000, B00110000, B00011000, B00001100, B00000110, B00000000, B00000000, B00000000, B00000000 };

byte* eyes[] = {neutral_eye, spooky_eye, closed_eye_up, closed_eye_down};
byte* mouths[] = {sad_mouth, happy_mouth, very_happy_mouth, neutral_mouth, tongue_mouth, opened_mouth};

// ==========================================
// Funções da Matriz de LED (Rosto)
// ==========================================
void display_eyes(byte right_eye[], byte left_eye[]) {
  for (int i = 0; i < 8; i++) {
    lc.setRow(0, i, left_eye[i]);
    lc.setRow(1, i, right_eye[i]);
  }
}

void display_mouth(byte mouth[]) {
  for (int i = 0; i < 8; i++) {
    lc.setRow(2, i, mouth[i]);
    lc.setRow(3, i, mouth[i + 8]);
    lc.setRow(4, i, mouth[i + 16]);
  }
}

void feliz()     { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[1]); executandoFalar = false; }
void triste()    { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[0]); executandoFalar = false; }
void bocaberta() { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[2]); executandoFalar = false; }
void serio()     { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[3]); executandoFalar = false; }
void lingua()    { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[4]); executandoFalar = false; }
void surpreso()  { display_eyes(eyes[0], eyes[0]); display_mouth(mouths[5]); executandoFalar = false; }

void falar() {
  static unsigned long ultimoTempo = 0;
  static bool bocaAberta = false;

  if (millis() - ultimoTempo > 400) {
    bocaAberta = !bocaAberta;
    display_eyes(eyes[0], eyes[0]);
    display_mouth(bocaAberta ? mouths[2] : mouths[3]);
    ultimoTempo = millis();
  }
}

// ==========================================
// Funções de Motores SEPARADAS (Prontas para edição)
// ==========================================
void moverEsquerdo(int angBase, int angOmbro, int angCotovelo) {
  baseEsq.write(180 - angBase);
  ombroEsq.write(angOmbro);
  cotoveloEsq.write(180 - angCotovelo);
}

void moverDireito(int angBase, int angOmbro, int angCotovelo) {
  baseDir.write(180 - angBase);
  ombroDir.write(angOmbro);
  cotoveloDir.write(180 - angCotovelo);
}

// ==========================================
// Sequências de Ações (Abertas para edição fácil)
// ==========================================

void acaoPosicaoInicial() { 
  moverEsquerdo(0, 0, 90);
  moverDireito(180, 180, 90);
  delay(1000); 
}

void acaoAcenar() { 
  moverEsquerdo(0, 135, 90);
  delay(500);

  moverEsquerdo(0, 160, 140);
  delay(500);

  moverEsquerdo(0, 135, 90);
  delay(500);

  moverEsquerdo(0, 160, 140);
   delay(500);

  moverEsquerdo(0, 135, 90);
  delay(500);

  moverEsquerdo(0, 160, 140);
  delay(500);

  moverEsquerdo(0, 135, 90);
  delay(500);

  acaoPosicaoInicial(); 
}

void acaoSobeDesce() { 
  moverEsquerdo(0, 0, 90);
  moverDireito(180, 180, 90);
  delay(500); 

  moverEsquerdo(45, 0, 90);
  moverDireito(135, 180, 90);
  delay(500); 

  moverEsquerdo(90, 0, 90);
  moverDireito(90, 180, 90);
  delay(500); 

  moverEsquerdo(135, 0, 90);
  moverDireito(45, 180, 90);
  delay(500); 

  moverEsquerdo(180, 0, 90);
  moverDireito(0, 180, 90);
  delay(500); 

  moverEsquerdo(135, 0, 90);
  moverDireito(45, 180, 90);
  delay(500); 

  moverEsquerdo(90, 0, 90);
  moverDireito(90, 180, 90);
  delay(500); 

  moverEsquerdo(45, 0, 90);
  moverDireito(135, 180, 90);
  delay(500); 

  moverEsquerdo(0, 0, 90);
  moverDireito(180, 180, 90);
  delay(500); 

  acaoPosicaoInicial(); 
}

void acaoCelebrar() { 
  moverEsquerdo(0, 180, 180);
  moverDireito(180, 0, 0);
  delay(500); 

  moverEsquerdo(0, 135, 180);
  moverDireito(180, 45, 0);
  delay(500); 

  moverEsquerdo(0, 180, 90);
  moverDireito(180, 0, 90);
  delay(500); 

  moverEsquerdo(0, 135, 180);
  moverDireito(180, 45, 0);
  delay(500); 

  moverEsquerdo(0, 180, 90);
  moverDireito(180, 0, 90);
  delay(500); 

  moverEsquerdo(0, 135, 180);
  moverDireito(180, 45, 0);
  delay(500); 

  moverEsquerdo(0, 180, 90);
  moverDireito(180, 0, 90);
  delay(500); 

  moverEsquerdo(0, 135, 180);
  moverDireito(180, 45, 0);
  delay(500); 

  moverEsquerdo(0, 180, 90);
  moverDireito(180, 0, 90);
  delay(500); 

  moverEsquerdo(0, 135, 180);
  moverDireito(180, 45, 0);
  delay(500); 

  acaoPosicaoInicial(); 
}

void acaoPalmas() { 
  for(int i = 0; i < 10; i++) { 
    moverEsquerdo(95, 40, 90);
    moverDireito(70, 140, 90);
    delay(200); 

    moverEsquerdo(95, 0, 30);
    moverDireito(70, 180, 150);
    delay(200); 
  } 
  
  moverEsquerdo(95, 45, 90);
  moverDireito(70, 135, 90);
  delay(500); 

  acaoPosicaoInicial(); 
}

void acaoVoar() { 
  moverEsquerdo(0, 160, 140);
  moverDireito(180, 20, 40);
  delay(300); 

  for(int i = 0; i < 5; i++) { 
    moverEsquerdo(0, 160, 140);
    moverDireito(180, 20, 40);
    delay(300); 

    moverEsquerdo(0, 75, 75);
    moverDireito(180, 105, 105);
    delay(300); 
  } 
  
  acaoPosicaoInicial(); 
}

void acaoCintura() { 
  moverEsquerdo(0, 90, 0);
  moverDireito(180, 90, 180);
  delay(500); 

  moverEsquerdo(0, 40, 0);
  moverDireito(180, 140, 180);
  delay(2000); 

  moverEsquerdo(0, 55, 10);
  moverDireito(180, 125, 170);
  delay(100); 

  acaoPosicaoInicial(); 
}

void acaoFlex() { 
  moverEsquerdo(0, 125, 160);
  moverDireito(180, 55, 20);
  delay(1000); 

  moverEsquerdo(0, 80, 180);
  moverDireito(180, 100, 0);
  delay(2000); 

  moverEsquerdo(0, 125, 160);
  moverDireito(180, 55, 20);
  delay(1000); 

  moverEsquerdo(0, 80, 180);
  moverDireito(180, 100, 0);
  delay(2000); 

  acaoPosicaoInicial(); 
}

void acaoDanca() { 
  for(int i = 0; i < 5; i++) { 
    moverEsquerdo(90, 0, 90);
    moverDireito(75, 180, 90);
    delay(250); 

    moverEsquerdo(90, 45, 50);
    moverDireito(75, 135, 130);
    delay(250); 

    moverEsquerdo(90, 90, 0);
    moverDireito(75, 90, 180);
    delay(250); 

    moverEsquerdo(90, 45, 10);
    moverDireito(75, 135, 170);
    delay(250); 
  } 
  acaoPosicaoInicial(); 
}

void acaoApontar() { 
  moverEsquerdo(90, 90, 0);
  delay(500);
  moverEsquerdo(90, 0, 90); 
  delay(500);
  acaoPosicaoInicial(); 
}

void acaoBatePeito() { 
  moverEsquerdo(90, 0, 90);
  delay(600); 

  for(int i = 0; i < 2; i++) { 
    moverEsquerdo(90, 0, 40);
    delay(200); 
    moverEsquerdo(90, 0, 90);;
    delay(200); 
  } 
  acaoPosicaoInicial(); 
}

void acaoEspreguicar() { 
  moverEsquerdo(0, 150, 180);
  moverDireito(180, 30, 0);
  delay(1000); 

  moverEsquerdo(0, 180, 90);
  moverDireito(180, 0, 90);
  delay(1000); 

  for(int i = 170; i > 90; i--) { 
    moverEsquerdo(0, i, 90);
    moverDireito(180, 180 - i, 90);
    delay(10); 
  } 
  acaoPosicaoInicial(); 
}

void acaoIdle() { 
  for(int i = 0; i < 3; i++) { 
    for(int j = 0; j < 25; j++) { 
      moverEsquerdo(j, 0, 90);
      moverDireito(180 - j, 180, 90);
      delay(50); 
    } 
    delay(100); 
    for(int j = 25; j > 0; j--) { 
      moverEsquerdo(j, 0, 90);
      moverDireito(180 - j, 180, 90);
      delay(50); 
    } 
    delay(100); 
  } 
  acaoPosicaoInicial(); 
}

void acaoVolta() { 
  for(int i = 0; i < 180; i++) { 
    moverEsquerdo(0, i, 90);
    moverDireito(180, 180 - i, 90);
  } 
  delay(1000); 
  for(int i = 180; i > 0; i--) { 
    moverEsquerdo(0, i, 90);
    moverDireito(180, 180 - i, 90);
  } 
  acaoPosicaoInicial(); 
}

void acaoSoprarBeijo() { 
  moverEsquerdo(150, 0, 90);
  delay(300); 

  moverEsquerdo(150, 0, 15);
  delay(700); 

  moverEsquerdo(150, 0, 90);
  delay(500); 

  acaoPosicaoInicial(); 
}

// ==========================================
// Setup
// ==========================================
void setup() {
  Serial.begin(115200);
  
  // Inicializa Matrizes de LED
  for (int i = 0; i < NUM_DISPLAYS; i++) {
    lc.shutdown(i, false);
    lc.setIntensity(i, 1);
    lc.clearDisplay(i);
  }
  
  serio();

  // Inicializa Bluetooth
  SerialBT.begin("Roboldo_BT"); 
  Serial.println("Monitor Serial e Bluetooth prontos!");
  Serial.println("Conecte-se a 'Roboldo_BT' ou digite os comandos aqui.");

  // Timers para 6 Servos não travarem o ESP32
  ESP32PWM::allocateTimer(0);
  ESP32PWM::allocateTimer(1);
  ESP32PWM::allocateTimer(2);
  ESP32PWM::allocateTimer(3);

  baseEsq.setPeriodHertz(50);
  ombroEsq.setPeriodHertz(50);
  cotoveloEsq.setPeriodHertz(50);
  baseDir.setPeriodHertz(50);
  ombroDir.setPeriodHertz(50);
  cotoveloDir.setPeriodHertz(50);

  baseEsq.attach(PINO_BASE_ESQ, 500, 2400);
  ombroEsq.attach(PINO_OMBRO_ESQ, 500, 2400);
  cotoveloEsq.attach(PINO_COTOVELO_ESQ, 500, 2400);
  baseDir.attach(PINO_BASE_DIR, 500, 2400);
  ombroDir.attach(PINO_OMBRO_DIR, 500, 2400);
  cotoveloDir.attach(PINO_COTOVELO_DIR, 500, 2400);

  acaoPosicaoInicial();
  Serial.println("Sistema pronto! Aguardando comandos...");
}

// ==========================================
// Loop Principal
// ==========================================
void loop() {
  if (executandoFalar) {
    falar();
  }

  char cmd = '\0'; // Variável vazia para armazenar o comando de qualquer porta

  // 1. Checa se recebeu algo pelo Bluetooth
  if (SerialBT.available()) {
    cmd = SerialBT.read();
  } 
  // 2. Se não tem Bluetooth, checa se recebeu pelo cabo USB (Monitor Serial)
  else if (Serial.available()) {
    cmd = Serial.read();
  }

  // 3. Se um comando foi recebido de alguma das duas portas
  if (cmd != '\0' && cmd != '\n' && cmd != '\r') {
    
    // FILTRO DE BRAÇOS (Letras MAIÚSCULAS)
    if (cmd >= 'A' && cmd <= 'Z') {
      Serial.print("Comando de BRACOS recebido: ");
      Serial.println(cmd);
      
      if (cmd == 'A') { acaoAcenar(); } 
      else if (cmd == 'B') { acaoCelebrar(); } 
      else if (cmd == 'C') { acaoPalmas(); } 
      else if (cmd == 'D') { acaoCintura(); }
      else if (cmd == 'E') { acaoFlex(); }
      else if (cmd == 'F') { acaoDanca(); }
      else if (cmd == 'G') { acaoIdle(); }
      else if (cmd == 'H') { acaoApontar(); }
      else if (cmd == 'I') { acaoBatePeito(); }
      else if (cmd == 'J') { acaoEspreguicar(); }
      else if (cmd == 'K') { acaoSoprarBeijo(); }
      else if (cmd == 'W') { acaoVoar(); } 
      else if (cmd == 'X') { acaoSobeDesce(); } 
      else if (cmd == 'Y') { acaoVolta(); }
      else if (cmd == 'Z') { acaoPosicaoInicial(); }
    }
    
    // FILTRO DE ROSTO (Letras minúsculas)
    else if (cmd >= 'a' && cmd <= 'z') {
      Serial.print("Comando de ROSTO recebido: ");
      Serial.println(cmd);
      
      if (cmd == 'a') { feliz(); }
      else if (cmd == 'b') { triste(); }
      else if (cmd == 'c') { bocaberta(); }
      else if (cmd == 'd') { serio(); }
      else if (cmd == 'e') { lingua(); }
      else if (cmd == 'f') { surpreso(); }
      else if (cmd == 'g') { executandoFalar = true; }
      else if (cmd == 'h') { executandoFalar = false; serio(); } 
    }
  }
  
  delay(20); 
}

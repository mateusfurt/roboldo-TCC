#!/usr/bin/env python3
"""
Testes funcionais do Roboldo e medição de T_ser (independe de rede).

Usa o mesmo .env, a mesma porta serial, o mesmo baud rate e a mesma função de
envio do googleapi.py (write, pausa de 0,05 s e leitura da resposta do ESP32).
Coloque este arquivo na mesma pasta do googleapi.py e do .env.

Etapas:
  1. Expressões e boca: envia cada código várias vezes e você confere o rosto.
  2. Gestos dos braços: envia cada código várias vezes, volta para 'Z' e você confere o movimento.
  3. T_ser: mede o tempo que o programa gasta enviando os comandos de um ciclo de fala
     (expressão, 'g', gesto, 'h', expressão), exatamente como em executar_fala_e_gestos().
  4. Interações completas: você roda o googleapi.py e informa o resultado aqui.

Saídas (pasta testes_funcionais/): resultados.json, tser.csv, tabela_funcionais.tex

Uso:
  python testes_funcionais.py                 # tudo
  python testes_funcionais.py --reps 5        # 5 repetições por comando (padrão 3)
  python testes_funcionais.py --so-tser       # só a medição de T_ser
  python testes_funcionais.py --simular       # sem robô (apenas para testar o programa)
"""
import argparse
import csv
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent
SAIDA = BASE / "testes_funcionais"

EXPRESSOES = list("abcdef")           # rostos
BOCA = ["g", "h"]                     # boca falando / silenciada
GESTOS = list("ABCDEFHI") + ["Z"]    # braços (Z = posição neutra)


class Robo:
    """Mesmo comportamento de enviar_comando() do googleapi.py."""

    def __init__(self, simular):
        self.serial = None
        self.simular = simular
        if simular:
            print("[Modo simulação] nenhum comando será enviado ao robô.")
            return
        import serial
        from dotenv import load_dotenv
        load_dotenv(BASE / ".env")
        porta = os.getenv("SERIAL_PORT")
        baud = os.getenv("BAUD_RATE")
        if not porta or not baud:
            sys.exit("SERIAL_PORT e BAUD_RATE não encontrados no .env desta pasta.")
        self.serial = serial.Serial(porta, int(baud), timeout=1)
        print(f"Conectado ao ESP32 ({porta} @ {baud} bps). Aguardando o Roboldo iniciar...")
        time.sleep(3)
        self.porta, self.baud = porta, int(baud)

    def enviar(self, comando):
        """Retorna (feedback_do_esp32, tempo_gasto_s)."""
        t0 = time.perf_counter()
        feedback = ""
        if self.serial:
            self.serial.write(comando.encode())
            time.sleep(0.05)
            if self.serial.in_waiting > 0:
                feedback = self.serial.readline().decode("utf-8", errors="ignore").strip()
        else:
            time.sleep(0.05)
        return feedback, time.perf_counter() - t0

    def fechar(self):
        if self.serial:
            self.serial.close()


def tex(s):
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("_", r"\_"),
                 ("#", r"\#"), ("$", r"\$"), ("{", r"\{"), ("}", r"\}")):
        s = s.replace(a, b)
    return s


def perguntar_sucessos(total):
    while True:
        r = input(f"   Funcionou em quantas das {total}? [Enter = todas] ").strip()
        if r == "":
            return total
        if r.isdigit() and 0 <= int(r) <= total:
            return int(r)
        print("   Digite um número entre 0 e", total)


def contraste(cod, tipo):
    """Estado diferente do testado, enviado antes de cada repetição, para que a
    mudança seja visível mesmo quando o mesmo código é repetido."""
    if tipo == "Expressão":
        return "b" if cod == "a" else "a"
    if tipo == "Boca":
        return "h" if cod == "g" else "g"
    return "A" if cod == "Z" else "Z"


def testar_comandos(robo, codigos, tipo, reps, espera, resultados, voltar_neutro):
    for cod in codigos:
        base = contraste(cod, tipo)
        print(f"\n[{tipo}] Código '{cod}': {reps} envios, cada um precedido de '{base}' "
              f"(estado diferente), para você ver a mudança")
        respostas = []
        for i in range(reps):
            robo.enviar(base)
            time.sleep(espera)
            print(f"   envio {i+1}/{reps}: '{cod}' agora")
            fb, _ = robo.enviar(cod)
            if fb:
                respostas.append(fb)
            time.sleep(espera)
        ok = perguntar_sucessos(reps)
        obs = input("   Observação (Enter = nenhuma): ").strip()
        resultados.append({"codigo": cod, "tipo": tipo, "repeticoes": reps,
                           "sucessos": ok, "observacao": obs,
                           "resposta_esp32": sorted(set(respostas))})


def medir_tser(robo, n, resultados):
    """Mede o tempo de envio de um ciclo completo, sem esperar o término dos gestos."""
    print(f"\n[T_ser] {n} ciclos (expressão, 'g', gesto, 'h', expressão) + 'Z'")
    print("   O robô vai se mexer. Pausa de 4 s entre ciclos para os braços terminarem.")
    ciclo = [("expressao", None), ("g", "g"), ("gesto", None), ("h", "h"), ("expressao", None)]
    linhas = []
    for i in range(n):
        emocao = EXPRESSOES[i % len(EXPRESSOES)]
        gesto = [g for g in GESTOS if g != "Z"][i % (len(GESTOS) - 1)]
        tempos = []
        t0 = time.perf_counter()
        for nome, fixo in ciclo:
            cod = emocao if nome == "expressao" else gesto if nome == "gesto" else fixo
            _, dt = robo.enviar(cod)
            tempos.append(dt)
        total5 = time.perf_counter() - t0
        _, dtz = robo.enviar("Z")
        linhas.append({"ciclo": i + 1, "emocao": emocao, "gesto": gesto,
                       "t_ciclo_s": total5, "t_z_s": dtz,
                       "t_ciclo_com_z_s": total5 + dtz,
                       "t_cmd_medio_s": statistics.mean(tempos)})
        print(f"   ciclo {i+1:02d}/{n}: {total5:.3f} s (com 'Z': {total5 + dtz:.3f} s)")
        time.sleep(4)
    SAIDA.mkdir(exist_ok=True)
    with open(SAIDA / "tser.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        w.writeheader()
        w.writerows(linhas)

    def resumo(chave):
        v = [l[chave] for l in linhas]
        q = statistics.quantiles(v, n=4) if len(v) >= 2 else [v[0]] * 3
        return {"n": len(v), "mediana": statistics.median(v), "q1": q[0], "q3": q[2],
                "media": statistics.mean(v), "dp": statistics.stdev(v) if len(v) > 1 else 0.0,
                "min": min(v), "max": max(v)}
    resultados["t_ser"] = {"ciclo_5_comandos_s": resumo("t_ciclo_s"),
                           "ciclo_com_z_s": resumo("t_ciclo_com_z_s"),
                           "por_comando_s": resumo("t_cmd_medio_s")}
    r5, r6 = resultados["t_ser"]["ciclo_5_comandos_s"], resultados["t_ser"]["ciclo_com_z_s"]
    print(f"\n   T_ser (5 comandos): mediana {r5['mediana']:.3f} s "
          f"(Q1-Q3 {r5['q1']:.3f}-{r5['q3']:.3f}; mín {r5['min']:.3f}; máx {r5['max']:.3f})")
    print(f"   T_ser (6 comandos, com 'Z'): mediana {r6['mediana']:.3f} s")


def interacoes_completas(resultados):
    print("\n[Interações completas] Rode o googleapi.py e converse com o Roboldo.")
    print("   Verifique se a fala, o rosto e os braços atuam juntos.")
    r = input("   Quantas interações completas você fez? [Enter = pular] ").strip()
    if not r.isdigit() or int(r) == 0:
        return
    n = int(r)
    ok = perguntar_sucessos(n)
    obs = input("   Observação (Enter = nenhuma): ").strip()
    resultados["interacoes"] = {"total": n, "sucessos": ok, "observacao": obs}


def gerar_tabela(resultados):
    L = ["% Gerado por testes_funcionais.py",
         "\\begin{table}[htbp]", "    \\centering",
         "    \\caption{Resultados dos testes funcionais dos comandos do robô}",
         "    \\label{tab:funcionais}", "    \\small",
         "    \\begin{tabular}{llccp{6cm}}", "        \\hline",
         "        \\textbf{Tipo} & \\textbf{Código} & \\textbf{Envios} & \\textbf{Corretos} & \\textbf{Observação} \\\\",
         "        \\hline"]
    ultimo = None
    for r in resultados["comandos"]:
        if ultimo and r["tipo"] != ultimo:
            L.append("        \\hline")
        t = r["tipo"] if r["tipo"] != ultimo else ""
        ultimo = r["tipo"]
        L.append(f"        {t} & \\texttt{{{r['codigo']}}} & {r['repeticoes']} & {r['sucessos']} & "
                 f"{tex(r['observacao']) or '--'} \\\\")
    L += ["        \\hline", "    \\end{tabular}",
          "    \\fonte{Elaborada pelo autor (2026).}", "\\end{table}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Testes funcionais e T_ser do Roboldo")
    ap.add_argument("--reps", type=int, default=3, help="envios por comando (padrão 3)")
    ap.add_argument("--espera-rosto", type=float, default=1.0)
    ap.add_argument("--espera-braco", type=float, default=3.0, help="tempo para o gesto terminar")
    ap.add_argument("--ciclos-tser", type=int, default=20)
    ap.add_argument("--so-tser", action="store_true")
    ap.add_argument("--pular-tser", action="store_true")
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()

    robo = Robo(a.simular)
    res = {"data": datetime.now().astimezone().isoformat(timespec="seconds"),
           "porta": getattr(robo, "porta", None), "baud": getattr(robo, "baud", None),
           "simulacao": a.simular, "repeticoes": a.reps, "comandos": []}
    try:
        if not a.so_tser:
            input("\nConfira: robô ligado, braços livres para se mover. Enter para começar.")
            robo.enviar("Z")
            testar_comandos(robo, EXPRESSOES, "Expressão", a.reps, a.espera_rosto, res["comandos"], False)
            testar_comandos(robo, BOCA, "Boca", a.reps, a.espera_rosto, res["comandos"], False)
            testar_comandos(robo, GESTOS, "Gesto", a.reps, a.espera_braco, res["comandos"], True)
        if not a.pular_tser:
            medir_tser(robo, a.ciclos_tser, res)
        if not a.so_tser:
            interacoes_completas(res)
    finally:
        robo.enviar("a")
        robo.enviar("Z")
        robo.fechar()

    SAIDA.mkdir(exist_ok=True)
    (SAIDA / "resultados.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if res["comandos"]:
        (SAIDA / "tabela_funcionais.tex").write_text(gerar_tabela(res), encoding="utf-8")
        print("\n" + gerar_tabela(res))
    total = sum(r["repeticoes"] for r in res["comandos"])
    ok = sum(r["sucessos"] for r in res["comandos"])
    if total:
        print(f"\nTotal: {ok} de {total} envios corretos.")
    print(f"Arquivos salvos em: {SAIDA}")


if __name__ == "__main__":
    main()
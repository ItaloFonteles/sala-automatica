"""Inicia a Sala Automática.

Exemplos:
    python main.py --sim                 # testa sem câmera, sem microfone, sem OBS
    python main.py                       # modo real, usando config.toml
    python main.py --listar-audio        # mostra as placas de som e seus números
"""

import argparse
import logging
import sys

if sys.version_info < (3, 11):
    sys.exit("A Sala Automática precisa do Python 3.11 ou mais novo.")


def main() -> None:
    p = argparse.ArgumentParser(description="Sala Automática - diretor de câmeras PTZ")
    p.add_argument("--config", default="config.toml", help="arquivo de configuração")
    p.add_argument("--sim", action="store_true", help="força o modo simulação")
    p.add_argument("--porta", type=int, default=8080, help="porta do painel web")
    p.add_argument("--listar-audio", action="store_true", help="lista dispositivos de áudio e sai")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-8s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("obsws_python").setLevel(logging.WARNING)  # não mostrar a senha do OBS no log

    if args.listar_audio:
        from salaauto.audio import listar_dispositivos

        print(listar_dispositivos())
        return

    from salaauto.servidor import Aplicacao, servir

    app = Aplicacao(args.config, forcar_simulacao=args.sim)
    try:
        servidor = servir(app, args.porta)
    except OSError:
        sys.exit(
            f"\n  A porta {args.porta} já está em uso: a Sala Automática provavelmente já está aberta"
            "\n  em outra janela. Feche a outra janela (ou use --porta 8081) e tente de novo.\n"
        )
    app.iniciar()
    sim = [p for p, v in app.partes_simuladas.items() if v]
    modo = "SIMULAÇÃO" if len(sim) == 3 else ("REAL" if not sim else "MISTO - simulando: " + ", ".join(sim))
    print(f"\n  Sala Automática ({modo})")
    print(f"  Painel do operador: http://localhost:{args.porta}")
    print("  Para encerrar: feche esta janela ou aperte Ctrl+C\n")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()
        app.parar()


if __name__ == "__main__":
    main()

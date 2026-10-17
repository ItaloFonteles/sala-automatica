"""Inicia a Sala Automática.

Exemplos:
    python main.py --sim                 # testa sem câmera, sem microfone, sem OBS
    python main.py                       # modo real, usando config.yaml
    python main.py --listar-audio        # mostra as placas de som e seus números
"""

import argparse
import logging

import uvicorn


def main() -> None:
    p = argparse.ArgumentParser(description="Sala Automática - diretor de câmeras PTZ")
    p.add_argument("--config", default="config.yaml", help="arquivo de configuração")
    p.add_argument("--sim", action="store_true", help="força o modo simulação")
    p.add_argument("--porta", type=int, default=8080, help="porta do painel web")
    p.add_argument("--listar-audio", action="store_true", help="lista dispositivos de áudio e sai")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-8s %(message)s", datefmt="%H:%M:%S")

    if args.listar_audio:
        from salaauto.audio import listar_dispositivos

        print(listar_dispositivos())
        return

    from salaauto.servidor import criar_app

    app = criar_app(args.config, forcar_simulacao=args.sim)
    print(f"\n  Painel do operador: http://localhost:{args.porta}\n")
    uvicorn.run(app, host="0.0.0.0", port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()

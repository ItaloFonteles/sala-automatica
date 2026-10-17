"""Cria no OBS as cenas que o config.toml usa (ex.: Geral, Geral 2, Cam1, Cam2).

Cada cena ganha um fundo colorido e uma etiqueta com o nome, para dar para
ver a troca de cena acontecendo mesmo sem câmera. Quando as câmeras chegarem,
basta adicionar a "Fonte de mídia" (RTSP) em cada cena.

Uso:  python configurar_obs.py            (lê obs.senha do config.toml)
      python configurar_obs.py --config config_teste_notebook.toml
Não apaga nem mexe em cenas que já existem.
"""

import argparse
import sys
import tomllib

CORES = [0xFF8A3B1E, 0xFF1E5C8A, 0xFF2E7D32, 0xFF6A1B9A, 0xFF8A6D1E, 0xFF7D2E2E]  # ABGR


def cenas_do_config(cfg: dict) -> list[str]:
    nomes: list[str] = []
    pg = cfg["plano_geral"]
    planos = pg["planos"] if "planos" in pg else [pg]
    for p in planos + [p for l in cfg["lugares"] for p in l["planos"]]:
        if p["cena"] not in nomes:
            nomes.append(p["cena"])
    return nomes


def main() -> None:
    ap = argparse.ArgumentParser(description="Cria as cenas da Sala Automática no OBS")
    ap.add_argument("--config", default="config.toml")
    args = ap.parse_args()

    with open(args.config, "rb") as f:
        cfg = tomllib.load(f)
    o = cfg.get("obs", {})
    cenas = cenas_do_config(cfg)

    import obsws_python as obsws

    try:
        cli = obsws.ReqClient(host=o.get("host", "localhost"), port=int(o.get("porta", 4455)), password=o.get("senha", ""), timeout=5)
    except Exception as e:  # noqa: BLE001
        sys.exit(
            f"\n  Não conectei ao OBS: {e}\n"
            "  Confira: OBS aberto, Ferramentas > Configurações do servidor WebSocket > Ativar,\n"
            "  porta 4455 e a mesma senha do config.toml (obs.senha).\n"
        )

    v = cli.get_version()
    print(f"Conectado ao OBS {v.obs_version} (WebSocket {v.obs_web_socket_version})")
    video = cli.get_video_settings()
    largura, altura = video.base_width, video.base_height

    tipos = cli.get_input_kind_list(False).input_kinds
    tipo_texto = next((t for t in tipos if t.startswith("text_gdiplus")), None) or next(
        (t for t in tipos if t.startswith("text_ft2_source")), None
    )
    tipo_cor = next((t for t in tipos if t.startswith("color_source")), None)

    existentes = {s["sceneName"] for s in cli.get_scene_list().scenes}
    for i, cena in enumerate(cenas):
        if cena in existentes:
            print(f"  = cena '{cena}' já existe (não mexi)")
            continue
        cli.create_scene(cena)
        if tipo_cor:
            cli.create_input(cena, f"{cena} - fundo", tipo_cor, {"color": CORES[i % len(CORES)], "width": largura, "height": altura}, True)
        if tipo_texto:
            cli.create_input(
                cena,
                f"{cena} - etiqueta",
                tipo_texto,
                {"text": cena.upper(), "font": {"face": "Arial", "size": 160, "style": "Bold"}, "color": 0xFFFFFFFF},
                True,
            )
            item = cli.get_scene_item_id(cena, f"{cena} - etiqueta").scene_item_id
            cli.set_scene_item_transform(
                cena, item, {"positionX": largura / 2, "positionY": altura / 2, "alignment": 0}
            )
        print(f"  + cena '{cena}' criada")
    print("\nPronto. Quando tiver as câmeras, adicione a Fonte de mídia (RTSP) em cada cena.")


if __name__ == "__main__":
    main()

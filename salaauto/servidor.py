"""Servidor web: API + painel do operador.

Usa só a biblioteca padrão do Python (nada para instalar), para funcionar
em qualquer versão nova do Python e em qualquer PC da sala.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .audio import MedidorPlacaDeSom, MedidorSimulado
from .diretor import Diretor, Lugar, Plano
from .obs import ObsControle
from .visca import ViscaCamera

log = logging.getLogger("servidor")
PASTA_WEB = Path(__file__).resolve().parent.parent / "web"


class ErroApi(Exception):
    def __init__(self, status: int, mensagem: str) -> None:
        super().__init__(mensagem)
        self.status = status
        self.mensagem = mensagem


def carregar_config(caminho: str) -> dict:
    with open(caminho, "rb") as f:
        return tomllib.load(f)


def _plano(d: dict, cameras: dict) -> Plano:
    cam = d.get("camera")
    if cam is not None and cam not in cameras:
        raise ValueError(f"Plano usa a câmera '{cam}', que não existe na lista de câmeras.")
    return Plano(cena=d["cena"], camera=cam, preset=d.get("preset"))


def partes_simuladas(cfg: dict, simulacao: bool) -> dict[str, bool]:
    """Quais partes rodam simuladas. `simulacao = true` simula tudo; a seção
    [simular] permite simular só uma parte (ex.: OBS e microfone reais,
    câmeras simuladas)."""
    s = cfg.get("simular", {})
    return {parte: simulacao or bool(s.get(parte, False)) for parte in ("cameras", "obs", "audio")}


def montar(cfg: dict, simulacao: bool):
    sim = partes_simuladas(cfg, simulacao)
    cameras = {
        c["nome"]: ViscaCamera(
            nome=c["nome"],
            ip=c["ip"],
            porta=int(c.get("porta", 52381)),
            protocolo=c.get("protocolo", "sony_udp"),
            endereco=int(c.get("endereco", 1)),
            simulacao=sim["cameras"],
        )
        for c in cfg["cameras"]
    }
    o = cfg.get("obs", {})
    obs = ObsControle(o.get("host", "localhost"), int(o.get("porta", 4455)), o.get("senha", ""), sim["obs"])

    lugares = [Lugar(l["nome"], int(l["canal"]), [_plano(p, cameras) for p in l["planos"]]) for l in cfg["lugares"]]
    if not lugares:
        raise ValueError("Cadastre pelo menos um lugar em [[lugares]].")
    a = cfg.get("audio", {})
    canais = int(a.get("canais", max(l.canal for l in lugares)))
    if sim["audio"]:
        medidor = MedidorSimulado(canais)
    else:
        disp = a.get("dispositivo", -1)
        medidor = MedidorPlacaDeSom(canais, None if disp in (-1, "") else disp, int(a.get("taxa", 48000)))

    pg = cfg["plano_geral"]
    planos_geral = [_plano(p, cameras) for p in pg["planos"]] if "planos" in pg else [_plano(pg, cameras)]
    diretor = Diretor(cameras, obs, medidor, lugares, planos_geral, cfg.get("regras"))
    return diretor, cameras, obs, medidor


class Aplicacao:
    """Junta tudo: diretor rodando num laço asyncio próprio + rotas da API."""

    def __init__(self, caminho_config: str, forcar_simulacao: bool = False) -> None:
        cfg = carregar_config(caminho_config)
        self.simulacao = forcar_simulacao or bool(cfg.get("simulacao", False))
        self.partes_simuladas = partes_simuladas(cfg, self.simulacao)
        self.diretor, self.cameras, self.obs, self.medidor = montar(cfg, self.simulacao)
        self.loop = asyncio.new_event_loop()
        self._thread: threading.Thread | None = None
        self._tarefa = None

    # ------------------------------------------------------------ ciclo
    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self.loop.run_forever, name="diretor", daemon=True)
        self._thread.start()
        self.obs.conectar()
        self.medidor.iniciar()
        self._rodar(self.diretor.ir_para_geral("início"))
        self._tarefa = asyncio.run_coroutine_threadsafe(self.diretor.rodar(), self.loop)

    def parar(self) -> None:
        if self._tarefa is not None:
            self._tarefa.cancel()
        self.medidor.parar()
        self.loop.call_soon_threadsafe(self.loop.stop)

    def _rodar(self, coro, timeout: float = 30.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def _cam(self, nome: str) -> ViscaCamera:
        if nome not in self.cameras:
            raise ErroApi(404, f"Câmera '{nome}' não existe")
        return self.cameras[nome]

    # ------------------------------------------------------------ rotas
    def estado(self) -> dict:
        d, obs = self.diretor, self.obs
        niveis = self.medidor.leitura()
        return {
            "simulacao": isinstance(self.medidor, MedidorSimulado),
            "simulado": self.partes_simuladas,
            "modo": d.modo,
            "no_ar": d.rotulo_no_ar,
            "cena": obs.cena_atual,
            "lugar_ativo": d.lugar_ativo.nome if d.lugar_ativo else None,
            "obs": {
                "conectado": obs.conectado,
                "transmitindo": obs.transmitindo,
                "gravando": obs.gravando,
                "erro": obs.ultimo_erro,
            },
            "limiar_db": d.limiar_db,
            "lugares": [
                {"nome": l.nome, "canal": l.canal, "db": round(niveis.get(l.canal, -120.0), 1)} for l in d.lugares
            ],
            "cameras": [
                {"nome": c.nome, "preset": c.ultimo_preset, "erro": c.ultimo_erro, "no_ar": d._camera_no_ar() == c.nome}
                for c in self.cameras.values()
            ],
            "eventos": list(d.eventos),
        }

    def post(self, caminho: str, corpo: dict) -> dict:
        d = self.diretor
        if caminho == "/api/modo":
            try:
                d.definir_modo(corpo.get("modo", ""))
            except ValueError as e:
                raise ErroApi(400, str(e)) from e
            return {"modo": d.modo}

        if m := re.fullmatch(r"/api/lugar/(.+)", caminho):
            nome = m.group(1)
            if nome not in d.lugar_por_nome:
                raise ErroApi(404, f"Lugar '{nome}' não existe")
            d.definir_modo("manual")
            self._rodar(d.ir_para_lugar(nome, "manual"))
            return {"no_ar": d.rotulo_no_ar}

        if caminho == "/api/geral":
            d.definir_modo("manual")
            self._rodar(d.ir_para_geral("manual"))
            return {"no_ar": d.rotulo_no_ar}

        if m := re.fullmatch(r"/api/camera/([^/]+)/preset/(\d+)/(chamar|salvar)", caminho):
            cam, numero, acao = self._cam(m.group(1)), int(m.group(2)), m.group(3)
            ok = cam.chamar_preset(numero) if acao == "chamar" else cam.salvar_preset(numero)
            return {"ok": ok}

        if m := re.fullmatch(r"/api/camera/([^/]+)/mover", caminho):
            ok = self._cam(m.group(1)).mover(int(corpo.get("pan", 0)), int(corpo.get("tilt", 0)), int(corpo.get("velocidade", 8)))
            return {"ok": ok}

        if m := re.fullmatch(r"/api/camera/([^/]+)/zoom", caminho):
            ok = self._cam(m.group(1)).zoom(int(corpo.get("direcao", 0)), int(corpo.get("velocidade", 3)))
            return {"ok": ok}

        if m := re.fullmatch(r"/api/sessao/(iniciar|encerrar)", caminho):
            if m.group(1) == "iniciar":
                ok = self.obs.iniciar_sessao()
                d._evento("Sessão INICIADA (gravando + transmitindo)")
            else:
                ok = self.obs.encerrar_sessao()
                d._evento("Sessão ENCERRADA")
            return {"ok": ok}

        if caminho == "/api/simular/fala":
            if not isinstance(self.medidor, MedidorSimulado):
                raise ErroApi(400, "Só funciona no modo simulação")
            canal = corpo.get("canal")
            self.medidor.definir_quem_fala(None if canal is None else int(canal))
            return {"falando": canal}

        raise ErroApi(404, f"Rota não encontrada: {caminho}")


def criar_handler(app: Aplicacao):
    from urllib.parse import unquote, urlsplit

    class Handler(BaseHTTPRequestHandler):
        server_version = "SalaAutomatica/0.1"

        def log_message(self, fmt, *args):  # silencia o log de cada requisição
            log.debug(fmt, *args)

        def _json(self, status: int, dados: dict) -> None:
            corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def do_GET(self):
            caminho = unquote(urlsplit(self.path).path)
            if caminho in ("/", "/index.html"):
                corpo = (PASTA_WEB / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)
            elif caminho == "/api/estado":
                self._json(200, app.estado())
            else:
                self._json(404, {"erro": "não encontrado"})

        def do_POST(self):
            caminho = unquote(urlsplit(self.path).path)
            tamanho = int(self.headers.get("Content-Length") or 0)
            try:
                bruto = self.rfile.read(tamanho) if tamanho else b""
                corpo = json.loads(bruto or b"{}")
                if not isinstance(corpo, dict):
                    raise ErroApi(400, "Corpo deve ser um objeto JSON")
                self._json(200, app.post(caminho, corpo))
            except ErroApi as e:
                self._json(e.status, {"erro": e.mensagem})
            except (ValueError, TypeError) as e:
                self._json(400, {"erro": str(e)})
            except Exception as e:  # noqa: BLE001
                log.exception("Erro na rota %s", caminho)
                self._json(500, {"erro": str(e)})

    return Handler


class _Servidor(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa DOIS programas usarem a mesma porta ao mesmo
    # tempo (o painel falaria com a cópia errada). Lá, desligamos isso.
    allow_reuse_address = os.name != "nt"


def servir(app: Aplicacao, porta: int = 8080, host: str = "0.0.0.0") -> ThreadingHTTPServer:
    servidor = _Servidor((host, porta), criar_handler(app))
    servidor.daemon_threads = True
    return servidor

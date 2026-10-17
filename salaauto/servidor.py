"""Servidor web: API + painel do operador."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .audio import MedidorPlacaDeSom, MedidorSimulado
from .diretor import Diretor, Lugar, Plano
from .obs import ObsControle
from .visca import ViscaCamera

log = logging.getLogger("servidor")
PASTA_WEB = Path(__file__).resolve().parent.parent / "web"


def _plano(d: dict, cameras: dict) -> Plano:
    cam = d.get("camera")
    if cam is not None and cam not in cameras:
        raise ValueError(f"Plano usa a câmera '{cam}', que não existe na lista 'cameras'.")
    return Plano(cena=d["cena"], camera=cam, preset=d.get("preset"))


def montar(cfg: dict, simulacao: bool) -> tuple[Diretor, dict, ObsControle, object]:
    cameras = {
        c["nome"]: ViscaCamera(
            nome=c["nome"],
            ip=c["ip"],
            porta=int(c.get("porta", 52381)),
            protocolo=c.get("protocolo", "sony_udp"),
            endereco=int(c.get("endereco", 1)),
            simulacao=simulacao,
        )
        for c in cfg["cameras"]
    }
    o = cfg.get("obs", {})
    obs = ObsControle(o.get("host", "localhost"), int(o.get("porta", 4455)), o.get("senha", ""), simulacao)

    lugares = [Lugar(l["nome"], int(l["canal"]), [_plano(p, cameras) for p in l["planos"]]) for l in cfg["lugares"]]
    if not lugares:
        raise ValueError("Cadastre pelo menos um lugar em 'lugares'.")
    a = cfg.get("audio", {})
    canais = int(a.get("canais", max(l.canal for l in lugares)))
    if simulacao:
        medidor = MedidorSimulado(canais)
    else:
        medidor = MedidorPlacaDeSom(canais, a.get("dispositivo"), int(a.get("taxa", 48000)))

    diretor = Diretor(cameras, obs, medidor, lugares, _plano(cfg["plano_geral"], cameras), cfg.get("regras"))
    return diretor, cameras, obs, medidor


class Movimento(BaseModel):
    pan: int = 0
    tilt: int = 0
    velocidade: int = 8


class Zoom(BaseModel):
    direcao: int = 0
    velocidade: int = 3


class Fala(BaseModel):
    canal: int | None = None


class Modo(BaseModel):
    modo: str


def criar_app(caminho_config: str, forcar_simulacao: bool = False) -> FastAPI:
    cfg = yaml.safe_load(Path(caminho_config).read_text(encoding="utf-8"))
    simulacao = forcar_simulacao or bool(cfg.get("simulacao", False))
    diretor, cameras, obs, medidor = montar(cfg, simulacao)

    @asynccontextmanager
    async def ciclo(app: FastAPI):
        await asyncio.to_thread(obs.conectar)
        medidor.iniciar()
        await diretor.ir_para_geral("início")
        tarefa = asyncio.create_task(diretor.rodar())
        yield
        tarefa.cancel()
        medidor.parar()

    app = FastAPI(title="Sala Automática", lifespan=ciclo)

    def _cam(nome: str) -> ViscaCamera:
        if nome not in cameras:
            raise HTTPException(404, f"Câmera '{nome}' não existe")
        return cameras[nome]

    @app.get("/")
    def painel():
        return FileResponse(PASTA_WEB / "index.html")

    @app.get("/api/estado")
    def estado():
        niveis = medidor.leitura()
        return {
            "simulacao": simulacao,
            "modo": diretor.modo,
            "no_ar": diretor.rotulo_no_ar,
            "cena": obs.cena_atual,
            "lugar_ativo": diretor.lugar_ativo.nome if diretor.lugar_ativo else None,
            "obs": {
                "conectado": obs.conectado,
                "transmitindo": obs.transmitindo,
                "gravando": obs.gravando,
                "erro": obs.ultimo_erro,
            },
            "limiar_db": diretor.limiar_db,
            "lugares": [
                {"nome": l.nome, "canal": l.canal, "db": round(niveis.get(l.canal, -120.0), 1)}
                for l in diretor.lugares
            ],
            "cameras": [
                {"nome": c.nome, "preset": c.ultimo_preset, "erro": c.ultimo_erro, "no_ar": diretor._camera_no_ar() == c.nome}
                for c in cameras.values()
            ],
            "eventos": list(diretor.eventos),
        }

    @app.post("/api/modo")
    def modo(m: Modo):
        try:
            diretor.definir_modo(m.modo)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"modo": diretor.modo}

    @app.post("/api/lugar/{nome}")
    async def lugar(nome: str):
        if nome not in diretor.lugar_por_nome:
            raise HTTPException(404, f"Lugar '{nome}' não existe")
        diretor.definir_modo("manual")
        await diretor.ir_para_lugar(nome, "manual")
        return {"no_ar": diretor.rotulo_no_ar}

    @app.post("/api/geral")
    async def geral():
        diretor.definir_modo("manual")
        await diretor.ir_para_geral("manual")
        return {"no_ar": diretor.rotulo_no_ar}

    @app.post("/api/camera/{nome}/preset/{numero}/{acao}")
    async def preset(nome: str, numero: int, acao: str):
        cam = _cam(nome)
        if acao == "chamar":
            ok = await asyncio.to_thread(cam.chamar_preset, numero)
        elif acao == "salvar":
            ok = await asyncio.to_thread(cam.salvar_preset, numero)
        else:
            raise HTTPException(400, "ação deve ser 'chamar' ou 'salvar'")
        return {"ok": ok}

    @app.post("/api/camera/{nome}/mover")
    async def mover(nome: str, m: Movimento):
        ok = await asyncio.to_thread(_cam(nome).mover, m.pan, m.tilt, m.velocidade)
        return {"ok": ok}

    @app.post("/api/camera/{nome}/zoom")
    async def zoom(nome: str, z: Zoom):
        ok = await asyncio.to_thread(_cam(nome).zoom, z.direcao, z.velocidade)
        return {"ok": ok}

    @app.post("/api/sessao/{acao}")
    async def sessao(acao: str):
        if acao == "iniciar":
            ok = await asyncio.to_thread(obs.iniciar_sessao)
            diretor._evento("Sessão INICIADA (gravando + transmitindo)")
        elif acao == "encerrar":
            ok = await asyncio.to_thread(obs.encerrar_sessao)
            diretor._evento("Sessão ENCERRADA")
        else:
            raise HTTPException(400, "ação deve ser 'iniciar' ou 'encerrar'")
        return {"ok": ok}

    @app.post("/api/simular/fala")
    def simular_fala(f: Fala):
        if not isinstance(medidor, MedidorSimulado):
            raise HTTPException(400, "Só funciona no modo simulação")
        medidor.definir_quem_fala(f.canal)
        return {"falando": f.canal}

    return app

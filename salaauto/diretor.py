"""Diretor automático: decide qual câmera vai ao ar com base em quem está falando.

Regra de ouro de transmissão: nunca mostrar uma câmera se mexendo.
Por isso o diretor sempre move uma câmera que NÃO está no ar, espera ela
parar (tempo de assentamento) e só então corta para ela.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from .audio import MedidorNivel
from .obs import ObsControle
from .visca import ViscaCamera

log = logging.getLogger("diretor")


@dataclass(frozen=True)
class Plano:
    """Um enquadramento: cena do OBS + (opcional) câmera e preset."""

    cena: str
    camera: str | None = None
    preset: int | None = None


@dataclass
class Lugar:
    """Uma cadeira/posição da sala ligada a um canal de microfone."""

    nome: str
    canal: int
    planos: list[Plano]


class Diretor:
    def __init__(
        self,
        cameras: dict[str, ViscaCamera],
        obs: ObsControle,
        medidor: MedidorNivel,
        lugares: list[Lugar],
        plano_geral: Plano,
        regras: dict | None = None,
    ) -> None:
        regras = regras or {}
        self.cameras = cameras
        self.obs = obs
        self.medidor = medidor
        self.lugares = lugares
        self.lugar_por_nome = {l.nome: l for l in lugares}
        self.plano_geral = plano_geral
        self.limiar_db = float(regras.get("limiar_db", -40))
        self.tempo_fala_s = float(regras.get("tempo_minimo_fala_s", 1.5))
        self.tempo_plano_s = float(regras.get("tempo_minimo_plano_s", 4.0))
        self.silencio_geral_s = float(regras.get("silencio_para_geral_s", 6.0))
        self.assentamento_s = float(regras.get("tempo_assentamento_s", 1.2))

        self.modo = "auto"  # "auto" ou "manual"
        self.no_ar: Plano | None = None
        self.rotulo_no_ar = "—"
        self.lugar_ativo: Lugar | None = None
        self.eventos: deque[str] = deque(maxlen=40)

        self._candidato: Lugar | None = None
        self._candidato_desde = 0.0
        self._ultimo_corte = -1e9
        self._ultima_voz = -1e9
        self._lock = asyncio.Lock()

    # ----------------------------------------------------------- utilidades
    def _evento(self, texto: str) -> None:
        linha = f"{datetime.now():%H:%M:%S} {texto}"
        self.eventos.appendleft(linha)
        log.info(texto)

    def _mais_alto(self, niveis: dict[int, float]) -> Lugar | None:
        melhor, melhor_db = None, self.limiar_db
        for lugar in self.lugares:
            db = niveis.get(lugar.canal, -120.0)
            if db >= melhor_db:
                melhor, melhor_db = lugar, db
        return melhor

    def _camera_no_ar(self) -> str | None:
        return self.no_ar.camera if self.no_ar else None

    def _precisa_mover(self, plano: Plano) -> bool:
        if plano.camera is None or plano.preset is None:
            return False
        return self.cameras[plano.camera].ultimo_preset != plano.preset

    def _escolher_plano(self, lugar: Lugar) -> Plano:
        # 1) já está no ar exatamente esse plano
        for p in lugar.planos:
            if p == self.no_ar:
                return p
        # 2) um plano com câmera já posicionada e fora do ar (corte instantâneo)
        cam_ar = self._camera_no_ar()
        for p in lugar.planos:
            if p.camera != cam_ar and not self._precisa_mover(p):
                return p
        # 3) qualquer plano cuja câmera esteja fora do ar
        for p in lugar.planos:
            if p.camera is None or p.camera != cam_ar:
                return p
        # 4) sem opção: usa o primeiro (vai precisar sair pelo plano geral)
        return lugar.planos[0]

    # ------------------------------------------------------------- execução
    async def _posicionar(self, plano: Plano) -> None:
        if self._precisa_mover(plano):
            cam = self.cameras[plano.camera]
            await asyncio.to_thread(cam.chamar_preset, plano.preset)
            await asyncio.sleep(self.assentamento_s)

    async def _cortar(self, plano: Plano, rotulo: str) -> None:
        await asyncio.to_thread(self.obs.trocar_cena, plano.cena)
        self.no_ar = plano
        self.rotulo_no_ar = rotulo
        self._ultimo_corte = time.monotonic()
        cam = f" | {plano.camera} preset {plano.preset}" if plano.camera else ""
        self._evento(f"NO AR: {rotulo} (cena '{plano.cena}'{cam})")

    async def _levar_ao_ar(self, plano: Plano, rotulo: str) -> None:
        if plano == self.no_ar:
            self.rotulo_no_ar = rotulo
            return
        if self._precisa_mover(plano) and plano.camera == self._camera_no_ar():
            # A câmera que precisa se mover está no ar: sai pelo plano geral antes.
            if self.plano_geral.camera != plano.camera and self.no_ar != self.plano_geral:
                await self._posicionar(self.plano_geral)
                await self._cortar(self.plano_geral, "Plano geral (transição)")
            else:
                self._evento(f"Aviso: {plano.camera} vai se mover no ar (sem câmera livre)")
        await self._posicionar(plano)
        await self._cortar(plano, rotulo)

    # ------------------------------------------------------------ ações
    async def ir_para_lugar(self, nome: str, motivo: str = "manual") -> None:
        lugar = self.lugar_por_nome[nome]
        async with self._lock:
            plano = self._escolher_plano(lugar)
            await self._levar_ao_ar(plano, lugar.nome)
            self.lugar_ativo = lugar
            if motivo != "auto":
                self._evento(f"({motivo}) {lugar.nome}")

    async def ir_para_geral(self, motivo: str = "manual") -> None:
        async with self._lock:
            await self._levar_ao_ar(self.plano_geral, "Plano geral")
            self.lugar_ativo = None

    def definir_modo(self, modo: str) -> None:
        if modo not in ("auto", "manual"):
            raise ValueError("modo deve ser 'auto' ou 'manual'")
        if modo != self.modo:
            self.modo = modo
            self._evento(f"Modo {modo.upper()}")

    # ------------------------------------------------------------ laço
    async def tick(self) -> None:
        agora = time.monotonic()
        lugar = self._mais_alto(self.medidor.leitura())
        if lugar is not None:
            self._ultima_voz = agora
        if lugar is not self._candidato:
            self._candidato = lugar
            self._candidato_desde = agora

        if self.modo != "auto" or self._lock.locked():
            return

        desde_corte = agora - self._ultimo_corte
        if lugar is not None:
            falou_o_bastante = agora - self._candidato_desde >= self.tempo_fala_s
            if lugar is not self.lugar_ativo and falou_o_bastante and desde_corte >= self.tempo_plano_s:
                await self.ir_para_lugar(lugar.nome, motivo="auto")
        elif (
            self.lugar_ativo is not None
            and agora - self._ultima_voz >= self.silencio_geral_s
            and desde_corte >= self.tempo_plano_s
        ):
            await self.ir_para_geral(motivo="auto")

    async def rodar(self, intervalo: float = 0.1) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - o diretor nunca pode morrer no meio da sessão
                log.exception("Erro no diretor (seguindo em frente)")
            await asyncio.sleep(intervalo)

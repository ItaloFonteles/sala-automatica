"""Controle do OBS Studio via obs-websocket (v5, já vem no OBS 28+).

No OBS: Ferramentas > Configurações do servidor WebSocket > Ativar.
"""

from __future__ import annotations

import logging

log = logging.getLogger("obs")


class ObsControle:
    def __init__(self, host: str = "localhost", porta: int = 4455, senha: str = "", simulacao: bool = False) -> None:
        self.host = host
        self.porta = porta
        self.senha = senha
        self.simulacao = simulacao
        self.cliente = None
        self.cena_atual: str | None = None
        self.transmitindo = False
        self.gravando = False
        self.ultimo_erro: str | None = None

    @property
    def conectado(self) -> bool:
        return self.simulacao or self.cliente is not None

    def conectar(self) -> bool:
        if self.simulacao:
            log.info("[SIM] OBS simulado")
            return True
        try:
            import obsws_python as obsws  # import tardio: só precisa no modo real

            self.cliente = obsws.ReqClient(host=self.host, port=self.porta, password=self.senha, timeout=3)
            self.ultimo_erro = None
            log.info("Conectado ao OBS em %s:%s", self.host, self.porta)
            return True
        except Exception as e:  # noqa: BLE001 - qualquer falha de conexão
            self.cliente = None
            self.ultimo_erro = str(e)
            log.error("Não conectou ao OBS (%s:%s): %s", self.host, self.porta, e)
            return False

    def _chamar(self, nome: str, *args) -> bool:
        if self.simulacao:
            log.info("[SIM] OBS %s %s", nome, args)
            return True
        if self.cliente is None and not self.conectar():
            return False
        try:
            getattr(self.cliente, nome)(*args)
            return True
        except Exception as e:  # noqa: BLE001
            self.ultimo_erro = str(e)
            log.error("OBS falhou em %s: %s", nome, e)
            self.cliente = None  # força reconexão na próxima chamada
            return False

    def trocar_cena(self, cena: str) -> bool:
        ok = self._chamar("set_current_program_scene", cena)
        if ok:
            self.cena_atual = cena
        return ok

    def iniciar_sessao(self, gravar: bool = True, transmitir: bool = True) -> bool:
        ok = True
        if gravar and not self.gravando:
            self.gravando = self._chamar("start_record")
            ok &= self.gravando
        if transmitir and not self.transmitindo:
            self.transmitindo = self._chamar("start_stream")
            ok &= self.transmitindo
        return ok

    def encerrar_sessao(self) -> bool:
        ok = True
        if self.transmitindo:
            ok &= self._chamar("stop_stream")
            self.transmitindo = False
        if self.gravando:
            ok &= self._chamar("stop_record")
            self.gravando = False
        return ok

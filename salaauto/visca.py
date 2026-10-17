"""Controle de câmeras PTZ via VISCA over IP.

Suporta três "sabores" de VISCA em rede, porque cada fabricante faz de um jeito:

- sony_udp : VISCA over IP da Sony (porta 52381, com cabeçalho de 8 bytes).
             Usado por Sony, Avonic, muitas chinesas "Sony compatible".
- raw_udp  : comandos VISCA puros em UDP (ex.: PTZOptics porta 1259).
- raw_tcp  : comandos VISCA puros em TCP (ex.: PTZOptics porta 5678, Lumens, Minrray).

Se a câmera não responder, troque o protocolo/porta no config.toml.
"""

from __future__ import annotations

import logging
import socket
import threading

log = logging.getLogger("visca")

PROTOCOLOS = ("sony_udp", "raw_udp", "raw_tcp")


class ViscaCamera:
    def __init__(
        self,
        nome: str,
        ip: str,
        porta: int = 52381,
        protocolo: str = "sony_udp",
        endereco: int = 1,
        timeout: float = 1.0,
        simulacao: bool = False,
    ) -> None:
        if protocolo not in PROTOCOLOS:
            raise ValueError(f"Câmera '{nome}': protocolo '{protocolo}' inválido. Use um de {PROTOCOLOS}.")
        self.nome = nome
        self.ip = ip
        self.porta = porta
        self.protocolo = protocolo
        self.endereco = endereco
        self.timeout = timeout
        self.simulacao = simulacao
        self.ultimo_preset: int | None = None
        self.ultimo_erro: str | None = None
        self._seq = 0
        self._lock = threading.Lock()
        self._seq_resetada = False

    # ------------------------------------------------------------------ envio
    def _montar(self, *corpo: int) -> bytes:
        return bytes([0x80 | self.endereco, *corpo, 0xFF])

    def _enviar(self, payload: bytes) -> bool:
        if self.simulacao:
            log.info("[SIM] %s <- %s", self.nome, payload.hex(" "))
            return True
        with self._lock:
            try:
                if self.protocolo == "sony_udp":
                    self._enviar_sony(payload)
                elif self.protocolo == "raw_udp":
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.sendto(payload, (self.ip, self.porta))
                else:
                    with socket.create_connection((self.ip, self.porta), timeout=self.timeout) as s:
                        s.sendall(payload)
                        try:
                            s.recv(16)  # ACK da câmera (ignorado)
                        except socket.timeout:
                            pass
                self.ultimo_erro = None
                return True
            except OSError as e:
                self.ultimo_erro = str(e)
                log.error("Câmera %s (%s:%s) não respondeu: %s", self.nome, self.ip, self.porta, e)
                return False

    def _enviar_sony(self, payload: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            if not self._seq_resetada:
                # Mensagem de controle "reset sequence number"
                s.sendto(bytes([0x02, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0x01]), (self.ip, self.porta))
                self._seq = 0
                self._seq_resetada = True
            self._seq = (self._seq + 1) & 0xFFFFFFFF
            cabecalho = bytes([0x01, 0x00]) + len(payload).to_bytes(2, "big") + self._seq.to_bytes(4, "big")
            s.sendto(cabecalho + payload, (self.ip, self.porta))

    # -------------------------------------------------------------- comandos
    def chamar_preset(self, numero: int) -> bool:
        """Move a câmera para um preset salvo."""
        ok = self._enviar(self._montar(0x01, 0x04, 0x3F, 0x02, numero & 0xFF))
        if ok:
            self.ultimo_preset = numero
        return ok

    def salvar_preset(self, numero: int) -> bool:
        """Grava a posição atual da câmera no preset indicado."""
        ok = self._enviar(self._montar(0x01, 0x04, 0x3F, 0x01, numero & 0xFF))
        if ok:
            self.ultimo_preset = numero
        return ok

    def mover(self, pan: int, tilt: int, velocidade: int = 8) -> bool:
        """pan: -1 esquerda, 0 parado, 1 direita | tilt: -1 baixo, 0 parado, 1 cima."""
        vp = max(1, min(0x18, velocidade))
        vt = max(1, min(0x14, velocidade))
        dir_pan = {-1: 0x01, 0: 0x03, 1: 0x02}[max(-1, min(1, pan))]
        dir_tilt = {1: 0x01, 0: 0x03, -1: 0x02}[max(-1, min(1, tilt))]
        if pan or tilt:
            self.ultimo_preset = None  # saiu do preset
        return self._enviar(self._montar(0x01, 0x06, 0x01, vp, vt, dir_pan, dir_tilt))

    def parar(self) -> bool:
        return self.mover(0, 0)

    def zoom(self, direcao: int, velocidade: int = 3) -> bool:
        """direcao: 1 aproxima (tele), -1 afasta (wide), 0 para."""
        v = max(0, min(7, velocidade))
        if direcao > 0:
            arg = 0x20 | v
        elif direcao < 0:
            arg = 0x30 | v
        else:
            arg = 0x00
        if direcao:
            self.ultimo_preset = None
        return self._enviar(self._montar(0x01, 0x04, 0x07, arg))

    def home(self) -> bool:
        self.ultimo_preset = None
        return self._enviar(self._montar(0x01, 0x06, 0x04))

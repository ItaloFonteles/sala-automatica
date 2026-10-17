"""Medição de nível de áudio por canal (quem está falando).

Real: uma interface de áudio multicanal (ex.: mesa com saída USB multicanal,
Behringer UMC404, Focusrite, Dante Virtual Soundcard). Cada microfone = 1 canal.
Simulado: o painel web "faz" alguém falar.
"""

from __future__ import annotations

import logging
import random
import threading

log = logging.getLogger("audio")

SILENCIO_DB = -120.0


class MedidorNivel:
    def __init__(self, canais: int) -> None:
        self.canais = canais
        self._niveis = {c: SILENCIO_DB for c in range(1, canais + 1)}
        self._lock = threading.Lock()

    def leitura(self) -> dict[int, float]:
        with self._lock:
            return dict(self._niveis)

    def _atualizar(self, niveis: dict[int, float]) -> None:
        with self._lock:
            self._niveis.update(niveis)

    def iniciar(self) -> None: ...

    def parar(self) -> None: ...


class MedidorSimulado(MedidorNivel):
    def __init__(self, canais: int) -> None:
        super().__init__(canais)
        self.falando: int | None = None

    def definir_quem_fala(self, canal: int | None) -> None:
        self.falando = canal
        log.info("[SIM] falando agora: %s", f"canal {canal}" if canal else "ninguém")

    def leitura(self) -> dict[int, float]:
        niveis = {}
        for c in range(1, self.canais + 1):
            if c == self.falando:
                niveis[c] = -18.0 + random.uniform(-4, 4)
            else:
                niveis[c] = -70.0 + random.uniform(-5, 5)
        return niveis


class MedidorPlacaDeSom(MedidorNivel):
    def __init__(self, canais: int, dispositivo=None, taxa: int = 48000, bloco: int = 2048) -> None:
        super().__init__(canais)
        self.dispositivo = dispositivo
        self.taxa = taxa
        self.bloco = bloco
        self._stream = None

    def iniciar(self) -> None:
        import numpy as np
        import sounddevice as sd

        def callback(indata, frames, tempo, status):  # roda numa thread do driver
            if status:
                log.debug("status áudio: %s", status)
            rms = np.sqrt(np.mean(np.square(indata, dtype=np.float64), axis=0))
            db = 20 * np.log10(np.maximum(rms, 1e-6))
            self._atualizar({i + 1: float(v) for i, v in enumerate(db)})

        self._stream = sd.InputStream(
            device=self.dispositivo,
            channels=self.canais,
            samplerate=self.taxa,
            blocksize=self.bloco,
            dtype="float32",
            callback=callback,
        )
        self._stream.start()
        log.info("Lendo %s canais de áudio do dispositivo %s", self.canais, self.dispositivo)

    def parar(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def listar_dispositivos() -> str:
    import sounddevice as sd

    return str(sd.query_devices())

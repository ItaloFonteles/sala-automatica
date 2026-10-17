"""Teste automático do modo simulação. Rode: python tests/teste_simulacao.py"""
import json, sys, time, threading, socket, re, urllib.request, urllib.error, pathlib, tempfile
RAIZ = str(pathlib.Path(__file__).resolve().parent.parent)
sys.path.insert(0, RAIZ)

# Garante que nada fora da biblioteca padrão é importado
import builtins
proibidos = ("fastapi", "uvicorn", "yaml", "pydantic", "numpy", "sounddevice", "obsws_python")
_imp = builtins.__import__
def guard(name, *a, **k):
    if name.split(".")[0] in proibidos:
        raise ImportError(f"importou dependência externa: {name}")
    return _imp(name, *a, **k)
builtins.__import__ = guard

from salaauto.servidor import Aplicacao, servir

src = pathlib.Path(RAIZ, "config.toml").read_text(encoding="utf-8")
for k, v in dict(tempo_minimo_fala_s=0.3, tempo_minimo_plano_s=0.5, silencio_para_geral_s=1.0, tempo_assentamento_s=0.2).items():
    src = re.sub(rf"^{k} = [\d.]+", f"{k} = {v}", src, flags=re.M)
cfg = pathlib.Path(tempfile.gettempdir(), "sala_teste.toml"); cfg.write_text(src, encoding="utf-8")

app = Aplicacao(str(cfg), forcar_simulacao=True); app.iniciar()
srv = servir(app, 0, "127.0.0.1"); porta = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{porta}"

def get(p):
    return json.loads(urllib.request.urlopen(B + p).read())
def post(p, body=None):
    req = urllib.request.Request(B + p, data=json.dumps(body or {}).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = urllib.request.urlopen(req); return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

html = urllib.request.urlopen(B + "/").read().decode(); assert "Sala Automática" in html
time.sleep(0.3); e = get("/api/estado"); print("inicio:", e["no_ar"]); assert e["no_ar"] == "Plano geral"
post("/api/simular/fala", {"canal": 1}); time.sleep(1.2); e = get("/api/estado"); print("fala1:", e["no_ar"], e["cena"]); assert (e["no_ar"], e["cena"]) == ("Presidente", "Cam2")
post("/api/simular/fala", {"canal": 3}); time.sleep(1.2); e = get("/api/estado"); print("fala3:", e["no_ar"], e["cena"]); assert (e["no_ar"], e["cena"]) == ("Vereador A", "Cam1")
post("/api/simular/fala", {"canal": 4}); time.sleep(1.2); e = get("/api/estado"); print("fala4:", e["no_ar"], e["cena"]); assert (e["no_ar"], e["cena"]) == ("Vereador B", "Cam2")
post("/api/simular/fala", {"canal": None}); time.sleep(2.0); e = get("/api/estado"); print("silencio:", e["no_ar"]); assert e["no_ar"] == "Plano geral"
s, r = post("/api/lugar/Secret%C3%A1rio"); print("manual acento:", s, r); assert s == 200 and get("/api/estado")["modo"] == "manual"
post("/api/simular/fala", {"canal": 1}); time.sleep(1.0); assert get("/api/estado")["no_ar"] == "Secretário"
post("/api/modo", {"modo": "auto"}); time.sleep(1.2); assert get("/api/estado")["no_ar"] == "Presidente"
assert post("/api/camera/cam1/preset/3/salvar")[1]["ok"]
assert post("/api/camera/cam1/mover", {"pan": 1})[1]["ok"]
assert post("/api/camera/cam2/zoom", {"direcao": -1})[1]["ok"]
assert post("/api/sessao/iniciar")[1]["ok"]; e = get("/api/estado"); assert e["obs"]["gravando"] and e["obs"]["transmitindo"]
assert post("/api/sessao/encerrar")[1]["ok"]
assert post("/api/camera/xx/mover")[0] == 404
assert post("/api/modo", {"modo": "foo"})[0] == 400
assert post("/api/nada")[0] == 404
print("\n".join(get("/api/estado")["eventos"][:6]))
srv.shutdown(); app.parar()
print("TUDO OK - sem dependências externas")

# --- Regressão: voltar ao geral com a cam1 no ar nunca pode mover a cam1 no ar
app = Aplicacao(str(cfg), forcar_simulacao=True); app.iniciar()
srv = servir(app, 0, "127.0.0.1"); B = f"http://127.0.0.1:{srv.server_address[1]}"
threading.Thread(target=srv.serve_forever, daemon=True).start()
movidos_no_ar = []
orig = {n: c.chamar_preset for n, c in app.cameras.items()}
for n, c in app.cameras.items():
    def espia(p, n=n):
        if app.diretor._camera_no_ar() == n:
            movidos_no_ar.append((n, p))
        return orig[n](p)
    c.chamar_preset = espia
for canal in (1, 3, None, 4, None, 6, 2, None):
    post("/api/simular/fala", {"canal": canal}); time.sleep(2.2 if canal else 2.0)
ev = get("/api/estado")["eventos"]
print("\n".join(reversed(ev[:12])))
assert not any("Aviso" in x for x in ev), "apareceu aviso de movimento no ar"
assert not movidos_no_ar, f"câmera movida no ar: {movidos_no_ar}"
srv.shutdown(); app.parar()
print("REGRESSÃO OK - nenhuma câmera se moveu no ar")

# --- Voz real oscila entre as sílabas: a troca precisa acontecer mesmo assim
import asyncio
from salaauto.audio import MedidorNivel
from salaauto.diretor import Diretor, Lugar, Plano
from salaauto.obs import ObsControle
from salaauto.visca import ViscaCamera


class VozSilabada(MedidorNivel):
    """Canal 1 alterna 0,15 s de voz (-28 dB) e 0,15 s de pausa (-55 dB)."""

    def __init__(self):
        super().__init__(1)
        self.inicio = time.monotonic()
        self.falando = True

    def leitura(self):
        if not self.falando:
            return {1: -55.0}
        fase = int((time.monotonic() - self.inicio) / 0.15) % 2
        return {1: -28.0 if fase == 0 else -55.0}


async def voz_silabada():
    cams = {n: ViscaCamera(n, "0.0.0.0", simulacao=True) for n in ("cam1", "cam2")}
    med = VozSilabada()
    d = Diretor(
        cams, ObsControle(simulacao=True), med,
        [Lugar("Presidente", 1, [Plano("Cam2", "cam2", 1)])],
        [Plano("Geral", "cam1", 1), Plano("Geral 2", "cam2", 8)],
        {"limiar_db": -40, "tempo_minimo_fala_s": 1.0, "tempo_minimo_plano_s": 0.5,
         "silencio_para_geral_s": 1.0, "tempo_assentamento_s": 0.1, "hold_s": 0.6},
    )
    await d.ir_para_geral("início")
    tarefa = asyncio.create_task(d.rodar())
    await asyncio.sleep(2.5)
    falou = d.rotulo_no_ar
    med.falando = False
    await asyncio.sleep(2.5)
    voltou = d.rotulo_no_ar
    tarefa.cancel()
    return falou, voltou


falou, voltou = asyncio.run(voz_silabada())
print("voz silabada ->", falou, "| silêncio ->", voltou)
assert falou == "Presidente", "voz com pausas entre sílabas não levou ao ar"
assert voltou == "Plano geral"
print("VOZ REAL OK - pausas entre sílabas não atrapalham")

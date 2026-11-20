#!/usr/bin/env python3
"""
Bitácora (versión web local) - registro diario de tareas y notas, con análisis de tu ritmo.
-----------------------------------------------------------------------------------------
Interfaz HTML/CSS/JS dentro de una ventana de escritorio (pywebview).
Comparte la base de datos con la versión Tkinter (bitacora.db).

Instalar:   pip install pywebview
Ejecutar:   python bitacora_web.py

Atajos: Ctrl+N nueva tarea · Ctrl+1/2/3 cambiar de sección · Ctrl+Enter guardar nota
"""
import os
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta

DB = os.environ.get("BITACORA_DB", "bitacora.db")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
CATEGORIAS_BASE = ["trabajo", "estudio", "personal", "salud", "hogar", "general"]


# ---------------------------------------------------------------- base de datos
def conectar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS tareas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            titulo TEXT NOT NULL,
            categoria TEXT DEFAULT 'general',
            prioridad INTEGER DEFAULT 2,
            min_estimados INTEGER,
            min_reales INTEGER,
            estado TEXT DEFAULT 'pendiente',
            completada_en TEXT
        );
        CREATE TABLE IF NOT EXISTS bitacora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            energia INTEGER,
            animo INTEGER,
            nota TEXT
        );
        """
    )
    return con


def calcular_analisis(con, desde, hasta):
    tareas = con.execute(
        "SELECT * FROM tareas WHERE fecha BETWEEN ? AND ?", (desde, hasta)).fetchall()
    notas = con.execute(
        "SELECT * FROM bitacora WHERE fecha BETWEEN ? AND ?", (desde, hasta)).fetchall()
    r = {"tareas": tareas, "notas": notas}
    if not tareas:
        return r

    hechas = [t for t in tareas if t["estado"] == "hecha"]
    r["total"], r["hechas"] = len(tareas), len(hechas)
    r["minutos"] = sum(t["min_reales"] or 0 for t in hechas)

    dias = defaultdict(lambda: [0, 0])
    for t in tareas:
        dias[t["fecha"]][1] += 1
        dias[t["fecha"]][0] += t["estado"] == "hecha"
    r["dias"] = {d: dias[d] for d in sorted(dias)}

    racha = mejor = 0
    for d in r["dias"]:
        h, tot = r["dias"][d]
        racha = racha + 1 if h / tot >= 0.8 else 0
        mejor = max(mejor, racha)
    r["racha"] = mejor

    cats = defaultdict(lambda: [0, 0, 0])
    for t in tareas:
        c = cats[t["categoria"]]
        c[1] += 1
        if t["estado"] == "hecha":
            c[0] += 1
            c[2] += t["min_reales"] or 0
    r["categorias"] = dict(sorted(cats.items(), key=lambda x: (-x[1][2], -x[1][1])))

    pares = [(t["min_estimados"], t["min_reales"]) for t in hechas
             if t["min_estimados"] and t["min_reales"]]
    r["ratio"] = (sum(b for _, b in pares) / sum(a for a, _ in pares)) if pares else None

    por_hora = defaultdict(int)
    for t in hechas:
        if t["completada_en"]:
            por_hora[int(t["completada_en"][11:13])] += 1
    r["horas"] = sorted(por_hora.items(), key=lambda x: -x[1])[:3]

    franjas = defaultdict(list)
    for n in notas:
        if n["energia"]:
            h = int(n["hora"][:2])
            franjas["la mañana" if h < 12 else "la tarde" if h < 19 else "la noche"].append(n["energia"])
    r["energia"] = {k: (sum(v) / len(v), len(v)) for k, v in franjas.items()}
    return r


def lecturas(r):
    out = []
    if r["horas"]:
        hs = [f"{h:02d}:00" for h, _ in r["horas"][:2]]
        out.append("Terminas más tareas cerca de las " + " y las ".join(hs) + ".")
    if r["energia"]:
        k, (v, _) = max(r["energia"].items(), key=lambda x: x[1][0])
        out.append(f"Tu energía es más alta en {k} ({v:.1f}/5). Reserva ahí lo difícil.")
    if r["ratio"] and r["ratio"] > 1.1:
        out.append(f"Tardas {r['ratio']:.1f}× lo que estimas: agrega margen a tus tiempos.")
    elif r["ratio"] and r["ratio"] < 0.9:
        out.append("Terminas antes de lo estimado: puedes planear un poco más.")
    p1 = [t for t in r["tareas"] if t["prioridad"] == 1 and t["estado"] != "hecha"]
    if p1:
        out.append(f"Tienes {len(p1)} tarea(s) de prioridad alta sin completar.")
    if r["total"] / max(len(r["dias"]), 1) > 7:
        out.append("Planeas más de 7 tareas por día en promedio; considera reducir la carga.")
    peor = min(r["categorias"].items(), key=lambda x: x[1][0] / x[1][1])
    if peor[1][0] < peor[1][1]:
        out.append(f"«{peor[0]}» es donde menos cumples ({peor[1][0]}/{peor[1][1]}).")
    return out or ["Registra unos días más y aquí aparecerán patrones."]


def porcentajes_por_dia(con):
    filas = con.execute(
        "SELECT fecha, SUM(estado='hecha') h, COUNT(*) n FROM tareas GROUP BY fecha").fetchall()
    return {r["fecha"]: r["h"] / r["n"] for r in filas}


def racha_actual(pct):
    dia = date.today()
    if pct.get(dia.isoformat(), 0) < 0.8:
        dia -= timedelta(days=1)
    n = 0
    while pct.get(dia.isoformat(), 0) >= 0.8:
        n += 1
        dia -= timedelta(days=1)
    return n


# ---------------------------------------------------------------- API para la interfaz
class Api:
    """Cada método se llama desde JavaScript: await pywebview.api.metodo(...)."""

    def dia(self, fecha):
        con = conectar()
        try:
            filas = con.execute(
                "SELECT * FROM tareas WHERE fecha=? ORDER BY prioridad, id", (fecha,)).fetchall()
            previos = con.execute(
                "SELECT COUNT(*) FROM tareas WHERE estado='pendiente' AND fecha<?",
                (fecha,)).fetchone()[0]
            usadas = {r[0] for r in con.execute("SELECT DISTINCT categoria FROM tareas") if r[0]}
            return {"tareas": [dict(r) for r in filas], "previos": previos,
                    "categorias": sorted(set(CATEGORIAS_BASE) | usadas)}
        finally:
            con.close()

    def agregar_tarea(self, fecha, titulo, categoria, prioridad, min_est):
        con = conectar()
        try:
            cur = con.execute(
                "INSERT INTO tareas (fecha, titulo, categoria, prioridad, min_estimados) "
                "VALUES (?,?,?,?,?)",
                (fecha, titulo, categoria, int(prioridad), int(min_est) if min_est else None))
            con.commit()
            return cur.lastrowid
        finally:
            con.close()

    def alternar(self, tarea_id, min_reales=None):
        """Si estaba hecha la vuelve pendiente; si no, la marca como hecha."""
        con = conectar()
        try:
            t = con.execute("SELECT estado FROM tareas WHERE id=?", (tarea_id,)).fetchone()
            if not t:
                return False
            if t["estado"] == "hecha":
                con.execute("UPDATE tareas SET estado='pendiente', completada_en=NULL, "
                            "min_reales=NULL WHERE id=?", (tarea_id,))
            else:
                con.execute("UPDATE tareas SET estado='hecha', min_reales=?, completada_en=? "
                            "WHERE id=?",
                            (int(min_reales) if min_reales else None,
                             datetime.now().isoformat(timespec="minutes"), tarea_id))
            con.commit()
            return True
        finally:
            con.close()

    def editar_tarea(self, tarea_id, titulo):
        con = conectar()
        try:
            con.execute("UPDATE tareas SET titulo=? WHERE id=?", (titulo, tarea_id))
            con.commit()
            return True
        finally:
            con.close()

    def eliminar_tarea(self, tarea_id):
        con = conectar()
        try:
            con.execute("DELETE FROM tareas WHERE id=?", (tarea_id,))
            con.commit()
            return True
        finally:
            con.close()

    def traer_pendientes(self, fecha):
        con = conectar()
        try:
            con.execute("UPDATE tareas SET fecha=? WHERE estado='pendiente' AND fecha<?",
                        (fecha, fecha))
            con.commit()
            return True
        finally:
            con.close()

    def notas(self, fecha):
        con = conectar()
        try:
            filas = con.execute("SELECT * FROM bitacora WHERE fecha=? ORDER BY hora, id",
                                (fecha,)).fetchall()
            return [dict(r) for r in filas]
        finally:
            con.close()

    def agregar_nota(self, fecha, energia, animo, texto):
        con = conectar()
        try:
            con.execute(
                "INSERT INTO bitacora (fecha, hora, energia, animo, nota) VALUES (?,?,?,?,?)",
                (fecha, datetime.now().strftime("%H:%M"), energia, animo, texto))
            con.commit()
            return True
        finally:
            con.close()

    def eliminar_nota(self, nota_id):
        con = conectar()
        try:
            con.execute("DELETE FROM bitacora WHERE id=?", (nota_id,))
            con.commit()
            return True
        finally:
            con.close()

    def lado(self):
        con = conectar()
        try:
            pct = porcentajes_por_dia(con)
        finally:
            con.close()
        hoy = date.today()
        semana = []
        for i in range(7):
            d = hoy - timedelta(days=6 - i)
            semana.append({"l": DIAS[d.weekday()][0].upper(), "p": pct.get(d.isoformat()),
                           "hoy": d == hoy})
        return {"racha": racha_actual(pct), "semana": semana}

    def analisis(self, periodo):
        hoy = date.today()
        desde, hasta = "0000-01-01", "9999-12-31"
        if periodo == "7 días":
            desde, hasta = (hoy - timedelta(days=6)).isoformat(), hoy.isoformat()
        elif periodo == "30 días":
            desde, hasta = (hoy - timedelta(days=29)).isoformat(), hoy.isoformat()
        elif periodo == "Este mes":
            desde, hasta = hoy.replace(day=1).isoformat(), hoy.isoformat()
        con = conectar()
        try:
            r = calcular_analisis(con, desde, hasta)
        finally:
            con.close()
        if not r["tareas"]:
            return {"vacio": True}
        return {
            "total": r["total"], "hechas": r["hechas"], "minutos": r["minutos"],
            "racha": r["racha"], "ratio": r["ratio"],
            "dias": [{"fecha": d, "h": v[0], "n": v[1]} for d, v in list(r["dias"].items())[-45:]],
            "categorias": [{"nombre": k, "h": v[0], "n": v[1], "min": v[2]}
                           for k, v in list(r["categorias"].items())[:8]],
            "lecturas": lecturas(r),
        }


# ---------------------------------------------------------------- interfaz
HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bitácora</title>
<style>
:root{
  --bg:#131211;--panel:#181716;--surf:#1e1d1b;--surf2:#292723;--line:#34312c;
  --text:#ece6da;--muted:#9a9386;--faint:#645f56;
  --accent:#e9b44c;--accent-hi:#f3c872;--accent-dk:#1b1408;
  --ok:#8fbf8a;--bad:#e2795e;--p3:#7d8ea0;
  --ease:cubic-bezier(.2,.8,.2,1);
  --sans:"Inter","Segoe UI Variable Text","Segoe UI","SF Pro Text","Helvetica Neue",system-ui,sans-serif;
  --serif:Georgia,"Source Serif 4",Cambria,"Iowan Old Style",serif;
  color-scheme:dark;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--text);font:14px/1.45 var(--sans);overflow:hidden;user-select:none;-webkit-font-smoothing:antialiased}
input,textarea{user-select:text;font-family:inherit}
button{font-family:inherit}

/* ---- luces de fondo ---- */
.luz{position:fixed;border-radius:50%;pointer-events:none;z-index:0;will-change:transform;animation:deriva 20s ease-in-out infinite alternate}
.l1{width:600px;height:600px;top:-180px;left:-140px;background:radial-gradient(circle,rgba(233,180,76,.30),transparent 70%)}
.l2{width:680px;height:680px;bottom:-260px;right:-160px;background:radial-gradient(circle,rgba(125,142,160,.24),transparent 70%);animation-delay:-8s}
.l3{width:420px;height:420px;top:38%;left:42%;background:radial-gradient(circle,rgba(226,121,94,.12),transparent 70%);animation-delay:-14s;animation-duration:27s}
@keyframes deriva{to{transform:translate(90px,60px) scale(1.15)}}

/* ---- glass ---- */
.glass{position:relative;background:rgba(255,255,255,.045);border:1px solid rgba(255,255,255,.09);
  backdrop-filter:blur(18px) saturate(140%);-webkit-backdrop-filter:blur(18px) saturate(140%);
  box-shadow:0 8px 32px rgba(0,0,0,.30);border-radius:18px;overflow:hidden;
  transition:transform .28s var(--ease),box-shadow .28s var(--ease),border-color .28s var(--ease)}
.glass::before{content:"";position:absolute;inset:0;pointer-events:none;opacity:0;transition:opacity .35s;
  background:radial-gradient(280px circle at var(--mx,50%) var(--my,0%),rgba(233,180,76,.13),transparent 60%)}
.glass:hover::before{opacity:1}
.card:hover{transform:translateY(-4px);border-color:rgba(233,180,76,.40);box-shadow:0 16px 40px rgba(0,0,0,.42),0 0 28px rgba(233,180,76,.12)}

.app{position:relative;z-index:1;display:flex;height:100vh}
main{flex:1;min-width:0;position:relative}

/* ---- barra lateral ---- */
.side{width:224px;flex:none;display:flex;flex-direction:column;border-radius:0;border-width:0 1px 0 0;box-shadow:none}
.marca{display:flex;align-items:center;gap:11px;padding:30px 24px 28px;font:600 18px var(--serif)}
.marca i{width:10px;height:10px;background:var(--accent);box-shadow:0 0 14px rgba(233,180,76,.7);animation:pulso 3.2s ease-in-out infinite}
@keyframes pulso{50%{box-shadow:0 0 22px rgba(233,180,76,1);transform:scale(1.15)}}
#nav a{position:relative;display:block;padding:11px 24px;color:var(--muted);font-size:14px;cursor:pointer;transition:color .2s,background .3s,padding-left .3s var(--ease)}
#nav a::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--accent);transform:scaleY(0);transition:transform .35s var(--ease)}
#nav a:hover{color:var(--text);padding-left:28px}
#nav a.on{color:var(--text);background:rgba(255,255,255,.05);padding-left:24px}
#nav a.on::before{transform:scaleY(1)}
#lado{margin-top:auto;padding:26px 24px}
.kicker{font-size:10px;font-weight:700;letter-spacing:.14em;color:var(--faint);text-transform:uppercase}
.racha{display:flex;align-items:flex-end;gap:8px;margin:2px 0 12px}
.racha b{font:400 30px/1 var(--serif);color:var(--accent)}
.racha b.cero{color:var(--faint)}
.racha span{font-size:11px;color:var(--muted);padding-bottom:3px}
.sem{display:flex;justify-content:space-between;width:166px}
.dia{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:9px;color:var(--faint)}
.dia.hoy{color:var(--text)}
.dia i{width:14px;height:14px;border-radius:50%;background:var(--c);animation:aparece .5s var(--ease) backwards;animation-delay:calc(var(--i)*60ms)}
@keyframes aparece{from{opacity:0;transform:scale(.3)}}

/* ---- páginas ---- */
.pag{position:absolute;inset:0;display:none;flex-direction:column;padding:32px 32px 0 38px}
.pag.on{display:flex;animation:pag .45s var(--ease)}
@keyframes pag{from{opacity:0;transform:translateY(14px)}}
.cab{display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:20px;padding-right:6px}
.cab .kicker{color:var(--accent)}
h1{font:400 34px/1.15 var(--serif);margin:2px 0}
.sub{color:var(--muted);font-size:14px;min-height:20px}
.navf{display:flex;gap:6px;margin-top:16px}
.scroll{flex:1;overflow-y:auto;padding:0 12px 22px 0}
.scroll::-webkit-scrollbar{width:4px}
.scroll::-webkit-scrollbar-thumb{background:var(--line);border-radius:4px}
.vacio{font:italic 17px/1.5 var(--serif);color:var(--faint);padding:40px 6px}

/* ---- botones ---- */
.btn{border:0;cursor:pointer;border-radius:10px;padding:8px 14px;font-size:12px;font-weight:600;transition:background .2s,color .2s,transform .15s var(--ease),box-shadow .2s}
.btn:active{transform:scale(.95)}
.btn.primary{background:var(--accent);color:var(--accent-dk)}
.btn.primary:hover{background:var(--accent-hi);box-shadow:0 0 20px rgba(233,180,76,.35)}
.btn.chip{background:rgba(255,255,255,.07);color:var(--text)}
.btn.chip:hover{background:rgba(255,255,255,.14)}
.btn.ghost{background:transparent;color:var(--muted)}
.btn.ghost:hover{background:rgba(255,255,255,.07);color:var(--text)}
.btn.danger{background:var(--bad);color:#1f0e09}
.btn.danger:hover{background:#ec8d75}
.seg{display:flex;gap:2px;padding:3px;border-radius:12px}
.seg button{background:transparent;color:var(--muted);border:0;border-radius:9px;padding:7px 13px;font-size:12px;font-weight:600;cursor:pointer;transition:all .25s var(--ease)}
.seg button:hover{color:var(--text)}
.seg button.on{background:rgba(255,255,255,.10);color:var(--accent)}

/* ---- anillo ---- */
.anillo{display:flex;align-items:center;gap:18px}
.ring{position:relative;width:118px;height:118px}
.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring circle{fill:none;stroke-width:10}
.ring .bg{stroke:rgba(255,255,255,.08)}
.ring .fg{stroke:var(--accent);stroke-linecap:round;stroke-dasharray:326.73;stroke-dashoffset:326.73;transition:stroke-dashoffset 1s var(--ease),stroke .4s,opacity .3s;filter:drop-shadow(0 0 6px rgba(233,180,76,.45))}
.ring .fg.ok{stroke:var(--ok);filter:drop-shadow(0 0 6px rgba(143,191,138,.5))}
.pct{position:absolute;inset:0;display:grid;place-items:center;font:400 26px var(--serif)}
.stat{font:400 28px/1.1 var(--serif)}
.muted{color:var(--muted);font-size:12px}

/* ---- agregar tarea ---- */
.addbar{display:flex;align-items:center;gap:8px;padding:6px 12px 6px 18px;margin-bottom:14px;border-radius:16px;overflow:visible}
.addbar:focus-within{border-color:rgba(233,180,76,.6);box-shadow:0 0 0 3px rgba(233,180,76,.12),0 8px 32px rgba(0,0,0,.30)}
.addbar input[type=text]{flex:1;min-width:0;background:transparent;border:0;outline:0;color:var(--text);font-size:15px;padding:12px 0}
.addbar input::placeholder,textarea::placeholder{color:var(--faint)}
.addbar select{appearance:none;-webkit-appearance:none;background:rgba(255,255,255,.07);color:var(--text);border:0;border-radius:10px;padding:8px 12px;font-size:12px;cursor:pointer;outline:0}
.addbar select option{background:#292723;color:var(--text)}
.prios{display:flex;gap:2px;background:rgba(255,255,255,.06);border-radius:10px;padding:2px}
.prios button{background:transparent;border:0;color:var(--faint);font-size:12px;font-weight:600;padding:6px 10px;border-radius:8px;cursor:pointer;transition:all .2s}
.prios button.on{background:rgba(255,255,255,.10);color:var(--c)}
.min{width:56px;background:rgba(255,255,255,.07)!important;border-radius:10px;text-align:center;padding:8px 4px!important;font-size:12px!important;flex:none!important}

/* ---- filas de tarea ---- */
.sec{margin:12px 6px 4px}
.aviso{display:flex;justify-content:space-between;align-items:center;padding:8px 8px 8px 16px;margin-bottom:14px;border-radius:14px;color:var(--muted);font-size:12px}
.fila{display:flex;align-items:center;gap:14px;padding:12px 10px;border-radius:12px;border-bottom:1px solid rgba(255,255,255,.04);transition:background .2s,transform .25s var(--ease)}
.fila:hover{background:rgba(255,255,255,.05);transform:translateX(3px)}
.fila.in{animation:entra .5s var(--ease) backwards;animation-delay:calc(var(--i)*45ms)}
@keyframes entra{from{opacity:0;transform:translateY(22px) scale(.97)}}
.check{flex:none;width:26px;height:26px;border-radius:50%;border:2px solid var(--c);background:transparent;cursor:pointer;display:grid;place-items:center;transition:background .25s,border-color .25s,box-shadow .25s,transform .2s}
.check:hover{box-shadow:0 0 12px var(--c);transform:scale(1.1)}
.hecha .check{background:var(--ok);border-color:var(--ok)}
.check svg{width:16px;height:16px}
.check svg path{stroke-dasharray:24;stroke-dashoffset:0}
.fresh .check{animation:pop .45s var(--ease)}
.fresh .check svg path{animation:trazo .4s .08s var(--ease) backwards}
@keyframes pop{40%{transform:scale(1.3)}}
@keyframes trazo{from{stroke-dashoffset:24}}
.tit{flex:1;min-width:0;font-size:15px;transition:color .3s;overflow-wrap:anywhere}
.hecha .tit{color:var(--faint);text-decoration:line-through;text-decoration-color:var(--faint)}
.chip-c{font-size:11px;color:var(--muted);background:rgba(255,255,255,.07);padding:2px 10px;border-radius:99px}
.meta{font-size:11px;color:var(--muted);white-space:nowrap}
.acts{display:flex;gap:2px;opacity:0;transition:opacity .2s}
.fila:hover .acts{opacity:1}
.acts button,.x{background:transparent;border:0;color:var(--faint);cursor:pointer;font-size:11px;padding:4px 8px;border-radius:8px;transition:color .2s,background .2s}
.acts button:hover{color:var(--text);background:rgba(255,255,255,.08)}
.acts button[data-a=del],.x{font-size:16px}
.acts button[data-a=del]:hover,.x:hover{color:var(--bad)}

/* ---- bitácora ---- */
.nota-box{padding:0;margin-bottom:18px;border-radius:16px}
.nota-box:focus-within{border-color:rgba(233,180,76,.6);box-shadow:0 0 0 3px rgba(233,180,76,.12),0 8px 32px rgba(0,0,0,.30)}
.nota-box textarea{display:block;width:100%;height:96px;resize:none;background:transparent;border:0;outline:0;color:var(--text);font-size:14px;line-height:1.55;padding:16px 18px}
.pie{display:flex;align-items:center;gap:8px;padding:0 14px 12px}
.pie label{font-size:12px;color:var(--muted);margin-left:4px}
.pie label+.escala{margin-right:14px}
.escala{display:flex;gap:3px}
.escala button{width:30px;height:26px;border:0;border-radius:7px;background:rgba(255,255,255,.07);color:var(--muted);font-size:12px;cursor:pointer;transition:background .2s,color .2s,transform .15s}
.escala button.on{background:var(--accent);color:var(--accent-dk)}
.escala button:hover{transform:translateY(-2px)}
.pie .btn{margin-left:auto}
.nota{display:flex;gap:14px;padding:14px 6px;border-bottom:1px solid rgba(255,255,255,.05);border-radius:10px;transition:background .2s}
.nota:hover{background:rgba(255,255,255,.04)}
.nota.in{animation:entra .5s var(--ease) backwards;animation-delay:calc(var(--i)*60ms)}
.hora{font:12px ui-monospace,"Cascadia Mono",Menlo,Consolas,monospace;color:var(--accent);width:44px;flex:none;padding-top:2px}
.ntxt{flex:1;min-width:0}
.ntxt p{white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px}
.ntxt small{display:block;margin-top:4px;color:var(--muted);font-size:11px}

/* ---- análisis ---- */
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:14px}
.rise{animation:entra .6s var(--ease) backwards;animation-delay:calc(var(--i)*80ms)}
.stats .card{padding:14px 16px}
.stats .v{font:400 28px/1.25 var(--serif)}
.stats small{font-size:11px;color:var(--muted)}
.panel{margin-bottom:14px}
.panel>.kicker{padding:16px 20px 8px}
.dos{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.chart{height:200px;padding:16px 14px 36px 50px;position:relative}
.plot{position:relative;height:100%}
.g{position:absolute;left:0;right:0;border-top:1px dashed rgba(255,255,255,.10)}
.g.z{border-top:1px solid var(--faint)}
.g span{position:absolute;right:calc(100% + 8px);top:-7px;font-size:9px;color:var(--faint)}
.cols{position:absolute;inset:0;display:flex;gap:4px}
.col{flex:1;display:flex;align-items:flex-end;justify-content:center;position:relative}
.bar{position:relative;width:min(70%,40px);height:var(--h);min-height:3px;background:var(--c);border-radius:6px 6px 2px 2px;opacity:.92;transition:filter .2s,opacity .2s;animation:crece .9s var(--ease) backwards;animation-delay:calc(var(--i)*28ms)}
@keyframes crece{from{height:0}}
.bar:hover{filter:brightness(1.18);opacity:1}
.bar em{position:absolute;bottom:calc(100% + 3px);left:50%;transform:translateX(-50%);font-style:normal;font-size:9px;color:var(--muted)}
.lab{position:absolute;top:calc(100% + 8px);font-size:10px;color:var(--muted);text-align:center;line-height:1.25}
.lab small{display:block;font-size:9px;color:var(--faint)}
.cats{padding:0 20px 14px}
.cat{display:flex;align-items:center;gap:12px;height:38px}
.cn{width:84px;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.track{flex:1;height:8px;background:rgba(255,255,255,.08);border-radius:5px;overflow:hidden}
.track i{display:block;height:100%;width:var(--w);background:var(--c);border-radius:5px;animation:ancho 1s var(--ease) backwards;animation-delay:calc(var(--i)*80ms)}
@keyframes ancho{from{width:0}}
.cc{width:62px;text-align:right;line-height:1.15}
.cc b{display:block;font-size:12px;font-weight:600}
.cc small{font-size:10px;color:var(--faint)}
.lect{list-style:none;padding:0 20px 14px}
.lect li{display:flex;gap:9px;font-size:13px;margin-bottom:10px;animation:entra .55s var(--ease) backwards;animation-delay:calc(var(--i)*90ms + 300ms)}
.lect li::before{content:"•";color:var(--accent)}

/* ---- diálogo ---- */
#ov{position:fixed;inset:0;z-index:50;display:grid;place-items:start center;padding-top:16vh;background:rgba(10,9,8,.5);backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);opacity:0;pointer-events:none;transition:opacity .25s}
#ov.on{opacity:1;pointer-events:auto}
#modal{width:min(440px,92vw);padding:24px 26px;background:rgba(36,34,31,.78);transform:translateY(16px) scale(.96);transition:transform .35s var(--ease)}
#ov.on #modal{transform:none}
#modal h3{font:400 20px var(--serif)}
#modal p{margin-top:8px;color:var(--muted);white-space:pre-line}
#modal input{width:100%;margin-top:16px;padding:11px 13px;background:rgba(0,0,0,.35);border:1px solid var(--accent);border-radius:10px;color:var(--text);font-size:14px;outline:0}
.m-act{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}

@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-delay:0s!important;transition-duration:.01ms!important}}
</style>
</head>
<body>
<div class="luz l1"></div><div class="luz l2"></div><div class="luz l3"></div>

<div class="app">
  <aside class="side glass">
    <div class="marca"><i></i><span>Bitácora</span></div>
    <nav id="nav">
      <a data-k="hoy">Hoy</a><a data-k="bitacora">Bitácora</a><a data-k="analisis">Análisis</a>
    </nav>
    <div id="lado"></div>
  </aside>

  <main>
    <!-- HOY -->
    <section class="pag" id="p-hoy">
      <div class="cab">
        <div>
          <div class="kicker" id="h-kicker"></div>
          <h1 id="h-titulo"></h1>
          <div class="sub" id="h-sub"></div>
          <div class="navf">
            <button class="btn chip" data-mv="-1">‹</button><button class="btn chip" data-mv="1">›</button><button class="btn chip" data-hoy>Hoy</button>
          </div>
        </div>
        <div class="anillo">
          <div class="ring">
            <svg viewBox="0 0 120 120"><circle class="bg" cx="60" cy="60" r="52"/><circle class="fg" id="arco" cx="60" cy="60" r="52"/></svg>
            <div class="pct" id="h-pct">0%</div>
          </div>
          <div><div class="stat" id="h-hechas">0 de 0</div><div class="muted">tareas hechas</div></div>
        </div>
      </div>
      <div class="addbar glass">
        <input type="text" id="e-titulo" placeholder="Agregar una tarea…  (Enter para guardar)" autocomplete="off">
        <select id="e-cat"></select>
        <div class="prios" id="prios">
          <button data-p="1" style="--c:var(--bad)">Alta</button>
          <button data-p="2" style="--c:var(--accent)" class="on">Media</button>
          <button data-p="3" style="--c:var(--p3)">Baja</button>
        </div>
        <input type="text" id="e-min" class="min" placeholder="min" autocomplete="off">
        <button class="btn primary" id="b-add">Agregar</button>
      </div>
      <div class="scroll" id="lista"></div>
    </section>

    <!-- BITÁCORA -->
    <section class="pag" id="p-bitacora">
      <div class="cab">
        <div>
          <div class="kicker" id="n-kicker"></div>
          <h1 id="n-titulo"></h1>
          <div class="sub">¿Cómo va el día? Anota qué te ayudó, qué te distrajo, cómo te sentiste.</div>
          <div class="navf">
            <button class="btn chip" data-mv="-1">‹</button><button class="btn chip" data-mv="1">›</button><button class="btn chip" data-hoy>Hoy</button>
          </div>
        </div>
      </div>
      <div class="nota-box glass">
        <textarea id="t-nota" placeholder="Escribe aquí…  (Ctrl+Enter para guardar)"></textarea>
        <div class="pie">
          <label>Energía</label><div class="escala" id="s-energia"></div>
          <label>Ánimo</label><div class="escala" id="s-animo"></div>
          <button class="btn primary" id="b-nota">Guardar entrada</button>
        </div>
      </div>
      <div class="kicker" style="margin:0 6px 6px">Entradas del día</div>
      <div class="scroll" id="n-lista"></div>
    </section>

    <!-- ANÁLISIS -->
    <section class="pag" id="p-analisis">
      <div class="cab">
        <div><div class="kicker">ANÁLISIS</div><h1>Tu ritmo</h1></div>
        <div class="seg glass" id="seg">
          <button data-p="7 días">7 días</button><button data-p="30 días">30 días</button><button data-p="Este mes">Este mes</button><button data-p="Todo">Todo</button>
        </div>
      </div>
      <div class="scroll" id="a-cont"></div>
    </section>
  </main>
</div>

<div id="ov"><div id="modal" class="glass"></div></div>

<script>
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const DIAS = ["domingo","lunes","martes","miércoles","jueves","viernes","sábado"];
const MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
const PCOL = {1: "var(--bad)", 2: "var(--accent)", 3: "var(--p3)"};
const api = () => window.pywebview.api;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

function iso(d){ const p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())}`; }
function parse(s){ const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); }
const col = p => p == null ? "var(--surf2)" : p >= .8 ? "var(--ok)" : p >= .5 ? "var(--accent)" : "var(--bad)";

const S = {pagina: "hoy", fecha: iso(new Date()), cat: "general", prio: 2, periodo: "7 días",
           cats: [], tareas: {}, fresh: null, entrar: null, energia: 3, animo: 3};

/* ---------- utilidades visuales ---------- */
function contar(el, hasta, fmt = v => Math.round(v), dur = 800){
  const ini = parseFloat(el.dataset.v || 0); el.dataset.v = hasta;
  const t0 = performance.now();
  (function paso(t){
    const k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
    el.textContent = fmt(ini + (hasta - ini) * e);
    if (k < 1) requestAnimationFrame(paso);
  })(t0);
}
document.addEventListener("mousemove", e => {
  const g = e.target.closest && e.target.closest(".glass");
  if (g){ const r = g.getBoundingClientRect(); g.style.setProperty("--mx", (e.clientX - r.left) + "px"); g.style.setProperty("--my", (e.clientY - r.top) + "px"); }
});

function dialogo(o){
  return new Promise(res => {
    const ov = $("#ov"), m = $("#modal");
    m.innerHTML = `<h3>${esc(o.titulo)}</h3>${o.mensaje ? `<p>${esc(o.mensaje)}</p>` : ""}${o.entrada ? `<input id="m-in" type="text" autocomplete="off">` : ""}
      <div class="m-act"><button class="btn ghost" id="m-c">${esc(o.cancelar || "Cancelar")}</button><button class="btn ${o.peligro ? "danger" : "primary"}" id="m-ok">${esc(o.ok || "Aceptar")}</button></div>`;
    ov.classList.add("on");
    const inp = $("#m-in");
    if (inp){ inp.value = o.inicial || ""; inp.focus(); inp.select(); } else $("#m-ok").focus();
    const cerrar = v => { ov.classList.remove("on"); document.removeEventListener("keydown", kd, true); res(v); };
    const kd = e => {
      if (e.key === "Escape"){ e.stopPropagation(); cerrar(null); }
      else if (e.key === "Enter"){ e.preventDefault(); e.stopPropagation(); cerrar(inp ? inp.value.trim() : true); }
    };
    document.addEventListener("keydown", kd, true);
    $("#m-ok").onclick = () => cerrar(inp ? inp.value.trim() : true);
    $("#m-c").onclick = () => cerrar(null);
    ov.onclick = e => { if (e.target === ov) cerrar(null); };
  });
}
const pedir = (titulo, mensaje, inicial = "", ok = "Guardar") => dialogo({titulo, mensaje, entrada: true, inicial, ok});
const confirmar = (titulo, mensaje, ok = "Eliminar") => dialogo({titulo, mensaje, ok, peligro: true}).then(v => v === true);
const aviso = (titulo, mensaje) => dialogo({titulo, mensaje, ok: "Entendido", cancelar: "Cerrar"});

/* ---------- navegación ---------- */
function cabecera(){
  const d = parse(S.fecha), hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const delta = Math.round((d - hoy) / 864e5);
  const rel = {"0": "hoy", "-1": "ayer", "1": "mañana"}[delta];
  const kick = DIAS[d.getDay()].toUpperCase() + (rel ? "  ·  " + rel.toUpperCase() : "");
  let t = `${d.getDate()} de ${MESES[d.getMonth()]}`;
  if (d.getFullYear() !== hoy.getFullYear()) t += ` de ${d.getFullYear()}`;
  ["h", "n"].forEach(p => { $("#" + p + "-kicker").textContent = kick; $("#" + p + "-titulo").textContent = t; });
}
function mostrar(k){
  S.pagina = k;
  $$(".pag").forEach(p => p.classList.toggle("on", p.id === "p-" + k));
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.k === k));
  refrescar(true);
}
async function refrescar(animar = false){
  cabecera();
  if (S.pagina === "hoy") await cargarHoy(animar);
  else if (S.pagina === "bitacora") await cargarNotas(animar);
  else await cargarAnalisis();
  cargarLado();
}
function moverFecha(n){ const d = parse(S.fecha); d.setDate(d.getDate() + n); S.fecha = iso(d); refrescar(true); }

async function cargarLado(){
  const l = await api().lado();
  $("#lado").innerHTML = `<div class="kicker">Racha</div>
    <div class="racha"><b class="${l.racha ? "" : "cero"}">${l.racha}</b><span>${l.racha === 1 ? "día" : "días"}</span></div>
    <div class="sem">${l.semana.map((d, i) => `<div class="dia ${d.hoy ? "hoy" : ""}"><i style="--c:${col(d.p)};--i:${i}"></i><span>${d.l}</span></div>`).join("")}</div>`;
}

/* ---------- HOY ---------- */
function mensaje(p, total, pend){
  if (!total) return "Un día en blanco. Empieza con una tarea pequeña.";
  if (p >= 1) return "Día completo. Bien hecho.";
  if (p === 0) return total === 1 ? "Solo una. Vamos." : `${total} por hacer. La primera es la más difícil.`;
  if (p < .5) return "Ya arrancaste. Sigue con la siguiente.";
  return pend === 1 ? "Falta 1." : `Más de la mitad. Faltan ${pend}.`;
}
function setAnillo(p){
  const arco = $("#arco");
  arco.style.strokeDashoffset = 326.73 * (1 - p);
  arco.style.opacity = p > 0 ? 1 : 0;
  arco.classList.toggle("ok", p >= 1);
  const pc = $("#h-pct");
  contar(pc, Math.round(p * 100), v => Math.round(v) + "%", 900);
  pc.style.color = p >= 1 ? "var(--ok)" : "var(--text)";
}
const CHECK = `<svg viewBox="0 0 24 24"><path d="M6 12.5l4 4 8-9" fill="none" stroke="#131211" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
function fila(t, i){
  const hecha = t.estado === "hecha";
  const anim = i >= 0 || t.id === S.entrar;
  const meta = [t.min_estimados ? `est. ${t.min_estimados} min` : "", t.min_reales ? `real ${t.min_reales} min` : ""].filter(Boolean).join("  ·  ");
  return `<div class="fila ${hecha ? "hecha" : ""} ${anim ? "in" : ""} ${S.fresh === t.id ? "fresh" : ""}" data-id="${t.id}" style="--i:${Math.max(0, Math.min(i, 14))};--c:${PCOL[t.prioridad] || "var(--muted)"}">
    <button class="check" data-a="alt" aria-label="Completar">${hecha ? CHECK : ""}</button>
    <span class="tit">${esc(t.titulo)}</span>
    <span class="chip-c">${esc(t.categoria)}</span>
    <span class="meta">${meta}</span>
    <span class="acts"><button data-a="edit">editar</button><button data-a="del">×</button></span>
  </div>`;
}
async function cargarHoy(animar){
  const d = await api().dia(S.fecha);
  S.cats = d.categorias; S.tareas = {};
  d.tareas.forEach(t => S.tareas[t.id] = t);
  renderCats();
  const pend = d.tareas.filter(t => t.estado !== "hecha"), hechas = d.tareas.filter(t => t.estado === "hecha");
  const total = d.tareas.length, p = total ? hechas.length / total : 0;
  setAnillo(p);
  $("#h-sub").textContent = mensaje(p, total, pend.length);
  $("#h-hechas").textContent = `${hechas.length} de ${total}`;
  let h = "";
  if (d.previos) h += `<div class="aviso glass rise" style="--i:0"><span>Tienes ${d.previos} pendiente${d.previos !== 1 ? "s" : ""} de días anteriores.</span><button class="btn chip" data-a="traer">Traer a este día</button></div>`;
  if (!total) h += `<div class="vacio">Nada por aquí todavía.<br>Escribe tu primera tarea arriba.</div>`;
  let i = 0;
  [["Pendientes", pend], ["Hechas", hechas]].forEach(([tt, g]) => {
    if (!g.length) return;
    h += `<div class="kicker sec">${tt}  ·  ${g.length}</div>`;
    g.forEach(t => h += fila(t, animar ? i++ : -1));
  });
  $("#lista").innerHTML = h;
  S.fresh = null; S.entrar = null;
}
function renderCats(){
  const sel = $("#e-cat");
  sel.innerHTML = S.cats.map(c => `<option value="${esc(c)}" ${c === S.cat ? "selected" : ""}>${esc(c)}</option>`).join("") + `<option value="__nueva">＋ Nueva categoría…</option>`;
}
async function agregar(){
  const ti = $("#e-titulo"), titulo = ti.value.trim();
  if (!titulo){ ti.focus(); return; }
  const est = $("#e-min").value.trim();
  if (est && !/^\d+$/.test(est)){ await aviso("Minutos no válidos", "Escribe solo un número, por ejemplo 45."); return; }
  S.entrar = await api().agregar_tarea(S.fecha, titulo, S.cat, S.prio, est ? +est : null);
  ti.value = ""; $("#e-min").value = ""; ti.focus();
  await refrescar(false);
}
async function alternar(t){
  if (t.estado === "hecha"){ await api().alternar(t.id, null); }
  else {
    const txt = await pedir("¿Cuánto tardaste?", `«${t.titulo}»\nMinutos reales (opcional, puedes dejarlo vacío).`, "", "Listo");
    if (txt === null) return;
    if (txt && !/^\d+$/.test(txt)){ await aviso("Minutos no válidos", "Escribe solo un número, por ejemplo 45."); return; }
    S.fresh = t.id;
    await api().alternar(t.id, txt ? +txt : null);
  }
  refrescar(false);
}
async function editar(t){
  const nuevo = await pedir("Editar tarea", "", t.titulo);
  if (nuevo){ await api().editar_tarea(t.id, nuevo); refrescar(false); }
}
async function eliminar(t){
  if (await confirmar("¿Eliminar tarea?", `«${t.titulo}» se borrará para siempre.`)){
    const el = $(`.fila[data-id="${t.id}"]`);
    if (el){ el.style.transition = "opacity .25s, transform .25s"; el.style.opacity = 0; el.style.transform = "translateX(30px)"; await new Promise(r => setTimeout(r, 220)); }
    await api().eliminar_tarea(t.id); refrescar(false);
  }
}

/* ---------- BITÁCORA ---------- */
function renderEscala(id, clave){
  const box = $("#" + id);
  box.innerHTML = [1, 2, 3, 4, 5].map(i => `<button data-v="${i}">${i}</button>`).join("");
  const pintar = () => $$("button", box).forEach(b => b.classList.toggle("on", +b.dataset.v <= S[clave]));
  box.onclick = e => { const b = e.target.closest("button"); if (b){ S[clave] = +b.dataset.v; pintar(); } };
  pintar();
}
async function cargarNotas(animar){
  const ns = await api().notas(S.fecha);
  $("#n-lista").innerHTML = ns.length ? ns.map((n, i) => `<div class="nota ${animar ? "in" : ""}" style="--i:${i}" data-id="${n.id}">
      <span class="hora">${esc(n.hora)}</span>
      <div class="ntxt"><p>${esc(n.nota)}</p>${(n.energia || n.animo) ? `<small>energía ${n.energia || "–"}/5   ·   ánimo ${n.animo || "–"}/5</small>` : ""}</div>
      <button class="x" data-a="delnota">×</button></div>`).join("")
    : `<div class="vacio">Sin entradas este día.</div>`;
}
async function agregarNota(){
  const ta = $("#t-nota"), texto = ta.value.trim();
  if (!texto){ ta.focus(); return; }
  await api().agregar_nota(S.fecha, S.energia, S.animo, texto);
  ta.value = ""; refrescar(true);
}

/* ---------- ANÁLISIS ---------- */
async function cargarAnalisis(){
  $$("#seg button").forEach(b => b.classList.toggle("on", b.dataset.p === S.periodo));
  const r = await api().analisis(S.periodo), box = $("#a-cont");
  if (r.vacio){
    box.innerHTML = `<div class="vacio">Aún no hay datos en este periodo.<br>Agrega tareas y márcalas como hechas: aquí verás tus patrones.</div>`;
    return;
  }
  const pct = r.hechas / r.total, hh = Math.floor(r.minutos / 60), mm = r.minutos % 60;
  const tiempo = hh ? `${hh} h ${String(mm).padStart(2, "0")}` : `${mm} min`;
  let estV = "–", estS = "falta registrar minutos";
  if (r.ratio){ estV = r.ratio.toFixed(1) + "×"; estS = r.ratio > 1.1 ? "subestimas el tiempo" : r.ratio < .9 ? "sobreestimas el tiempo" : "estimas bien"; }
  const cards = [
    ["Cumplimiento", `<span data-n="${Math.round(pct * 100)}" data-s="%">0%</span>`, `${r.hechas} de ${r.total} tareas`, col(pct)],
    ["Tiempo", tiempo, "en tareas hechas", "var(--text)"],
    ["Mejor racha", `<span data-n="${r.racha}">0</span>`, "días seguidos con ≥80%", "var(--text)"],
    ["Tu estimación", estV, estS, "var(--text)"]];
  const stats = cards.map((c, i) => `<div class="card glass rise" style="--i:${i}"><div class="kicker">${c[0]}</div><div class="v" style="color:${c[3]}">${c[1]}</div><small>${c[2]}</small></div>`).join("");

  const n = r.dias.length, cada = n <= 14 ? 1 : Math.max(1, Math.round(n / 12));
  const cols = r.dias.map((d, i) => {
    const p = d.h / d.n, dt = parse(d.fecha), lab = i % cada === 0 || i === n - 1;
    return `<div class="col" title="${d.fecha}: ${d.h}/${d.n}"><div class="bar" style="--h:${p * 100}%;--c:${col(p)};--i:${i}">${n <= 20 ? `<em>${Math.round(p * 100)}</em>` : ""}</div>
      ${lab ? `<span class="lab">${dt.getDate()}${n <= 14 ? `<small>${DIAS[dt.getDay()].slice(0, 3)}</small>` : ""}</span>` : ""}</div>`;
  }).join("");
  const grafica = `<div class="panel glass rise" style="--i:4"><div class="kicker">Cumplimiento por día</div>
    <div class="chart"><div class="plot">
      <div class="g" style="bottom:100%"><span>100%</span></div><div class="g" style="bottom:50%"><span>50%</span></div><div class="g z" style="bottom:0"><span>0%</span></div>
      <div class="cols">${cols}</div></div></div></div>`;

  const cats = r.categorias.map((c, i) => { const p = c.h / c.n;
    return `<div class="cat"><span class="cn">${esc(c.nombre)}</span><div class="track"><i style="--w:${p * 100}%;--c:${col(p)};--i:${i}"></i></div><div class="cc"><b>${c.h}/${c.n}</b><small>${c.min} min</small></div></div>`; }).join("");
  const lect = r.lecturas.map((l, i) => `<li style="--i:${i}">${esc(l)}</li>`).join("");
  const dos = `<div class="dos">
    <div class="panel glass rise" style="--i:5"><div class="kicker">Por categoría</div><div class="cats">${cats}</div></div>
    <div class="panel glass rise" style="--i:6"><div class="kicker">Lo que dicen tus datos</div><ul class="lect">${lect}</ul></div></div>`;

  box.innerHTML = `<div class="stats">${stats}</div>${grafica}${dos}`;
  $$("[data-n]", box).forEach(el => contar(el, +el.dataset.n, v => Math.round(v) + (el.dataset.s || ""), 900));
}

/* ---------- eventos ---------- */
document.addEventListener("click", e => {
  const mv = e.target.closest("[data-mv]"); if (mv) return moverFecha(+mv.dataset.mv);
  if (e.target.closest("[data-hoy]")){ S.fecha = iso(new Date()); return refrescar(true); }
  const nav = e.target.closest("#nav a"); if (nav) return mostrar(nav.dataset.k);
  const seg = e.target.closest("#seg button"); if (seg){ S.periodo = seg.dataset.p; return cargarAnalisis(); }
  const pr = e.target.closest("#prios button");
  if (pr){ S.prio = +pr.dataset.p; $$("#prios button").forEach(b => b.classList.toggle("on", b === pr)); return; }
  const b = e.target.closest("[data-a]"); if (!b) return;
  const f = b.closest(".fila"), t = f ? S.tareas[f.dataset.id] : null;
  switch (b.dataset.a){
    case "alt": return alternar(t);
    case "edit": return editar(t);
    case "del": return eliminar(t);
    case "traer": return api().traer_pendientes(S.fecha).then(() => refrescar(true));
    case "delnota": return confirmar("¿Eliminar entrada?", "Esta nota se borrará para siempre.")
      .then(ok => ok && api().eliminar_nota(+b.closest(".nota").dataset.id).then(() => refrescar(false)));
  }
});
document.addEventListener("dblclick", e => {
  const tit = e.target.closest(".tit"); if (!tit) return;
  editar(S.tareas[tit.closest(".fila").dataset.id]);
});
$("#e-cat").addEventListener("change", async e => {
  if (e.target.value === "__nueva"){
    const n = await pedir("Nueva categoría", "Dale un nombre corto, por ejemplo «lectura».", "", "Crear");
    if (n){ S.cat = n.toLowerCase().slice(0, 20); if (!S.cats.includes(S.cat)) S.cats.push(S.cat); }
    renderCats();
  } else S.cat = e.target.value;
});
$("#e-titulo").addEventListener("keydown", e => { if (e.key === "Enter") agregar(); });
$("#e-min").addEventListener("keydown", e => { if (e.key === "Enter") agregar(); });
$("#b-add").addEventListener("click", agregar);
$("#b-nota").addEventListener("click", agregarNota);
$("#t-nota").addEventListener("keydown", e => { if (e.ctrlKey && e.key === "Enter"){ e.preventDefault(); agregarNota(); } });
document.addEventListener("keydown", e => {
  if (!e.ctrlKey) return;
  if (e.key === "n"){ e.preventDefault(); mostrar("hoy"); setTimeout(() => $("#e-titulo").focus(), 60); }
  else if (e.key === "1") mostrar("hoy");
  else if (e.key === "2") mostrar("bitacora");
  else if (e.key === "3") mostrar("analisis");
});

/* ---------- arranque ---------- */
let iniciado = false;
function iniciar(){
  if (iniciado) return; iniciado = true;
  renderEscala("s-energia", "energia"); renderEscala("s-animo", "animo");
  mostrar("hoy");
}
window.addEventListener("pywebviewready", iniciar);
if (window.pywebview && window.pywebview.api) iniciar();
</script>
</body>
</html>
"""


def main():
    try:
        import webview
    except ImportError:
        raise SystemExit("Falta pywebview. Instálalo con:  pip install pywebview")
    webview.create_window("Bitácora", html=HTML, js_api=Api(), width=1120, height=740,
                          min_size=(940, 620), background_color="#131211")
    webview.start()


if __name__ == "__main__":
    main()

"""
Genera las tablas de deflexiones (referidas a hitos) y la propuesta de zonas de
fresado y reposición de la HU-5401 a partir de los datos del proyecto 2512-PC.

Entradas (en esta carpeta):
  deflexiones_hu5401.csv  -> carril, pk_obra_km, pk_hito_km, deflexion_mm100, singular_gya
Salidas:
  zonas_fresado_propuestas.csv
  tabla_proyecto_km_carril.csv

Criterio de zonas (por kilómetro y carril):
  1. La longitud a fresar de cada km/carril es la del proyecto (Anejo 3, tabla
     de superficies). No se cambia la medición, solo se localiza.
  2. Cada punto de ensayo HWD representa el tramo entre los puntos medios con
     sus vecinos (≈20 m).
  3. Los puntos singulares del informe GYA (agotamiento) entran siempre.
  4. El resto se ordena por la media móvil de 3 puntos (≈60 m), desempatando
     por la deflexión del propio punto, y se toman hasta alcanzar la longitud.
  5. El exceso de la última celda se recorta de la zona más larga del km.
  6. Las celdas contiguas se unen en una sola zona.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))

# Anejo 3 (pág. 6) / Mediciones 0102. Longitud (m) y anchura (m) por km y carril.
# Nota: en Mediciones 3+000-4+000 carril derecho figura 1.888 m (errata de 188 m).
PROYECTO = {
    'D': [(150, 3.5), (125, 3.0), (90, 3.0), (188, 2.0), (85, 3.5), (175, 2.0),
          (110, 2.0), (188, 2.5), (172, 3.0), (190, 2.0), (192, 2.5), (150, 2.0),
          (158, 3.5), (170, 2.5), (150, 3.0), (185, 2.0), (101, 3.0), (110, 2.5)],
    'I': [(120, 2.5), (110, 3.5), (102, 3.5), (95, 2.5), (177, 2.0), (105, 2.5),
          (192, 3.0), (175, 3.0), (218, 2.0), (220, 2.0), (144, 2.5), (166, 3.0),
          (169, 2.0), (175, 2.5), (195, 2.0), (105, 2.5), (125, 2.0), (165, 2.0)],
}
PK_FIN = 17.250


def leer_deflexiones():
    pts = {'D': [], 'I': []}
    with open(os.path.join(HERE, 'deflexiones_hu5401.csv'), newline='') as f:
        for r in csv.DictReader(f):
            pts[r['carril']].append({
                'pk': float(r['pk_hito_km']),
                'd': int(r['deflexion_mm100']),
                'sing': r['singular_gya'] == '1',
            })
    for s in pts:
        pts[s].sort(key=lambda p: p['pk'])
    return pts


def celdas(pts):
    """Asigna a cada punto su intervalo de influencia [ini, fin) en km."""
    n = len(pts)
    for i, p in enumerate(pts):
        prev_pk = pts[i - 1]['pk'] if i else None
        next_pk = pts[i + 1]['pk'] if i < n - 1 else None
        # huecos > 40 m (puentes, cruces sin ensayo): no se extiende la celda
        ini = p['pk'] - 0.010 if prev_pk is None or p['pk'] - prev_pk > 0.040 else (p['pk'] + prev_pk) / 2
        fin = p['pk'] + 0.010 if next_pk is None or next_pk - p['pk'] > 0.040 else (p['pk'] + next_pk) / 2
        p['ini'], p['fin'] = max(ini, 0.0), min(fin, PK_FIN)
        vec = [q['d'] for q in pts[max(i - 1, 0):i + 2]]
        p['score'] = sum(vec) / len(vec)


def zonas_carril(s, pts):
    out = []
    for k, (lon_m, ancho) in enumerate(PROYECTO[s]):
        km_ini, km_fin = float(k), min(k + 1.0, PK_FIN)
        cand = [p for p in pts if km_ini <= p['pk'] < km_fin]
        orden = sorted(cand, key=lambda p: (not p['sing'], -p['score'], -p['d']))
        elegidas, acum = [], 0.0
        for p in orden:
            if acum >= lon_m / 1000 - 1e-9:
                break
            # recorta las celdas al km para no invadir el km vecino
            p_ini, p_fin = max(p['ini'], km_ini), min(p['fin'], km_fin)
            elegidas.append((p_ini, p_fin, p))
            acum += p_fin - p_ini
        elegidas.sort(key=lambda e: e[0])
        grupos = []
        for e in elegidas:
            if grupos and abs(e[0] - grupos[-1][-1][1]) < 1e-6:
                grupos[-1].append(e)
            else:
                grupos.append([e])
        # el exceso sobre la medición se recorta por igual en los extremos de la zona más larga
        exceso = acum - lon_m / 1000
        if grupos and exceso > 0:
            g = max(grupos, key=lambda g: g[-1][1] - g[0][0])
            g[0] = (g[0][0] + exceso / 2,) + g[0][1:]
            g[-1] = (g[-1][0], g[-1][1] - exceso / 2, g[-1][2])
        for g in grupos:
            ds = [e[2]['d'] for e in g]
            out.append({
                'carril': s,
                'km': k,
                'pk_ini': round(g[0][0], 3),
                'pk_fin': round(g[-1][1], 3),
                'longitud_m': round((g[-1][1] - g[0][0]) * 1000, 1),
                'ancho_m': ancho,
                'superficie_m2': round((g[-1][1] - g[0][0]) * 1000 * ancho, 1),
                'defl_max': max(ds),
                'defl_media': round(sum(ds) / len(ds)),
                'n_ensayos': len(ds),
                'singular_gya': int(any(e[2]['sing'] for e in g)),
                'long_proyecto_km_m': lon_m,
            })
    return out


def main():
    pts = leer_deflexiones()
    zonas = []
    for s in ('D', 'I'):
        celdas(pts[s])
        zonas += zonas_carril(s, pts[s])
    for i, z in enumerate(zonas, 1):
        z['id'] = f"Z{z['carril']}{i:03d}"
    campos = ['id', 'carril', 'km', 'pk_ini', 'pk_fin', 'longitud_m', 'ancho_m',
              'superficie_m2', 'defl_max', 'defl_media', 'n_ensayos', 'singular_gya',
              'long_proyecto_km_m']
    with open(os.path.join(HERE, 'zonas_fresado_propuestas.csv'), 'w', newline='') as f:
        w = csv.DictWriter(f, campos)
        w.writeheader()
        w.writerows(zonas)

    with open(os.path.join(HERE, 'tabla_proyecto_km_carril.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['carril', 'pk_ini', 'pk_fin', 'longitud_m', 'ancho_m', 'superficie_m2',
                    'pct_longitud_km', 'defl_media', 'defl_max', 'n_ensayos'])
        for s in ('D', 'I'):
            for k, (lon, an) in enumerate(PROYECTO[s]):
                fin = min(k + 1.0, PK_FIN)
                ds = [p['d'] for p in pts[s] if k <= p['pk'] < fin]
                w.writerow([s, float(k), fin, lon, an, lon * an,
                            round(100 * lon / ((fin - k) * 1000), 1),
                            round(sum(ds) / len(ds)) if ds else '', max(ds) if ds else '', len(ds)])

    tot = sum(z['superficie_m2'] for z in zonas)
    print(f'{len(zonas)} zonas, {tot:.0f} m2 (proyecto 13.674,5 m2)')


if __name__ == '__main__':
    main()

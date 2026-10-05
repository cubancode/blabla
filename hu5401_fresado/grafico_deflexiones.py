"""Perfil de deflexiones HWD por carril con las zonas de fresado propuestas."""
import csv
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
P = list(csv.DictReader(open(os.path.join(HERE, 'deflexiones_hu5401.csv'))))
Z = list(csv.DictReader(open(os.path.join(HERE, 'zonas_fresado_propuestas.csv'))))
T = list(csv.DictReader(open(os.path.join(HERE, 'tabla_proyecto_km_carril.csv'))))
INK, MUTED, LINE, ZONE, SING = '#0b0b0b', '#52514e', '#2a78d6', '#eb6834', '#e34948'

fig, axes = plt.subplots(2, 1, figsize=(18, 8), sharex=True, facecolor='#fcfcfb')
for ax, (c, nom) in zip(axes, (('D', 'Carril derecho (sentido PK creciente)'),
                               ('I', 'Carril izquierdo (sentido PK decreciente)'))):
    ax.set_facecolor('#fcfcfb')
    for z in Z:
        if z['carril'] == c:
            ax.axvspan(float(z['pk_ini']), float(z['pk_fin']), color=ZONE, alpha=0.35, lw=0)
    pts = [p for p in P if p['carril'] == c]
    xs = [float(p['pk_hito_km']) for p in pts]
    ys = [int(p['deflexion_mm100']) for p in pts]
    ax.plot(xs, ys, color=LINE, lw=1.2)
    sx = [float(p['pk_hito_km']) for p in pts if p['singular_gya'] == '1']
    sy = [int(p['deflexion_mm100']) for p in pts if p['singular_gya'] == '1']
    ax.scatter(sx, sy, s=40, color=SING, zorder=3, edgecolor='#fcfcfb', linewidth=1.5)
    for t in T:
        if t['carril'] == c:
            ax.text((float(t['pk_ini']) + float(t['pk_fin'])) / 2, 205,
                    f"{float(t['longitud_m']):.0f} m × {float(t['ancho_m']):.1f}", ha='center',
                    fontsize=8, color=MUTED)
    ax.set_ylim(0, 215)
    ax.set_ylabel('Deflexión patrón (0,01 mm)', color=MUTED)
    ax.set_title(nom, loc='left', color=INK, fontsize=11)
    ax.grid(axis='y', color='#e5e4e0', lw=0.6)
    for s in ('top', 'right'):
        ax.spines[s].set_visible(False)
    ax.tick_params(colors=MUTED)
axes[1].set_xlim(0, 17.25)
axes[1].set_xticks(range(18))
axes[1].set_xlabel('PK de hito (km)', color=MUTED)
from matplotlib.patches import Patch
from matplotlib.lines import Line2D
axes[0].legend(handles=[Line2D([], [], color=LINE, lw=1.2, label='Deflexión HWD'),
                        Line2D([], [], marker='o', ls='', color=SING, label='Punto singular (informe GYA)'),
                        Patch(color=ZONE, alpha=0.35, label='Zona de fresado propuesta'),
                        Line2D([], [], ls='', label='Arriba: medición del proyecto por km (long. × ancho)')],
               loc='lower right', ncol=4, frameon=False, fontsize=9)
fig.suptitle('HU-5401 · Deflexiones HWD y zonas de fresado propuestas (PK de hito)',
             x=0.01, ha='left', color=INK, fontsize=13)
fig.tight_layout()
fig.savefig(os.path.join(HERE, 'perfil_deflexiones_zonas.png'), dpi=110)

"""Listado de campo en PDF (A4): zonas de fresado propuestas agrupadas por km."""
import csv
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, KeepTogether

HERE = os.path.dirname(os.path.abspath(__file__))
Z = list(csv.DictReader(open(os.path.join(HERE, 'zonas_fresado_propuestas.csv'), encoding='utf-8')))
T = list(csv.DictReader(open(os.path.join(HERE, 'tabla_proyecto_km_carril.csv'), encoding='utf-8')))


def pk(x):
    m = int(round(float(x) * 1000))
    return f'{m // 1000}+{m % 1000:03d}'


def n(x, d=1):
    return f'{float(x):,.{d}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


st = getSampleStyleSheet()
st['Title'].fontSize = 15
peq = st['BodyText'].clone('peq', fontSize=8.5, leading=11)
doc = SimpleDocTemplate(os.path.join(HERE, 'listado_campo_fresado_HU5401.pdf'), pagesize=A4,
                        leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                        title='HU-5401 · Listado de campo de fresado')
el = [Paragraph('HU-5401 · Fresado y reposición · Listado de campo', st['Title']),
      Paragraph('Zonas propuestas a partir del ensayo HWD (GYA, julio 2025), repartiendo la medición del proyecto '
                '(Anejo 3) por km y carril. <b>PK de hito.</b> Carril D = sentido PK creciente (hacia Paymogo); '
                'carril I = sentido decreciente (hacia Puebla de Guzmán). La franja se plantea desde el borde de '
                'calzada hacia el eje. * = punto singular del informe GYA. <b>Comprobar en campo y anotar el ajuste.</b>',
                peq),
      Spacer(1, 4 * mm)]
cab = ['Zona', 'Carril', 'PK inicio', 'PK fin', 'Long.\n(m)', 'Ancho\n(m)', 'Sup.\n(m²)', 'Defl.\nmáx', "OK",
       'Ajuste / observaciones']
anchos = [15, 11, 17, 17, 13, 13, 14, 12, 8, 66]
for k in range(18):
    tr = {t['carril']: t for t in T if int(float(t['pk_ini'])) == k}
    zs = sorted([z for z in Z if int(z['km']) == k], key=lambda z: float(z['pk_ini']))
    fin = '17+250' if k == 17 else f'{k + 1}+000'
    tit = Paragraph(f"<b>km {k}+000 – {fin}</b> · Proyecto: carril D {n(tr['D']['longitud_m'], 0)} m × "
                    f"{n(tr['D']['ancho_m'])} m = {n(tr['D']['superficie_m2'], 0)} m² · carril I "
                    f"{n(tr['I']['longitud_m'], 0)} m × {n(tr['I']['ancho_m'])} m = {n(tr['I']['superficie_m2'], 0)} m²",
                    st['BodyText'])
    filas = [cab]
    for z in zs:
        filas.append([z['id'] + (' *' if z['singular_gya'] == '1' else ''), z['carril'], pk(z['pk_ini']),
                      pk(z['pk_fin']), n(z['longitud_m']), n(z['ancho_m']), n(z['superficie_m2'], 0),
                      z['defl_max'], "", ''])
    tb = Table(filas, colWidths=[a * mm for a in anchos], repeatRows=1)
    estilo = [('FONT', (0, 0), (-1, -1), 'Helvetica', 8.5),
              ('FONT', (0, 0), (-1, 0), 'Helvetica-Bold', 8),
              ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e8eef7')),
              ('GRID', (0, 0), (-1, -1), 0.3, colors.HexColor('#808080')),
              ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
              ('ALIGN', (4, 1), (8, -1), 'RIGHT'),
              ('ALIGN', (8, 0), (8, -1), 'CENTER'),
              ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f6f4')]),
              ('TOPPADDING', (0, 1), (-1, -1), 4), ('BOTTOMPADDING', (0, 1), (-1, -1), 4)]
    for i, z in enumerate(zs, 1):
        if z['carril'] == 'D':
            estilo.append(('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#c00000')))
        else:
            estilo.append(('TEXTCOLOR', (1, i), (1, i), colors.HexColor('#d06000')))
    tb.setStyle(TableStyle(estilo))
    el.append(KeepTogether([tit, Spacer(1, 1.5 * mm), tb, Spacer(1, 5 * mm)]))
doc.build(el)
print('ok')

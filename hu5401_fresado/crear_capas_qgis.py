"""
HU-5401 · Crea en QGIS las capas de deflexiones y de zonas de fresado/reposición
a partir del eje de la carretera.

Uso: abrir en QGIS > Complementos > Consola de Python > Editor, ajustar la
sección CONFIGURACIÓN y ejecutar. Genera un GeoPackage con:
  - deflexiones_hwd       puntos de ensayo (centro de carril)
  - zonas_fresado         polígonos propuestos (tabla zonas_fresado_propuestas.csv)
  - tramos_proyecto       km/carril con la medición del proyecto (líneas)
  - hitos_calculados      dónde cae cada hito según la calibración (para comprobar)
  - hojas_planos          hojas del atlas (cada HOJA_M metros)
  - marcas_pk_100m        marcas de PK cada 100 m
y, si CREAR_PLANOS, una composición de impresión con atlas (una hoja por tramo,
con la tabla de zonas para apuntar en campo) y su exportación a PDF.
Los estilos quedan guardados dentro del GeoPackage.

Referencia de PK: los PK de las tablas son PK de HITO (los "PK de obra" del
informe HWD ya se han convertido con las marcas de hito del propio ensayo).
Por eso conviene calibrar el eje con los hitos reales (opción A o B).
"""
import csv
import math
import os

from qgis.core import (
    QgsFeature, QgsField, QgsFields, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes, QgsCoordinateTransformContext,
    QgsGraduatedSymbolRenderer, QgsRendererRange, QgsSymbol, QgsCategorizedSymbolRenderer,
    QgsRendererCategory, QgsRuleBasedRenderer, QgsPalLayerSettings, QgsTextFormat,
    QgsTextBufferSettings, QgsTextBackgroundSettings, QgsVectorLayerSimpleLabeling,
    QgsRasterLayer, QgsPrintLayout, QgsLayoutItemPage, QgsLayoutItemMap, QgsLayoutItemLabel,
    QgsLayoutItemLegend, QgsLayoutItemScaleBar, QgsLayoutItemAttributeTable, QgsLayoutFrame,
    QgsLayoutTableColumn, QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes, QgsLayoutExporter,
    QgsFillSymbol, QgsMarkerSymbol, QgsLineSymbol, QgsLayoutObject, QgsProperty,
    QgsLayoutItemPicture, QgsLegendStyle,
)
from qgis.PyQt.QtCore import QVariant, Qt, QSizeF
from qgis.PyQt.QtGui import QColor, QFont

# ----------------------------------------------------------------------------
# CONFIGURACIÓN
# ----------------------------------------------------------------------------
EJE = 'eje_HU5401'          # nombre de la capa del eje en el proyecto (o ruta a fichero)
CARPETA = None              # carpeta con los CSV; None = la de este script
SALIDA = None               # GeoPackage de salida; None = <CARPETA>/hu5401_fresado.gpkg

# Sentido: el PK 0+000 está en Puebla de Guzmán y crece hacia Paymogo.
# Si el eje está digitalizado al revés, poner True.
INVERTIR_EJE = False

# Calibración del PK (elegir una; se usa la primera disponible):
#  A) Capa de puntos con los hitos reales y un campo con el PK en km (p.ej. 5 ó 5.0)
HITOS_CAPA = None           # p.ej. 'hitos_HU5401'
HITOS_CAMPO = 'pk'
#  B) Usar los valores M del eje (en km o m, ver M_EN_METROS) si el eje es LineStringM
USAR_M = False
M_EN_METROS = False
#  C) Sin calibración: PK = (distancia a lo largo del eje + PK_ORIGEN_M) / 1000
PK_ORIGEN_M = 0.0

# Sección: carriles de 3,50 m. Carril D = derecha en sentido de PK creciente.
ANCHO_CARRIL = 3.50
# Dónde se coloca la franja de fresado dentro del carril cuando su ancho < 3,50 m:
#  'exterior' -> desde el borde de calzada hacia el eje (rodada exterior, lo habitual)
#  'eje'      -> desde el eje hacia fuera
FRANJA_DESDE = 'exterior'
PASO_M = 2.0                # densificación de los polígonos

# Planos
CREAR_PLANOS = True         # composición con atlas + PDF
HOJA_M = 500                # longitud de carretera por hoja (m). 500 m ≈ 1:1.350 en A3
FORMATO = 'A3'              # 'A3' o 'A4' (apaisado)
ANADIR_PNOA = True          # añade la ortofoto PNOA (WMS del IGN) si no hay una capa 'PNOA'
EXPORTAR_PDF = True         # <CARPETA>/planos_fresado_HU5401.pdf


# ----------------------------------------------------------------------------
def _carpeta():
    if CARPETA:
        return CARPETA
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        raise Exception('Indica CARPETA (ruta donde están los CSV).')


def _capa(nombre_o_ruta):
    capas = QgsProject.instance().mapLayersByName(nombre_o_ruta)
    if capas:
        return capas[0]
    lyr = QgsVectorLayer(nombre_o_ruta, os.path.basename(nombre_o_ruta), 'ogr')
    if not lyr.isValid():
        raise Exception(f'No encuentro la capa "{nombre_o_ruta}"')
    return lyr


def _eje_unico(lyr):
    geoms = [f.geometry() for f in lyr.getFeatures() if not f.geometry().isEmpty()]
    g = QgsGeometry.unaryUnion(geoms) if len(geoms) > 1 else geoms[0]
    g = g.mergeLines() if g.isMultipart() else g
    if g.isMultipart():
        partes = sorted(g.asGeometryCollection(), key=lambda x: -x.length())
        print(f'AVISO: el eje tiene {len(partes)} partes inconexas; uso la más larga '
              f'({partes[0].length():.0f} m). Revisa el eje.')
        g = partes[0]
    if INVERTIR_EJE:
        g = QgsGeometry(g.constGet().reversed())
    return g


class Calibracion:
    """Convierte PK de hito (km) en distancia a lo largo del eje (m)."""

    def __init__(self, eje, eje_lyr):
        self.eje = eje
        self.pares = None
        if HITOS_CAPA:
            hl = _capa(HITOS_CAPA)
            pares = []
            for f in hl.getFeatures():
                pk = float(f[HITOS_CAMPO])
                pk = pk / 1000 if pk > 100 else pk
                pares.append((pk, eje.lineLocatePoint(f.geometry())))
            self.pares = sorted(pares)
            self.modo = f'hitos ({len(pares)} puntos)'
        elif USAR_M and QgsWkbTypes.hasM(eje_lyr.wkbType()):
            pares, d = [], 0.0
            verts = list(eje.vertices())
            for i, v in enumerate(verts):
                if i:
                    d += math.hypot(v.x() - verts[i - 1].x(), v.y() - verts[i - 1].y())
                pares.append(((v.m() / 1000) if M_EN_METROS else v.m(), d))
            self.pares = sorted(pares)
            self.modo = 'valores M del eje'
        else:
            self.modo = f'distancia sobre el eje (origen {PK_ORIGEN_M} m)'
        if self.pares:
            difs = [b[1] - a[1] for a, b in zip(self.pares, self.pares[1:])]
            if any(x <= 0 for x in difs):
                raise Exception('La calibración no es monótona: revisa INVERTIR_EJE o los hitos.')

    def dist(self, pk):
        if not self.pares:
            return pk * 1000 - PK_ORIGEN_M
        p = self.pares
        if pk <= p[0][0]:
            (k0, d0), (k1, d1) = p[0], p[1]
        elif pk >= p[-1][0]:
            (k0, d0), (k1, d1) = p[-2], p[-1]
        else:
            i = next(i for i in range(1, len(p)) if p[i][0] >= pk)
            (k0, d0), (k1, d1) = p[i - 1], p[i]
        return d0 + (pk - k0) * (d1 - d0) / (k1 - k0)


def _punto_desplazado(eje, d, off):
    """Punto a distancia d del origen del eje, desplazado off m (+izq, -dcha)."""
    d = min(max(d, 0.0), eje.length())
    p = eje.interpolate(d).asPoint()
    a = eje.interpolateAngle(d)          # radianes, horario desde el norte
    return QgsPointXY(p.x() - off * math.cos(a), p.y() + off * math.sin(a))


def _franja(eje, d0, d1, off_a, off_b):
    n = max(2, int(math.ceil((d1 - d0) / PASO_M)) + 1)
    ds = [d0 + (d1 - d0) * i / (n - 1) for i in range(n)]
    lado_a = [_punto_desplazado(eje, d, off_a) for d in ds]
    lado_b = [_punto_desplazado(eje, d, off_b) for d in reversed(ds)]
    return QgsGeometry.fromPolygonXY([lado_a + lado_b + [lado_a[0]]])


def _linea(eje, d0, d1, off):
    n = max(2, int(math.ceil((d1 - d0) / PASO_M)) + 1)
    return QgsGeometry.fromPolylineXY(
        [_punto_desplazado(eje, d0 + (d1 - d0) * i / (n - 1), off) for i in range(n)])


def _signo(carril):
    return -1.0 if carril == 'D' else 1.0


def _leer(nombre):
    with open(os.path.join(_carpeta(), nombre), newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _capa_memoria(tipo, crs, campos):
    lyr = QgsVectorLayer(f'{tipo}?crs={crs.authid()}', 'tmp', 'memory')
    flds = QgsFields()
    for nombre, t in campos:
        flds.append(QgsField(nombre, t))
    lyr.dataProvider().addAttributes(flds)
    lyr.updateFields()
    return lyr


def _guardar(lyr, gpkg, nombre, primera):
    opt = QgsVectorFileWriter.SaveVectorOptions()
    opt.driverName = 'GPKG'
    opt.layerName = nombre
    opt.actionOnExistingFile = (QgsVectorFileWriter.CreateOrOverwriteFile if primera
                                else QgsVectorFileWriter.CreateOrOverwriteLayer)
    res = QgsVectorFileWriter.writeAsVectorFormatV3(lyr, gpkg, QgsCoordinateTransformContext(), opt)
    if res[0] != QgsVectorFileWriter.NoError:
        raise Exception(f'Error guardando {nombre}: {res}')
    return QgsVectorLayer(f'{gpkg}|layername={nombre}', nombre, 'ogr')


def _pk(pk):
    m = int(round(pk * 1000))
    return f'{m // 1000}+{m % 1000:03d}'


def _num(x, dec=1):
    return f'{x:,.{dec}f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


def _etiquetas(lyr, expr, size=8, color='#0b0b0b', fondo=None, placement=None, escala_max=None):
    pal = QgsPalLayerSettings()
    pal.fieldName = expr
    pal.isExpression = True
    if placement is not None:
        pal.placement = placement
    fmt = QgsTextFormat()
    f = QFont('Arial')
    f.setBold(True)
    fmt.setFont(f)
    fmt.setSize(size)
    fmt.setColor(QColor(color))
    buf = QgsTextBufferSettings()
    buf.setEnabled(True)
    buf.setSize(0.8)
    buf.setColor(QColor('white'))
    fmt.setBuffer(buf)
    if fondo:
        bg = QgsTextBackgroundSettings()
        bg.setEnabled(True)
        bg.setFillColor(QColor(fondo))
        bg.setStrokeColor(QColor('#0b0b0b'))
        bg.setStrokeWidth(0.2)
        bg.setSizeType(QgsTextBackgroundSettings.SizeBuffer)
        bg.setSize(QSizeF(1.0, 0.6))
        fmt.setBackground(bg)
        buf.setEnabled(False)
        fmt.setBuffer(buf)
    pal.setFormat(fmt)
    if escala_max:
        pal.scaleVisibility = True
        pal.minimumScale = escala_max      # no etiquetar más allá de 1:escala_max
        pal.maximumScale = 0
    lyr.setLabeling(QgsVectorLayerSimpleLabeling(pal))
    lyr.setLabelsEnabled(True)


def _estilos(defl, zonas, tramos, hitos, hojas):
    # Deflexiones: reglas por rango + puntos singulares destacados
    raiz = QgsRuleBasedRenderer.Rule(None)
    for lo, hi, col, et in ((0, 100, '#1a9850', 'Deflexión < 100'),
                            (100, 120, '#fee08b', 'Deflexión 100–120'),
                            (120, 150, '#fc8d59', 'Deflexión 120–150'),
                            (150, 999, '#d73027', 'Deflexión ≥ 150')):
        sym = QgsMarkerSymbol.createSimple({'name': 'circle', 'color': col, 'size': '1.8',
                                            'outline_color': '#404040', 'outline_width': '0.1'})
        raiz.appendChild(QgsRuleBasedRenderer.Rule(
            sym, filterExp=f'"deflexion" >= {lo} AND "deflexion" < {hi}', label=et))
    sym = QgsMarkerSymbol.createSimple({'name': 'star', 'color': '#d73027', 'size': '4.5',
                                        'outline_color': '#000000', 'outline_width': '0.3'})
    raiz.appendChild(QgsRuleBasedRenderer.Rule(sym, filterExp='"singular_gya" = 1',
                                               label='Punto singular (informe GYA)'))
    defl.setRenderer(QgsRuleBasedRenderer(raiz))
    _etiquetas(defl, 'CASE WHEN "singular_gya" = 1 THEN "pk_txt" || \'  (\' || "deflexion" || \')\' END',
               size=7, color='#a50026')

    # Zonas de fresado
    cats = []
    for val, col, et in (('D', '#e31a1c', 'Fresado carril D (→ Paymogo)'),
                         ('I', '#ff7f00', 'Fresado carril I (→ Puebla de Guzmán)')):
        c = QColor(col)
        c.setAlpha(150)
        sym = QgsFillSymbol.createSimple({'color': f'{c.red()},{c.green()},{c.blue()},150',
                                          'outline_color': col, 'outline_width': '0.5'})
        cats.append(QgsRendererCategory(val, sym, et))
    zonas.setRenderer(QgsCategorizedSymbolRenderer('carril', cats))
    _etiquetas(zonas, '"id"', size=8, color='#7f0000', placement=QgsPalLayerSettings.AroundPoint)

    # Tramos km/carril del proyecto (desactivada por defecto en el mapa)
    tramos.setRenderer(QgsCategorizedSymbolRenderer('carril', [
        QgsRendererCategory('D', QgsLineSymbol.createSimple({'color': '#e31a1c', 'width': '0.3',
                                                             'line_style': 'dash'}), 'Tramo proyecto D'),
        QgsRendererCategory('I', QgsLineSymbol.createSimple({'color': '#ff7f00', 'width': '0.3',
                                                             'line_style': 'dash'}), 'Tramo proyecto I')]))

    # Hitos
    hitos.setRenderer(QgsRuleBasedRenderer(QgsMarkerSymbol.createSimple(
        {'name': 'square', 'color': '#ffff00', 'size': '3', 'outline_color': '#000000',
         'outline_width': '0.3'})))
    _etiquetas(hitos, "'km ' || left(\"hito\", strpos(\"hito\", '+') - 1)", size=10,
               fondo='#ffff00', placement=QgsPalLayerSettings.OverPoint)

    # Hojas
    # (no se dibujan en el mapa principal de los planos, solo en el de situación)
    raiz = QgsRuleBasedRenderer.Rule(None)
    raiz.appendChild(QgsRuleBasedRenderer.Rule(QgsFillSymbol.createSimple(
        {'color': '0,0,0,0', 'outline_color': '#2a78d6', 'outline_width': '0.4',
         'outline_style': 'dash'}), filterExp="coalesce(@map_id, '') <> 'mapa'", label='Hoja'))
    hojas.setRenderer(QgsRuleBasedRenderer(raiz))


def _hojas(eje, cal, crs, zonas_csv, tramos_csv):
    lyr = _capa_memoria('Polygon', crs, [('hoja', QVariant.Int), ('pk_ini', QVariant.Double),
                                         ('pk_fin', QVariant.Double), ('titulo', QVariant.String),
                                         ('resumen', QVariant.String), ('rot', QVariant.Double)])
    n = int(math.ceil(17.25 / (HOJA_M / 1000)))
    feats = []
    for h in range(n):
        k0, k1 = h * HOJA_M / 1000, min((h + 1) * HOJA_M / 1000, 17.25)
        d0, d1 = cal.dist(k0), cal.dist(k1)
        g = _franja(eje, d0, d1, 25, -25)
        lineas = []
        for c in ('D', 'I'):
            zs = [z for z in zonas_csv if z['carril'] == c
                  and float(z['pk_fin']) > k0 and float(z['pk_ini']) < k1]
            sup = sum(float(z['superficie_m2']) for z in zs)
            lineas.append(f'Carril {c}: {len(zs)} zonas · {_num(sup, 0)} m²')
        kms = sorted({int(k0), int(min(k1, 17.2499))})
        for k in kms:
            ts = {t['carril']: t for t in tramos_csv if int(float(t['pk_ini'])) == k}
            lineas.append(f'Proyecto km {k}+000: D {_num(float(ts["D"]["longitud_m"]), 0)} m × '
                          f'{_num(float(ts["D"]["ancho_m"]))} · I {_num(float(ts["I"]["longitud_m"]), 0)} m × '
                          f'{_num(float(ts["I"]["ancho_m"]))}')
        f = QgsFeature(lyr.fields())
        f.setGeometry(g)
        # giro del mapa para que la carretera quede horizontal con el PK creciendo a la derecha
        p0, p1 = eje.interpolate(d0).asPoint(), eje.interpolate(d1).asPoint()
        azimut = math.degrees(math.atan2(p1.x() - p0.x(), p1.y() - p0.y()))
        f.setAttributes([h + 1, k0, k1, f'PK {_pk(k0)} a {_pk(k1)}', '\n'.join(lineas),
                         round(90 - azimut, 2)])
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    return lyr


def _anadir_pnoa(crs):
    if QgsProject.instance().mapLayersByName('PNOA'):
        return
    uri = (f'contextualWMSLegend=0&crs={crs.authid()}&dpiMode=7&featureCount=10&format=image/jpeg'
           '&layers=OI.OrthoimageCoverage&styles=&url=https://www.ign.es/wms-inspire/pnoa-ma')
    r = QgsRasterLayer(uri, 'PNOA', 'wms')
    if r.isValid():
        QgsProject.instance().addMapLayer(r, False)
        QgsProject.instance().layerTreeRoot().addLayer(r)   # al final = debajo de todo
    else:
        print('AVISO: no se pudo cargar la PNOA (¿sin conexión?). Los planos saldrán sin ortofoto.')


def _crear_planos(capas, eje, nombre='Planos fresado HU-5401'):
    defl, zonas, tramos, hitos, hojas = capas
    proj = QgsProject.instance()
    mgr = proj.layoutManager()
    viejo = mgr.layoutByName(nombre)
    if viejo:
        mgr.removeLayout(viejo)
    lay = QgsPrintLayout(proj)
    lay.initializeDefaults()
    lay.setName(nombre)
    mgr.addLayout(lay)
    pag = lay.pageCollection().page(0)
    pag.setPageSize(FORMATO, QgsLayoutItemPage.Landscape)
    W, H = pag.pageSize().width(), pag.pageSize().height()
    k = W / 420.0                       # escala de maquetación respecto a A3
    mm = QgsUnitTypes.LayoutMillimeters

    def colocar(item, x, y, w, h):
        item.attemptMove(QgsLayoutPoint(x * k, y * k, mm))
        item.attemptResize(QgsLayoutSize(w * k, h * k, mm))
        lay.addLayoutItem(item)

    def texto(t, x, y, w, h, size, bold=False, color='#0b0b0b'):
        lb = QgsLayoutItemLabel(lay)
        lb.setText(t)
        fmt = QgsTextFormat()
        f = QFont('Arial')
        f.setBold(bold)
        fmt.setFont(f)
        fmt.setSize(size * k)
        fmt.setColor(QColor(color))
        lb.setTextFormat(fmt)
        colocar(lb, x, y, w, h)
        return lb

    atlas = lay.atlas()
    atlas.setCoverageLayer(hojas)
    atlas.setEnabled(True)
    atlas.setHideCoverage(False)
    atlas.setPageNameExpression("'H' || lpad(\"hoja\", 2, '0')")
    atlas.setFilenameExpression("'HU5401_hoja_' || lpad(\"hoja\", 2, '0')")
    n = hojas.featureCount()

    texto('HU-5401 · Rehabilitación del firme PP.KK. 0+000 a 17+250 · Fresado y reposición (5 cm AC16 surf)',
          10, 6, 300, 8, 13, True)
    texto(f'[% "titulo" %]   ·   Hoja [% "hoja" %] de {n}', 10, 14, 300, 7, 11, True, '#2a78d6')
    texto('Zonas propuestas a partir del ensayo HWD (GYA, jul-2025) repartiendo la medición del proyecto '
          'por km y carril. COMPROBAR EN CAMPO.', 230, 7, 180, 12, 7.5, False, '#52514e')

    mapa = QgsLayoutItemMap(lay)
    mapa.setFrameEnabled(True)
    colocar(mapa, 10, 22, 400, 105)
    mapa.zoomToExtent(hojas.extent())
    mapa.setAtlasDriven(True)
    mapa.setAtlasScalingMode(QgsLayoutItemMap.Auto)
    mapa.setAtlasMargin(0.08)
    mapa.setId('mapa')
    mapa.dataDefinedProperties().setProperty(QgsLayoutObject.MapRotation,
                                             QgsProperty.fromExpression('"rot"'))

    vista = QgsLayoutItemMap(lay)
    vista.setFrameEnabled(True)
    colocar(vista, 285, 136, 125, 30)
    vista.setId('vista')
    vista.setLayers([hojas])
    vista.setKeepLayerSet(True)
    g = QgsGeometry.unaryUnion([f.geometry() for f in hojas.getFeatures()]).boundingBox()
    g.scale(1.05)
    vista.zoomToExtent(g)
    vista.overview().setLinkedMap(mapa)
    texto('Situación de la hoja', 285, 166.5, 125, 4, 7, False, '#52514e')

    ley = QgsLayoutItemLegend(lay)
    ley.setTitle('')
    ley.setLinkedMap(mapa)
    ley.setAutoUpdateModel(False)
    raiz = ley.model().rootGroup()
    raiz.removeAllChildren()
    for l in (zonas, defl, hitos):
        raiz.addLayer(l)
    for estilo, tam in ((QgsLegendStyle.Title, 10), (QgsLegendStyle.Group, 8),
                        (QgsLegendStyle.Subgroup, 8), (QgsLegendStyle.SymbolLabel, 7.5)):
        st = QgsLegendStyle(ley.style(estilo))
        fmt = QgsTextFormat(st.textFormat())
        fmt.setSize(tam * k)
        st.setTextFormat(fmt)
        ley.setStyle(estilo, st)
    ley.setSymbolHeight(3.5 * k)
    ley.setResizeToContents(False)
    colocar(ley, 285, 172, 125, 76)

    texto('[% "resumen" %]', 285, 251, 125, 18, 8, False)

    esc = QgsLayoutItemScaleBar(lay)
    esc.setStyle('Single Box')
    esc.setLinkedMap(mapa)
    esc.setUnits(QgsUnitTypes.DistanceMeters)
    esc.setNumberOfSegments(4)
    esc.setNumberOfSegmentsLeft(0)
    esc.setUnitsPerSegment(25)
    esc.setUnitLabel('m')
    colocar(esc, 285, 274, 80, 12)
    norte = QgsLayoutItemPicture(lay)
    norte.setPicturePath(':/images/north_arrows/layout_default_north_arrow.svg')
    norte.setLinkedMap(mapa)
    norte.setNorthMode(QgsLayoutItemPicture.GridNorth)
    colocar(norte, 394, 270, 14, 18)
    texto('PK creciente →   (izquierda: Puebla de Guzmán · derecha: Paymogo)', 10, 128, 200, 5, 8, True, '#52514e')

    tabla = QgsLayoutItemAttributeTable.create(lay)
    tabla.setVectorLayer(zonas)
    tabla.setFilterToAtlasFeature(True)
    tabla.setMaximumNumberOfFeatures(40)
    cols = []
    for campo, cab, ancho in (('id', 'Zona', 16), ('carril', 'Carril', 12), ('pk_txt', 'PK inicio – fin', 36),
                              ('longitud_m', 'Long. (m)', 17), ('ancho_m', 'Ancho (m)', 17),
                              ('superficie_m2', 'Sup. (m²)', 18), ('defl_max', 'Defl. máx', 16),
                              ('comprobado', 'Comprobado', 22), ('estado_campo', 'Estado / ajuste', 35),
                              ('obs', 'Observaciones', 52)):
        c = QgsLayoutTableColumn(cab)
        c.setAttribute(campo)
        c.setWidth(ancho * k)
        cols.append(c)
    tabla.setColumns(cols)
    orden = QgsLayoutTableColumn()
    orden.setAttribute('pk_ini')
    orden.setSortOrder(Qt.AscendingOrder)
    tabla.setSortColumns([orden])
    tabla.setGridStrokeWidth(0.15)
    tabla.setCellMargin(0.8 * k)
    tabla.setEmptyTableBehavior(QgsLayoutItemAttributeTable.ShowMessage)
    tabla.setEmptyTableMessage('Sin zonas de fresado en esta hoja')
    for attr in ('headerTextFormat', 'contentTextFormat'):
        fmt = getattr(tabla, attr)()
        fmt.setSize(7.5 * k)
        getattr(tabla, 'set' + attr[0].upper() + attr[1:])(fmt)
    lay.addMultiFrame(tabla)
    marco = QgsLayoutFrame(lay, tabla)
    colocar(marco, 10, 136, 268, 154)
    tabla.addFrame(marco)
    return lay


def ejecutar(cargar=True):
    eje_lyr = _capa(EJE)
    crs = eje_lyr.crs()
    if crs.isGeographic():
        raise Exception('El eje debe estar en un SRC proyectado en metros (p.ej. EPSG:25829).')
    eje = _eje_unico(eje_lyr)
    cal = Calibracion(eje, eje_lyr)
    gpkg = SALIDA or os.path.join(_carpeta(), 'hu5401_fresado.gpkg')
    print(f'Eje: {eje.length():.0f} m · calibración: {cal.modo}')
    print(f'PK 0+000 -> {cal.dist(0):.0f} m ; PK 17+250 -> {cal.dist(17.25):.0f} m del inicio del eje')

    # Deflexiones
    D, S = QVariant.Double, QVariant.String
    I = QVariant.Int
    defl = _capa_memoria('Point', crs, [('carril', S), ('pk_hito', D), ('pk_obra', D),
                                        ('deflexion', I), ('singular_gya', I), ('pk_txt', S)])
    feats = []
    for r in _leer('deflexiones_hu5401.csv'):
        pk = float(r['pk_hito_km'])
        f = QgsFeature(defl.fields())
        f.setGeometry(QgsGeometry.fromPointXY(
            _punto_desplazado(eje, cal.dist(pk), _signo(r['carril']) * ANCHO_CARRIL / 2)))
        f.setAttributes([r['carril'], pk, float(r['pk_obra_km']), int(r['deflexion_mm100']),
                         int(r['singular_gya']), _pk(pk)])
        feats.append(f)
    defl.dataProvider().addFeatures(feats)

    # Zonas de fresado
    zonas = _capa_memoria('Polygon', crs, [
        ('id', S), ('carril', S), ('km', I), ('pk_ini', D), ('pk_fin', D), ('longitud_m', D),
        ('ancho_m', D), ('superficie_m2', D), ('defl_max', I), ('defl_media', I),
        ('singular_gya', I), ('area_gis_m2', D), ('pk_txt', S),
        ('comprobado', S), ('estado_campo', S), ('obs', S)])
    feats = []
    for r in _leer('zonas_fresado_propuestas.csv'):
        a = float(r['ancho_m'])
        sg = _signo(r['carril'])
        if FRANJA_DESDE == 'exterior':
            off_a, off_b = sg * (ANCHO_CARRIL - a), sg * ANCHO_CARRIL
        else:
            off_a, off_b = 0.0, sg * a
        g = _franja(eje, cal.dist(float(r['pk_ini'])), cal.dist(float(r['pk_fin'])), off_a, off_b)
        f = QgsFeature(zonas.fields())
        f.setGeometry(g)
        f.setAttributes([r['id'], r['carril'], int(r['km']), float(r['pk_ini']), float(r['pk_fin']),
                         float(r['longitud_m']), a, float(r['superficie_m2']), int(r['defl_max']),
                         int(r['defl_media']), int(r['singular_gya']), round(g.area(), 1),
                         f"{_pk(float(r['pk_ini']))} – {_pk(float(r['pk_fin']))}", '', '', ''])
        feats.append(f)
    zonas.dataProvider().addFeatures(feats)

    # Tramos km/carril del proyecto
    tramos = _capa_memoria('LineString', crs, [
        ('carril', S), ('pk_ini', D), ('pk_fin', D), ('longitud_m', D), ('ancho_m', D),
        ('superficie_m2', D), ('pct_longitud_km', D)])
    feats = []
    for r in _leer('tabla_proyecto_km_carril.csv'):
        f = QgsFeature(tramos.fields())
        f.setGeometry(_linea(eje, cal.dist(float(r['pk_ini'])), cal.dist(float(r['pk_fin'])),
                             _signo(r['carril']) * (ANCHO_CARRIL + 0.5)))
        f.setAttributes([r['carril'], float(r['pk_ini']), float(r['pk_fin']), float(r['longitud_m']),
                         float(r['ancho_m']), float(r['superficie_m2']), float(r['pct_longitud_km'])])
        feats.append(f)
    tramos.dataProvider().addFeatures(feats)

    # Marcas de PK cada 100 m (sin los km)
    marcas = _capa_memoria('Point', crs, [('pk', D), ('pk_txt', S)])
    feats = []
    for i in range(1, 173):
        if i % 10 == 0:
            continue
        pk = i / 10
        f = QgsFeature(marcas.fields())
        f.setGeometry(QgsGeometry.fromPointXY(_punto_desplazado(eje, cal.dist(pk), 0)))
        f.setAttributes([pk, _pk(pk)])
        feats.append(f)
    marcas.dataProvider().addFeatures(feats)

    # Hitos calculados
    hitos = _capa_memoria('Point', crs, [('hito', S), ('dist_eje_m', D)])
    feats = []
    for k in range(18):
        f = QgsFeature(hitos.fields())
        d = cal.dist(float(k))
        f.setGeometry(QgsGeometry.fromPointXY(_punto_desplazado(eje, d, 0)))
        f.setAttributes([f'{k}+000', round(d, 1)])
        feats.append(f)
    hitos.dataProvider().addFeatures(feats)

    hojas = _hojas(eje, cal, crs, _leer('zonas_fresado_propuestas.csv'),
                   _leer('tabla_proyecto_km_carril.csv'))

    salidas = []
    for i, (lyr, nombre) in enumerate(((defl, 'deflexiones_hwd'), (zonas, 'zonas_fresado'),
                                       (tramos, 'tramos_proyecto'), (hitos, 'hitos_calculados'),
                                       (hojas, 'hojas_planos'), (marcas, 'marcas_pk_100m'))):
        salidas.append(_guardar(lyr, gpkg, nombre, i == 0))
    tot = sum(f['area_gis_m2'] for f in salidas[1].getFeatures())
    print(f'{gpkg}: {salidas[1].featureCount()} zonas, {tot:.0f} m² (proyecto 13.674,5 m²), '
          f'{salidas[4].featureCount()} hojas')
    _estilos(*salidas[:5])
    salidas[5].setRenderer(QgsRuleBasedRenderer(QgsMarkerSymbol.createSimple(
        {'name': 'circle', 'color': '#ffffff', 'size': '1.6', 'outline_color': '#0b0b0b', 'outline_width': '0.3'})))
    _etiquetas(salidas[5], '"pk_txt"', size=7, color='#0b0b0b',
               placement=QgsPalLayerSettings.AroundPoint)
    for lyr in salidas:
        lyr.saveStyleToDatabase(lyr.name(), 'HU-5401 fresado', True, '')
    if cargar:
        proj = QgsProject.instance()
        root = proj.layerTreeRoot()
        viejo = root.findGroup('HU-5401 fresado')
        if viejo:
            root.removeChildNode(viejo)
        grupo = root.insertGroup(0, 'HU-5401 fresado')
        titulos = {'deflexiones_hwd': 'Deflexiones HWD (0,01 mm)', 'zonas_fresado': 'Zonas de fresado propuestas',
                   'tramos_proyecto': 'Medición proyecto km/carril', 'hitos_calculados': 'Hitos (calculados)',
                   'hojas_planos': 'Hojas de planos', 'marcas_pk_100m': 'PK cada 100 m'}
        for lyr in (salidas[3], salidas[5], salidas[1], salidas[0], salidas[2], salidas[4]):
            lyr.setName(titulos[lyr.name()])
            proj.addMapLayer(lyr, False)
            nodo = grupo.addLayer(lyr)
            if lyr is salidas[2]:
                nodo.setItemVisibilityChecked(False)
        if ANADIR_PNOA:
            _anadir_pnoa(crs)
        if CREAR_PLANOS:
            lay = _crear_planos(salidas[:5], eje)
            print(f'Composición "{lay.name()}" creada (Proyecto > Composiciones).')
            if EXPORTAR_PDF:
                pdf = os.path.join(os.path.dirname(gpkg), 'planos_fresado_HU5401.pdf')
                res, err = QgsLayoutExporter.exportToPdf(lay.atlas(), pdf,
                                                         QgsLayoutExporter.PdfExportSettings())
                print(f'PDF: {pdf}' if res == QgsLayoutExporter.Success else f'Error PDF: {err}')
    return salidas


if __name__ in ('__main__', '__console__'):
    ejecutar()

"""
HU-5401 · Crea en QGIS las capas de deflexiones y de zonas de fresado/reposición
a partir del eje de la carretera.

Uso: abrir en QGIS > Complementos > Consola de Python > Editor, ajustar la
sección CONFIGURACIÓN y ejecutar. Genera un GeoPackage con:
  - deflexiones_hwd       puntos de ensayo (centro de carril)
  - zonas_fresado         polígonos propuestos (tabla zonas_fresado_propuestas.csv)
  - tramos_proyecto       km/carril con la medición del proyecto (líneas)
  - hitos_calculados      dónde cae cada hito según la calibración (para comprobar)

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
    QgsRendererCategory,
)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor

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


def _estilos(defl, zonas):
    rangos = [(0, 100, '#1a9850', '< 100'), (100, 120, '#fee08b', '100-120'),
              (120, 150, '#fc8d59', '120-150'), (150, 999, '#d73027', '≥ 150')]
    rr = []
    for lo, hi, col, et in rangos:
        s = QgsSymbol.defaultSymbol(defl.geometryType())
        s.setColor(QColor(col))
        s.setSize(2.2)
        rr.append(QgsRendererRange(lo, hi, s, et))
    defl.setRenderer(QgsGraduatedSymbolRenderer('deflexion', rr))
    cats = []
    for val, col, et in (('D', '#e31a1c', 'Carril D (sentido creciente)'),
                         ('I', '#6a3d9a', 'Carril I (sentido decreciente)')):
        s = QgsSymbol.defaultSymbol(zonas.geometryType())
        c = QColor(col)
        c.setAlpha(140)
        s.setColor(c)
        cats.append(QgsRendererCategory(val, s, et))
    zonas.setRenderer(QgsCategorizedSymbolRenderer('carril', cats))


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
                         int(r['singular_gya']), f'{int(pk)}+{round((pk % 1) * 1000):03d}'])
        feats.append(f)
    defl.dataProvider().addFeatures(feats)

    # Zonas de fresado
    zonas = _capa_memoria('Polygon', crs, [
        ('id', S), ('carril', S), ('km', I), ('pk_ini', D), ('pk_fin', D), ('longitud_m', D),
        ('ancho_m', D), ('superficie_m2', D), ('defl_max', I), ('defl_media', I),
        ('singular_gya', I), ('area_gis_m2', D)])
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
                         int(r['defl_media']), int(r['singular_gya']), round(g.area(), 1)])
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

    salidas = []
    for i, (lyr, nombre) in enumerate(((defl, 'deflexiones_hwd'), (zonas, 'zonas_fresado'),
                                       (tramos, 'tramos_proyecto'), (hitos, 'hitos_calculados'))):
        salidas.append(_guardar(lyr, gpkg, nombre, i == 0))
    tot = sum(f['area_gis_m2'] for f in salidas[1].getFeatures())
    print(f'{gpkg}: {salidas[1].featureCount()} zonas, {tot:.0f} m² (proyecto 13.674,5 m²)')
    if cargar:
        _estilos(salidas[0], salidas[1])
        for lyr in reversed(salidas):
            QgsProject.instance().addMapLayer(lyr)
    return salidas


if __name__ in ('__main__', '__console__'):
    ejecutar()

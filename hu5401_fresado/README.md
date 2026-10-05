# HU-5401 · Zonas de fresado y reposición (proyecto 2512-PC)

Este README explica cómo se localizan sobre el eje en QGIS los 13.674,5 m² de fresado y reposición del proyecto, que el proyecto mide por km y carril pero no sitúa en planta. Para ello se usa el ensayo de deflexiones HWD (informe GYA DHU25118, Anejo 3, Apéndice I).

## Ficheros

| Fichero | Contenido |
|---|---|
| `deflexiones_hu5401.csv` | 1.674 ensayos HWD extraídos del Anejo I del informe (833 en el carril D y 841 en el I), con el PK de obra y el **PK de hito** |
| `hitos_en_ensayo_hwd.csv` | PK de obra en el que el equipo marcó cada hito, en cada carril |
| `tabla_proyecto_km_carril.csv` | Medición del proyecto por km y carril, junto con la estadística de deflexiones de ese km |
| `zonas_fresado_propuestas.csv` | 114 zonas propuestas (pk_ini, pk_fin, ancho), con 13.675 m² en total |
| `generar_zonas.py` | Genera las zonas a partir de los CSV |
| `crear_capas_qgis.py` | Script para la consola de Python de QGIS. Con vuestro eje crea el GeoPackage con estilos, un grupo de capas, la composición de planos con atlas y el PDF de planos |
| `listado_campo_fresado_HU5401.pdf` | Listado para imprimir (A4, 5 páginas): zonas por km con casillas OK y una columna para ajustes y observaciones |
| `listado_campo.py` | Genera el listado anterior |
| `perfil_deflexiones_zonas.png` | Perfil de deflexiones con las zonas propuestas |

## Uso en QGIS

1. Carga el eje en un SRC métrico, por ejemplo ETRS89 UTM 29N (EPSG:25829).
2. Abre `crear_capas_qgis.py` en la consola de Python, en el editor, y ajusta la sección CONFIGURACIÓN:
   * `EJE`: nombre de la capa del eje.
   * `INVERTIR_EJE`: el PK 0+000 está en Puebla de Guzmán. Si el eje está digitalizado al revés, ponlo a `True`.
   * Calibración: se recomienda una **capa de puntos de hitos** con su PK (`HITOS_CAPA`). Si el eje ya tiene valores M, puedes usar `USAR_M`. Si no hay ninguna de las dos, el PK se calcula como la distancia sobre el eje.
3. Ejecuta el script. Al terminar tendrás:
   * **El grupo "HU-5401 fresado"** con las capas ya simbolizadas y etiquetadas: hitos, PK cada 100 m, zonas de fresado (rojo para el carril D y naranja para el I), deflexiones por rangos con los puntos singulares marcados con estrella, y hojas de planos. Los estilos van guardados dentro del GeoPackage.
   * **La ortofoto PNOA** (WMS del IGN) por debajo, si no tenías ya una capa llamada "PNOA".
   * **La composición "Planos fresado HU-5401"** (Proyecto > Composiciones). Es un atlas A3 apaisado de 35 hojas de 500 m, aproximadamente a 1:1.350. Cada hoja va girada para que la carretera quede horizontal con el PK creciente hacia la derecha. Incluye la tabla de zonas de la hoja con columnas para apuntar en campo, un mapa de situación, la leyenda, el resumen de la medición del proyecto, la escala y el norte.
   * **El PDF de planos** `planos_fresado_HU5401.pdf`, junto al GeoPackage.
4. Comprueba que los hitos calculados caen sobre los hitos reales de la ortofoto. Si no coinciden, calibra con una capa de hitos (`HITOS_CAPA`) y vuelve a ejecutar el script.

Los campos `comprobado`, `estado_campo` y `obs` de las zonas están vacíos para rellenarlos en campo, por ejemplo con QField, o a mano sobre el plano impreso.

Se ha probado con QGIS 3.34 y un eje sintético. Los carriles quedan en el lado correcto, las geometrías son válidas y el área de las zonas cuadra con la medición.

## Criterio

* La longitud de fresado de cada km y carril es **la del proyecto**. No se cambia la medición, solo se localiza.
* Cada ensayo representa unos 20 m de carril. Primero entran los puntos singulares del informe GYA. Después se escogen los tramos con mayor deflexión media en una ventana de 3 ensayos (unos 60 m), hasta completar la longitud del km.
* El ancho es el del proyecto. Por defecto la franja se coloca desde el borde de la calzada hacia el eje (rodada exterior). Puede cambiarse con `FRANJA_DESDE`.

## Limitaciones (importante)

* **La medición del proyecto no guarda relación con las deflexiones.** La correlación entre la longitud por km y la deflexión media o máxima de ese km está entre −0,3 y +0,1. Las longitudes salen de la inspección visual (estado III), no del HWD. Por eso las zonas propuestas son la mejor hipótesis con datos objetivos, no una reconstrucción de lo que vio el proyectista.
* Las deflexiones son bajas en todo el tramo: media de 0,95 mm y máxima de 1,86 mm, sin ningún punto por encima de 3,00 mm. Detectan debilidad estructural localizada, pero no el deterioro superficial (descarnado, fisuración), que es lo que motiva el fresado.
* Los "PK de obra" del informe HWD se separan de los hitos hasta 320 m al final del carril D. Todo se ha pasado a PK de hito usando las marcas de hito del propio ensayo.
* Se recomienda contrastar las zonas sobre el terreno o con una ortofoto o imagen reciente. La memoria (§5.4) ya prevé que el contratista proponga la disposición definitiva a la Dirección Facultativa.

## Erratas detectadas en el proyecto

* **Mediciones 0102, km 3–4 del carril derecho:** figuran 1.888 m en lugar de 188 m. Por eso la medición suma 85.372,5 m²·cm en vez de 68.372,5 m²·cm, que es lo que da el Anejo 3. Este error se arrastra a la partida 0202 (AC16): 2.014,79 t en lugar de unas 1.613,5 t, con unas **401 t de más**. También afecta a las partidas 0201 y 0203.
* La memoria indica "85.372,50 m²·cm", mientras que el Anejo 3 indica 68.372,50 m²·cm y 13.674,5 m².
* La partida 0203 dice "empleado en AC22 surf S", pero la mezcla proyectada es AC16 surf.
* El estado III es el 10–15 % del tramo según la memoria y el 5–10 % según el Anejo 3. La superficie proyectada equivale al 11,3 %.

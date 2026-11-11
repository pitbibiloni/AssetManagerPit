# AssetManagerPit

**Documentación de usuario --- versión 1.0.0**\
**Autor:** Pit Bibiloni\
**Compatibilidad declarada:** Blender 5.2

AssetManagerPit reúne dos herramientas en un único addon: organización
de assets por catálogo desde el Asset Browser y conexión automática de
texturas para modelos FBX/OBJ.

## 1. Instalación

1.  Abrí Blender 5.2.
2.  Entrá en **Edit \> Preferences**.
3.  Abrí la sección **Get Extensions** y elegí **Install from Disk**
    (según la configuración de Blender, también puede aparecer la opción
    de instalar un addon desde archivo).
4.  Seleccioná `assetmanagerpit.py`.
5.  Activá el addon si Blender no lo activa automáticamente.

La herramienta de texturas aparece en el Viewport 3D, en la barra
lateral (`N`), dentro de la pestaña **AssetManagerPit**. La herramienta
de catálogos se utiliza desde el menú contextual del Asset Browser.

## 2. Texture Connector

### 2.1 Importar modelos

Hay dos formas de importar:

-   **Desde el panel:** abrí el Viewport 3D, presioná `N` y entrá en
    **AssetManagerPit \> Texture Connector**. Usá **Import FBX / OBJ** y
    seleccioná uno o varios archivos.
-   **Drag & drop:** arrastrá archivos FBX u OBJ al Viewport 3D. El
    manejador de archivos del addon importa los archivos y abre la
    confirmación de texturas.

Se pueden importar varios archivos en una misma operación, incluso si
están en carpetas diferentes. El addon guarda las carpetas de origen de
todos los archivos importados en esa tanda y selecciona los objetos
recién importados.

### 2.2 Confirmar conexión de texturas

Después de importar, aparece una ventana:

> Do you wish to import associated textures in the folder?

Al confirmar, el addon busca imágenes en cada carpeta de origen y en
todas sus subcarpetas. No es necesario seleccionar manualmente la
carpeta de texturas.

El botón **Connect Textures** del panel permite repetir la búsqueda para
los objetos seleccionados, usando las carpetas registradas en la última
importación.

### 2.3 Mapas reconocidos

  -----------------------------------------------------------------------
  Tipo de mapa                        Entradas / nodos
  ----------------------------------- -----------------------------------
  Base Color / Albedo / Diffuse /     Base Color del Principled BSDF
  Color                               

  Roughness                           Roughness del Principled BSDF

  Metallic / Metalness                Metallic del Principled BSDF

  Normal                              Nodo Normal Map y entrada Normal

  AO / Occlusion                      Se combina con Base Color mediante
                                      una mezcla Multiply

  Emission / Emissive                 Emission Color (o Emission, según
                                      la versión del nodo)

  Alpha / Opacity / Transparency      Alpha del Principled BSDF

  Height / Displacement / Bump        Nodo Bump conectado a Normal
  -----------------------------------------------------------------------

Extensiones de imagen admitidas: PNG, JPG/JPEG, TIF/TIFF, TGA, BMP, EXR,
HDR y WEBP.

El addon asigna **sRGB** a Base Color y Emission, y **Non-Color** a
mapas de datos como Roughness, Metallic, Normal, AO, Alpha y Height.

### 2.4 Cómo identifica las texturas

El addon analiza los nombres de archivo y reconoce términos habituales y
abreviaturas, por ejemplo:

-   `BaseColor`, `Albedo`, `Diffuse`, `Color`, `D`
-   `Roughness`, `Rough`, `R`
-   `Metallic`, `Metalness`, `Metal`, `M`
-   `Normal`, `NormalGL`, `NormalDX`, `NRM`, `N`
-   `AO`, `Occlusion`
-   `Emission`, `Emissive`, `Emit`
-   `Opacity`, `Alpha`, `Transparency`
-   `Height`, `Bump`, `Displacement`

Para elegir entre imágenes candidatas, compara el nombre del material
con el nombre de la textura. Si no encuentra una coincidencia suficiente
y hay varias candidatas, también intenta comparar con el nombre del
objeto.

**Recomendación:** aunque el reconocimiento admite nombres variados,
usar un identificador común facilita la asociación. Por ejemplo:

``` text
SM_Rock_BaseColor.png
SM_Rock_Roughness.png
SM_Rock_Normal.png
SM_Rock_AO.png
```

### 2.5 Limitaciones y comportamiento

-   Solo importa modelos FBX y OBJ mediante los operadores del addon.
-   La búsqueda se limita a las carpetas de origen de la última
    importación y sus subcarpetas.
-   **Connect Textures** trabaja sobre los objetos seleccionados. Si no
    hay objetos seleccionados, no podrá procesar materiales.
-   Los materiales se procesan una sola vez por nombre durante una
    operación.
-   Si varios materiales tienen nombres genéricos o las carpetas
    contienen varias texturas del mismo tipo sin nombres identificables,
    la asociación puede no ser inequívoca.
-   El mapa AO solo se mezcla con Base Color cuando el material tiene
    una textura Base Color conectada.
-   El addon no promete reconocer cualquier convención de nombres:
    utiliza una lista de términos y abreviaturas incorporada.

Si aparece **No maps could be connected**, verificá que los objetos
importados sigan seleccionados, que las imágenes estén dentro de las
carpetas de origen o sus subcarpetas y que los nombres incluyan términos
reconocibles.

## 3. Asset Catalog Organizer

Esta herramienta permite asignar uno o varios assets seleccionados a un
catálogo existente desde el menú contextual del Asset Browser.

### 3.1 Uso

1.  Abrí el **Asset Browser**.
2.  Seleccioná uno o varios assets.
3.  Hacé clic derecho sobre la selección.
4.  Elegí **Assign to**.
5.  Seleccioná el catálogo de destino. Los catálogos se muestran con su
    ruta completa, por ejemplo `Materials / Rock / Large`.
6.  Confirmá la operación cuando Blender muestre el aviso.

El addon busca el archivo `blender_assets.cats.txt` asociado a la
biblioteca del asset y muestra los catálogos que encuentra allí.

### 3.2 Qué modifica

La operación cambia el catálogo asignado a los assets seleccionados en
sus archivos `.blend` de origen. Para hacerlo, el addon inicia procesos
de Blender en segundo plano, actualiza los datablocks de los assets y
guarda los archivos fuente modificados. Al terminar, intenta refrescar
la biblioteca de assets.

**Importante:** esta operación modifica y guarda los archivos `.blend`
originales de la biblioteca. Hacé una copia de seguridad antes de
asignar assets en lote. Esperá a que termine el proceso antes de
continuar trabajando con esos archivos.

### 3.3 Limitaciones

-   Los assets online/remotos no están soportados.
-   Los assets deben pertenecer a una biblioteca local cuyo archivo
    `.blend` de origen pueda identificarse.
-   El catálogo debe existir en el archivo `blender_assets.cats.txt` de
    esa biblioteca.
-   Si algún archivo fuente falla, el addon informa que hubo errores y
    recomienda revisar la consola de Blender.
-   El addon no crea catálogos nuevos: asigna los assets a catálogos
    existentes.

## 4. Solución de problemas

  -----------------------------------------------------------------------
  Problema                            Qué revisar
  ----------------------------------- -----------------------------------
  No aparece **Assign to**            Confirmá que estás en el Asset
                                      Browser y que hay assets
                                      seleccionados.

  No aparecen catálogos               Revisá que la biblioteca tenga
                                      `blender_assets.cats.txt` y
                                      catálogos definidos.

  La asignación falla                 Confirmá que el archivo `.blend` de
                                      origen existe y puede modificarse.
                                      Revisá la consola.

  No aparece el popup de texturas     Importá mediante **Import FBX /
                                      OBJ** o arrastrá FBX/OBJ
                                      directamente al Viewport 3D.

  No encuentra imágenes               Revisá las carpetas junto a los
                                      modelos y sus subcarpetas, las
                                      extensiones admitidas y los nombres
                                      de mapas.

  Conecta una textura incorrecta      Usá nombres de materiales y
                                      texturas más específicos y
                                      consistentes para evitar candidatos
                                      ambiguos.
  -----------------------------------------------------------------------

## 5. Resumen de funciones

  -----------------------------------------------------------------------
  Herramienta             Ubicación               Función
  ----------------------- ----------------------- -----------------------
  Texture Connector       Viewport 3D \> `N` \>   Importar FBX/OBJ,
                          AssetManagerPit         buscar texturas y
                                                  conectar mapas

  Asset Catalog Organizer Menú contextual del     Asignar assets
                          Asset Browser           seleccionados a
                                                  catálogos existentes
  -----------------------------------------------------------------------

**AssetManagerPit --- Pit Bibiloni**\
Versión documentada: 1.0.0 · Blender 5.2

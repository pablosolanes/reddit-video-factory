# Reddit Video Factory

MVP local en Python para Windows que generara videos verticales a partir de historias de Reddit. El proyecto esta dividido por fases para mantenerlo modular, reanudable y facil de validar.

## Estado Actual

Fase 1 implementada:

- Estructura de carpetas y paquetes Python.
- `config.yaml` con valores iniciales.
- `.env.example` sin secretos.
- SQLite con tablas iniciales.
- Logging en `logs/app.log`.
- CLI ejecutable con `python -m app.main`.

Fase 2 implementada:

- Cliente Reddit de solo lectura mediante PRAW.
- Filtro de duplicados contra SQLite.
- Filtros por score, longitud, posts vacios, eliminados, fijados y spam basico.
- Selector heuristico local por conflicto, curiosidad, tension y potencial narrativo.
- Guardado de historias seleccionadas en `stories` con `internal_score`.

Fase 3 implementada:

- Proveedor `LLMProvider` con implementacion DeepSeek.
- Modelo por defecto `deepseek-v4-flash`.
- Uso de JSON mode para guiones estructurados.
- Cache local por historia/modelo/prompt en `cache/llm`.
- Validacion del JSON generado.
- Guardado en SQLite de `scripts` y `parts`.

Fase 4 implementada:

- Proveedor `TTSProvider` con implementacion local Kokoro.
- Voz configurable en `config.yaml`.
- Cache local WAV por texto/voz/velocidad en `cache/audio`.
- Reutilizacion de audio ya generado.
- Calculo de duracion real del WAV.
- Guardado de `audio_path`, `duration` y estado en `parts`.

Fase 5 implementada:

- Transcripcion local con `faster-whisper`.
- Word timestamps cuando el modelo los devuelve.
- Cache local de transcripciones en `cache/transcripts`.
- Generacion de subtitulos `.ass` estilo TikTok/Reels.
- Guardado de `transcript_path` y `subtitle_path` en `parts`.

Fase 6 implementada:

- Seleccion automatica de fondos locales desde `backgrounds/`.
- Evita repetir el ultimo fondo cuando hay alternativas.
- Render local con FFmpeg a MP4 vertical 1080x1920.
- Loop del fondo para cubrir la duracion del audio.
- Audio AAC, video H.264 y subtitulos ASS quemados en el video.
- Variacion simple de estilos `style_01`, `style_02`, `style_03`.
- Metadata JSON junto al MP4 final.
- Validacion con `ffprobe` de duracion, resolucion, codecs y audio.

Fase 7 implementada:

- Chequeo de dependencias con `--check-deps`.
- Recuperacion automatica de trabajos interrumpidos en estado `processing`.
- Reintento explicito de fallos con `--retry-failed`.
- Documentacion de ejecucion diaria con Windows Task Scheduler.
- Flujo completo reanudable hasta generar MP4 y JSON finales.

Publicacion TikTok anadida al MVP:

- Cliente TikTok por Content Posting API oficial.
- Modo por defecto `upload`, que sube el video como borrador/inbox para terminarlo en TikTok.
- Modo opcional `direct_post`, solo si tu app tiene scope `video.publish` aprobado.
- Tabla `publications` para registrar `publish_id`, plataforma, modo, estado y errores.
- Publicacion/subida solo con `--publish-ready`.
- `publishing.enabled: false` por defecto para evitar subidas accidentales.

Sistema de fondos ampliado:

- Biblioteca local indexada en SQLite con tabla `backgrounds`.
- Registro de filename, filepath, categoria, subcategoria, fuente, autor, licencia, hash, duracion, resolucion y uso.
- Perfil visual unico por historia mediante `visual_profile`.
- Coherencia visual entre partes de la misma historia.
- Selector por categoria/estilo con prioridad a fondos menos usados.
- Interfaces para fuentes y descarga autorizada, desactivadas por defecto.

## Instalacion En Windows

1. Instala Python 3.11 o superior.
2. Crea un entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Instala dependencias:

```powershell
python -m pip install -r requirements.txt
```

4. Crea tu archivo local `.env`:

```powershell
Copy-Item .env.example .env
```

No escribas claves API en el codigo ni subas `.env` a Git.

Nota sobre Kokoro: para TTS local usa Python 3.11 o 3.12 si encuentras problemas con dependencias de audio/modelos en versiones mas nuevas. Este proyecto mantiene Python 3.11+ como objetivo, pero el stack TTS local puede ir por detras del runtime mas reciente.

## Configuracion De Reddit

El MVP usa PRAW con una app externa de Reddit en modo lectura. Necesitas:

- `REDDIT_CLIENT_ID`
- `REDDIT_CLIENT_SECRET`
- `REDDIT_USER_AGENT`

Pasos:

1. Entra con tu cuenta de Reddit.
2. Abre `https://www.reddit.com/prefs/apps`.
3. Crea una app de tipo `script`.
4. Copia el valor corto bajo el nombre de la app como `REDDIT_CLIENT_ID`.
5. Copia `secret` como `REDDIT_CLIENT_SECRET`.
6. Define un user agent descriptivo, por ejemplo:

```text
reddit-video-factory/0.1 by tu_usuario_reddit
```

Ejemplo de `.env`:

```text
DEEPSEEK_API_KEY=
REDDIT_CLIENT_ID=tu_client_id
REDDIT_CLIENT_SECRET=tu_client_secret
REDDIT_USER_AGENT=reddit-video-factory/0.1 by tu_usuario_reddit
TIKTOK_ACCESS_TOKEN=
```

Subreddits activos por defecto:

- `AskReddit`
- `TrueOffMyChest`
- `AmItheAsshole`
- `relationship_advice`
- `tifu`
- `HistoriasDeReddit`

Subreddits opcionales de ficcion/relato:

- `nosleep`
- `WritingPrompts`
- `HFY`

Recomendacion practica: empieza con historias personales (`tifu`, `TrueOffMyChest`, `AmItheAsshole`, `relationship_advice`, `HistoriasDeReddit`) y deja ficcion (`nosleep`, `WritingPrompts`, `HFY`) para pruebas separadas. En ficcion el riesgo de derechos/autoria suele ser mas alto porque son relatos creativos originales, asi que revisa normas del subreddit, permisos y licencia antes de reutilizar o monetizar.

## Configuracion De DeepSeek

Necesitas una API key de DeepSeek:

```text
DEEPSEEK_API_KEY=tu_api_key
```

La configuracion por defecto usa:

```yaml
llm:
  provider: deepseek
  model: deepseek-v4-flash
  base_url: https://api.deepseek.com
```

`deepseek-v4-flash` es el modelo economico recomendado para este MVP. El codigo usa `/chat/completions` con `response_format: {"type": "json_object"}` y prompts que piden JSON explicitamente.

## Configuracion De Kokoro TTS

El proveedor por defecto es local:

```yaml
tts:
  provider: kokoro
  voice: ef_dora
  speed: 1.0
```

Voces espanolas conocidas:

- `ef_dora`: voz femenina en espanol.
- `em_alex`: voz masculina en espanol.
- `em_santa`: voz masculina alternativa en espanol.

En Windows, Kokoro necesita `espeak-ng` para idiomas como espanol:

1. Descarga el instalador MSI desde las releases de `espeak-ng`.
2. Instala la version x64.
3. Cierra y abre de nuevo PowerShell.
4. Comprueba:

```powershell
espeak-ng --version
```

Si Kokoro no inicializa, revisa que `espeak-ng` este disponible en `PATH`.

## Configuracion De Whisper Local

La Fase 5 usa `faster-whisper` local:

```yaml
whisper:
  provider: faster-whisper
  model_size: small
  device: auto
  compute_type: default
  language: es
  beam_size: 5
```

La primera ejecucion puede descargar el modelo si no esta cacheado. Despues, la transcripcion queda cacheada en:

```text
cache/transcripts/
```

Los subtitulos ASS se guardan en:

```text
cache/subtitles/
```

## Configuracion De FFmpeg Y Fondos

Instala FFmpeg para Windows y comprueba que `ffmpeg` y `ffprobe` esten en `PATH`:

```powershell
ffmpeg -version
ffprobe -version
```

Coloca videos de fondo propios o con derechos de uso en:

```text
backgrounds/
  minecraft/
  satisfying/
  gameplay/
  relaxing/
  other/
```

El sistema no descarga fondos de Internet. Usa archivos locales `.mp4`, `.mov`, `.mkv` o `.webm`.

Configuracion relevante:

```yaml
backgrounds:
  directory: backgrounds
  avoid_consecutive_repeats: true
  min_duration_seconds: 30
  min_width: 720
  min_height: 720
  default_category: minecraft
  default_style: parkour

background_download:
  enabled: false
  min_items_per_category: 5
  allowed_sources: []
```

Con `background_download.enabled: false`, el sistema nunca descarga fondos automaticamente. Solo indexa y usa los archivos que coloques manualmente.

## Configuracion De TikTok

TikTok se integra solo mediante API oficial. No se usa Selenium, Playwright ni navegador.

Requisitos:

- Cuenta en TikTok for Developers.
- App registrada.
- Producto Content Posting API anadido a la app.
- Scope `video.upload` aprobado para subir borradores al inbox.
- Scope `video.publish` aprobado si quieres publicacion directa.
- Access token de usuario autorizado con el scope correspondiente.

Configuracion por defecto:

```yaml
publishing:
  enabled: false
  provider: tiktok
  mode: upload
  privacy_level: SELF_ONLY
  is_aigc: true
```

Variable necesaria en `.env`:

```text
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=
```

Para obtener tokens con OAuth local, configura en TikTok Developers este redirect URI:

```text
http://127.0.0.1:8765/callback/
```

Despues ejecuta:

```powershell
python -m app.main --tiktok-login
```

El comando abre el navegador, espera la autorizacion en `127.0.0.1:8765` y muestra las lineas `TIKTOK_ACCESS_TOKEN` y `TIKTOK_REFRESH_TOKEN` para pegarlas en `.env`.

Modo recomendado para el MVP:

```yaml
publishing:
  enabled: true
  mode: upload
```

Este modo sube el video a TikTok como borrador/inbox. Luego terminas la edicion y publicacion desde TikTok.

Para publicacion directa:

```yaml
publishing:
  enabled: true
  mode: direct_post
  privacy_level: SELF_ONLY
```

La publicacion directa requiere scope `video.publish`. TikTok indica que el contenido de clientes no auditados queda restringido a modo privado hasta que la app supere auditoria.

## Uso

Comprobar carga de configuracion, SQLite, logging y flujo de Fase 2:

```powershell
python -m app.main --test --dry-run
```

Comprobar dependencias locales:

```powershell
python -m app.main --check-deps
```

Probar seleccion de fondo local sin descargar:

```powershell
python -m app.main --test-background
```

Probar coherencia visual de una historia multipartes:

```powershell
python -m app.main --test-story
```

Simular el pipeline sin escribir ni gastar API:

```powershell
python -m app.main --count 3 --dry-run
```

Generar 1 video de prueba:

```powershell
python -m app.main --test
```

Generar 3 videos:

```powershell
python -m app.main --count 3
```

Reanudar trabajos incompletos sin volver a buscar Reddit:

```powershell
python -m app.main --resume --count 3
```

Reintentar trabajos fallidos:

```powershell
python -m app.main --resume --retry-failed --count 3
```

Subir/publicar videos ya generados por API oficial:

```powershell
python -m app.main --publish-ready --count 3
```

Generar y luego subir/publicar en una misma ejecucion:

```powershell
python -m app.main --count 3 --publish-ready
```

## Salidas Esperadas Del Smoke Test

El comando `python -m app.main --test --dry-run` debe:

- Cargar `config.yaml`.
- Crear `data/database.db`.
- Crear las tablas `stories`, `scripts`, `parts` y `videos`.
- Crear o usar `logs/app.log`.
- Intentar preparar la busqueda de Reddit.
- Mostrar `[PHASE 6] OK` o `[PHASE 7] OK` segun el flujo disponible.

## Salidas Esperadas En Fase 2

Con credenciales de Reddit configuradas, el comando debe:

- Buscar en los subreddits de `config.yaml`.
- Filtrar historias ya existentes en SQLite.
- Mostrar candidatas encontradas.
- Mostrar historias seleccionadas por el selector.
- En modo normal, guardar las historias en `data/database.db`.
- Mostrar `[PHASE 2] OK`.

## Salidas Esperadas En Fase 3

Con historias pendientes y `DEEPSEEK_API_KEY` configurada, el comando debe:

- Leer historias `pending` desde SQLite.
- Reutilizar `cache/llm/*.json` si existe.
- Llamar a DeepSeek solo si no hay cache valida.
- Validar que el resultado tenga `title`, `hook`, `script`, `description`, `hashtags` y `parts`.
- Guardar el guion en `scripts`.
- Guardar cada parte en `parts`.
- Marcar la historia como `completed` si el guion se guarda correctamente.
- Mostrar `[PHASE 3] OK`.

## Salidas Esperadas En Fase 4

Con partes pendientes, Kokoro instalado y `espeak-ng` disponible, el comando debe:

- Leer partes `pending` desde SQLite.
- Crear o reutilizar WAV en `cache/audio`.
- Calcular la duracion real del audio.
- Actualizar `parts.audio_path`, `parts.duration` y `parts.status`.
- Mostrar `[PHASE 4] OK`.

## Salidas Esperadas En Fase 5

Con partes que ya tengan `audio_path`, el comando debe:

- Transcribir audio localmente con Whisper.
- Reutilizar `cache/transcripts/*.json` si existe.
- Crear un `.ass` en `cache/subtitles`.
- Actualizar `parts.transcript_path` y `parts.subtitle_path`.
- Mostrar `[PHASE 5] OK`.

## Salidas Esperadas En Fase 6

Con partes que ya tengan `audio_path` y `subtitle_path`, el comando debe:

- Seleccionar un fondo local valido desde `backgrounds/`.
- Renderizar un MP4 vertical H.264/AAC.
- Validar el MP4 con `ffprobe`.
- Crear `output/YYYY-MM-DD/video_001.mp4`.
- Crear `output/YYYY-MM-DD/video_001.json`.
- Registrar el resultado en `videos`.
- Mostrar `[PHASE 6] OK`.

## Salidas Esperadas En Fase 7

El comando `python -m app.main --check-deps` debe mostrar:

- Paquetes Python disponibles o pendientes.
- Estado de `ffmpeg`, `ffprobe` y `espeak-ng`.
- Si las variables de `.env` estan configuradas, sin imprimir secretos.

El comando `python -m app.main --resume --retry-failed --count 3` debe:

- Resetear trabajos interrumpidos.
- Reintentar historias/partes/videos fallidos.
- Reutilizar cache existente siempre que sea valido.
- Continuar desde el siguiente paso incompleto.

Con `publishing.enabled: true` y `--publish-ready`, el sistema debe:

- Leer videos `completed` no publicados desde SQLite.
- Inicializar subida/publicacion en TikTok.
- Subir el MP4 por `FILE_UPLOAD`.
- Guardar `publish_id` en `publications`.
- Marcar estado `uploaded` en modo `upload` o `published` en modo `direct_post`.

## Carpetas Principales

- `backgrounds/`: videos de fondo colocados manualmente por el usuario.
- `cache/`: resultados reutilizables de LLM, audio y transcripciones.
- `data/`: base de datos SQLite local.
- `logs/`: logs de ejecucion.
- `output/`: MP4 finales y metadata JSON.

## Aviso Legal Y De Contenido

Las publicaciones de Reddit no son automaticamente contenido libre de derechos. El usuario debe comprobar derechos, permisos, licencias y politicas de las plataformas antes de publicar o monetizar.

No se debe descargar automaticamente contenido multimedia de terceros. Usa fondos sobre los que tengas derechos de uso.

## Windows Task Scheduler

Para ejecutar 3 videos una vez al dia:

1. Abre `Task Scheduler`.
2. Selecciona `Create Basic Task`.
3. Nombre: `Reddit Video Factory Daily`.
4. Trigger: `Daily`.
5. Action: `Start a program`.
6. Program/script:

```text
C:\Users\JuanluTec\OneDrive\Escriptori\Proyectos\Tiktok-Stories\.venv\Scripts\python.exe
```

Si no usas virtualenv, usa el resultado de:

```powershell
where python
```

7. Add arguments:

```text
-m app.main --count 3
```

8. Start in:

```text
C:\Users\JuanluTec\OneDrive\Escriptori\Proyectos\Tiktok-Stories
```

9. Guarda la tarea.

Para una tarea mas tolerante a fallos, usa:

```text
-m app.main --resume --retry-failed --count 3
```

Antes de programarla, ejecuta manualmente:

```powershell
python -m app.main --check-deps
python -m app.main --test
```

## Estado Final Del MVP

El MVP local queda completo por fases. No publica automaticamente y deja los MP4 con metadata JSON en `output/YYYY-MM-DD/` para revision y subida manual.

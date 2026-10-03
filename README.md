# ColorCorrection

## Готовое приложение ColorPro

[Скачать установщики и обновления](https://github.com/babkanomer13-dotcom/colorcorrection/releases/latest).
ColorPro — отдельная настольная оболочка сохранённой V39: Windows 10/11 x64
(автовыбор совместимой NVIDIA CUDA или CPU) и Windows 7 SP1 x64 (CPU).
Python, библиотеки и веса включены в полный офлайн-установщик.
Фотографии обрабатываются локально, без интернета.

В 1.4.0 полностью обновлён интерфейс: миниатюры и счётчики в очереди,
отдельная страница «До / после», светлые настройки, новая боковая панель и логотип.
Внизу панели — локальный профиль с именем; «Помощь» находится под «Обновлениями».

- С версии 1.3.1 для нового ПК скачайте **один `Win10-x64-Offline.exe`** — полный
  комплект без докачек, дисков и BIN. Повторный запуск не заменяет совпадающие файлы.
- Windows 7: отдельный `Win7-x64-Offline.exe`. Проверка именно на реальной Windows 7
  пока не выполнена; библиотеки прошли статический аудит, приложение — тесты на Windows 10.
- В установленной 1.1.0 и новее используйте «Обновления»: скачивается только
  компактный пакет изменённых файлов, **без повторной загрузки модели и библиотек**.
  Проверяются SHA-256, целостность компонентов и канал Windows. Установка — по нажатию.
- Маленький `Setup.exe` — только обновление, не установщик для нового ПК.
  Он никогда не скачивает и не переустанавливает полный комплект компонентов.
- V39 неизменна; JPEG — 100%, 4:4:4; PNG — без потерь. Настройки и фотографии сохраняются.
- Установщики пока без цифровой подписи. Не отключайте защиту Windows.

Инструкции и выпуск новых версий: [colorpro/RELEASES.txt](colorpro/RELEASES.txt).
Правила RTX 3090 и обучения **ниже относятся к исследовательскому pipeline**, не к
настольному ColorPro. Исходники приложения и проверки находятся в `colorpro/`;
фотографии и состояние обучения в публичные коммиты не включаются.

## Исследовательский pipeline

Локальный, негенеративный pipeline для обучения цветокоррекции по доверенным парам
`BEFORE -> TARGET` и применения обученной модели к новым фотографиям. Проект ищет один и
тот же кадр до и после авторской обработки, строит проверяемый paired dataset, анализирует
цветовые преобразования, обучает image-conditioned adaptive 3D LUT и оценивает его только на
отложенных съёмках.

Модель меняет цвет и тон, но не генерирует содержание, не ретуширует объекты и не должна менять
геометрию изображения. Обучение, evaluation и AI-inference выполняются локально и строго на
NVIDIA GeForce RTX 3090.

## Основные гарантии

- Архив фотографий считается read-only. В него нельзя записывать SQLite, кэши, manifests,
  previews, checkpoints или результаты inference.
- Точность matching важнее полноты. Имя файла — только слабый дополнительный сигнал; решение
  подтверждается perceptual hashes, локальными признаками, двунаправленным matching и RANSAC.
- В dataset попадают только пары со статусом `MATCHED`, прошедшие отдельную проверку геометрии.
  `UNCERTAIN` и `UNMATCHED` остаются для аудита и не используются при обычном обучении.
- Split выполняется целыми группами `season / shoot / context`. Кадры одной съёмки не
  разделяются между `train`, `val` и `test`.
- Production-код не имеет CPU fallback и не переключается на другую видеокарту. Если RTX 3090
  нельзя однозначно выбрать, команда завершается ошибкой до начала CUDA-работы.
- Реальные фотографии, manifests с локальными путями, SQLite, reports, логи, веса и секреты не
  должны попадать в публичный Git-репозиторий.

## Конвейер

```text
read-only archive
       |
       v
scan -> conservative matching -> validation + grouped split
                                      |
                                      +-> analysis + deterministic baselines
                                      |
                                      +-> adaptive LUT training -> held-out evaluation
                                                                    |
                                                                    +-> local inference
                                                                    +-> visual QA report
```

Все стрелки после архива ведут во внешнее приватное хранилище. Dataset является
`manifest-only`: фотографии не копируются и не переписываются.

## Структура архива

Scanner определяет роли по структуре реального workflow:

| Признак | Роль |
| --- | --- |
| каталог, где `дубли` является отдельным словом (`дубли`, `дубли 2`, `восп дубли`, ...) | `before` |
| файл непосредственно в каталоге с дочерней стадией `PP` | `after` |
| любой файл внутри `PP`, включая вложенные каталоги со словом `дубли` | исключается |

Для `after` одного похожего имени папки недостаточно: дочерний `PP` является обязательным
структурным подтверждением. В CLI необходимо передать ровно три season-каталога внутри одного
archive root.

Scanner индексирует обычные raster-форматы, PSD и ряд camera/HEIF-контейнеров. Фактическое
декодирование зависит от возможностей установленного Pillow; неподдерживаемый или повреждённый
файл сохраняется в индексе вместе с диагностикой. XMP и другие sidecar-файлы намеренно не
считаются изображениями.

## Установка на Windows

Требования:

- Windows и PowerShell;
- Python 3.10 или новее;
- Git;
- актуальный NVIDIA driver;
- CUDA-enabled сборка PyTorch, видящая RTX 3090.

Из корня клонированного репозитория:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

Сначала установите совместимую CUDA-enabled сборку `torch` и `torchvision` командой из
[официального PyTorch selector](https://pytorch.org/get-started/locally/). Затем установите
проект с training- и dev-зависимостями:

```powershell
python -m pip install -e ".[dev,training]"
```

Если нужны только scan/match/dataset/analyze/report без AI training и inference:

```powershell
python -m pip install -e ".[dev]"
```

Проверка PyTorch и видимых устройств:

```powershell
python -c "import torch; print('torch', torch.__version__); print('CUDA build', torch.version.cuda); print('CUDA available', torch.cuda.is_available()); [print(i, torch.cuda.get_device_name(i)) for i in range(torch.cuda.device_count())]"
python -c "from colorcorrection.gpu import describe_cuda_devices; print(describe_cuda_devices())"
```

## Разделение архива и приватных результатов

Ниже используются только параметризованные PowerShell-переменные. Задайте реальный archive
root локально и создайте приватную рабочую директорию рядом с репозиторием:

```powershell
$env:CC_ARCHIVE = "<archive-root>"
$env:CC_PRIVATE = Join-Path (Split-Path -Parent (Get-Location)) "colorcorrection-private"
$seasons = @("<season-1>", "<season-2>", "<season-3>")

$privateDirectories = @(
  "indexes", "cache", "matcher-manifests", "datasets", "analysis",
  "runs", "evaluations", "comparisons", "error-analysis", "reports", "outputs", "weights"
)
$privateDirectories | ForEach-Object {
  New-Item -ItemType Directory -Force -Path (Join-Path $env:CC_PRIVATE $_) | Out-Null
}
```

Не направляйте `$env:CC_PRIVATE` внутрь `$env:CC_ARCHIVE`. Рекомендуется также держать его вне
Git working tree. Manifests и reports могут содержать абсолютные локальные пути и производные
previews, поэтому они остаются приватными даже без оригиналов.

## Политика RTX 3090

Строгий выбор устройства применяется в `train`, `evaluate`, formal `compare`, CLI inference и в
публичном классе `ColorCorrection`:

- одна видимая RTX 3090 выбирается автоматически;
- `--cuda-index N` выбирает индекс явно, но имя устройства всё равно проверяется;
- альтернативно можно задать `COLORCORRECTION_CUDA_INDEX`;
- индекс любой другой GPU, отсутствие CUDA или отсутствие RTX 3090 приводят к ошибке;
- несколько видимых RTX 3090 требуют явного индекса;
- multi-GPU и CPU fallback отсутствуют.

Пример явной настройки после проверки inventory:

```powershell
$env:COLORCORRECTION_CUDA_INDEX = "<cuda-index-of-rtx-3090>"
```

Scan, matching, validation, analysis и сборка статического report являются CPU-этапами. Перед
training/evaluation/inference дополнительно проверьте свободную память командой `nvidia-smi` и
не запускайте новый процесс поверх чужой GPU-задачи.

## 1. Индексация архива

Полный scan вычисляет размеры, безопасную EXIF-сводку, ICC fingerprint, быстрый file fingerprint
и perceptual hashes. Не используйте `--metadata-only` для production matching: этот флаг пропускает
content fingerprint и perceptual hashes.

```powershell
$indexDatabase = Join-Path $env:CC_PRIVATE "indexes\archive.sqlite3"

python -m colorcorrection.cli_scan `
  --archive-root $env:CC_ARCHIVE `
  --seasons $seasons `
  --database $indexDatabase `
  --workers 12 `
  --commit-every 250
```

Scanner фиксирует checkpoint в SQLite каждые `--commit-every` файлов и печатает progress JSON в
`stderr`. После прерывания повторите ту же команду: неизменившиеся файлы переиспользуются по
размеру и времени изменения, а незавершённый run не выдаётся за completed. Ошибки отдельных
декодеров сохраняются для аудита; исходные файлы не изменяются.

Роли в архиве определяются по реальному производственному workflow. RAW находится в ближайшей
папке, где `дубли` является отдельным словом (`дубли`, `восп дубли`, `учителя дубли`, `дубли 3`
и т. п.). TARGET — только файл непосредственно в каталоге, у которого есть дочерняя стадия
`PP`; название самого TARGET-каталога значения не имеет. Всё внутри `PP`, включая варианты
`PP ПОВЕРНУТЬ`, является ретушью и никогда не индексируется как TARGET.

При первом открытии scanner index schema v1 мигрируется в v2 без доверия к старым ICC hashes:
строки без ICC hash получают статус `none`, а строки с hash — `unverified`. Следующий scan
повторно инспектирует только `unverified`/устаревшие строки, даже если размер и mtime файла не
изменились; после успешной проверки они получают явные `valid`/`invalid` и provenance.

## 2. Консервативный matching

```powershell
$matcherCache = Join-Path $env:CC_PRIVATE "cache\matcher"
$matcherOutput = Join-Path $env:CC_PRIVATE "matcher-manifests"

$matchJson = python -m colorcorrection.cli_match `
  --database $indexDatabase `
  --cache-dir $matcherCache `
  --output-dir $matcherOutput `
  --dataset-version dataset_v001 `
  --resume `
  --progress-every 10

$matchResult = $matchJson | ConvertFrom-Json
$matcherManifest = $matchResult.manifest_jsonl
```

Matcher сначала ограничивает кандидатов сезоном и контекстом, затем использует независимые
pHash/dHash leaders, детерминированный spread, aspect/dimension signals, SIFT/ORB,
bidirectional ratio matches, RANSAC и сравнение выровненной структуры. Имя файла даёт лишь малый
bonus и не может заменить геометрическую проверку. Shortlist остаётся ограниченным и не является
гарантией recall: manifest сохраняет полный размер доступного pool, ranks, cutoff и saturation.
Fallback-кандидат по умолчанию не может подняться выше `UNCERTAIN`; флаг
`--allow-audited-fallback-matched` допустим только после описанного ниже calibration-аудита.

Для единственного одноимённого RAW в том же контексте действует быстрый путь, но имя лишь выбирает
кандидата: результат всё равно обязан пройти полную SIFT/RANSAC-проверку, overlap не ниже 0.97,
почти единичную площадь преобразования, строгую detail-проверку и локальный mismatch gate. Копии
одного RAW предварительно схлопываются, чтобы не создавать ложного второго кандидата.

Каждый AFTER-результат сразу записывается в SQLite, поэтому совместимый незавершённый run можно
продолжить. JSONL и CSV создаются атомарно по завершении. `--limit` удобен только для smoke test;
ограниченный run не заменяет полный production matching. Консервативные thresholds лучше не
ослаблять без анализа `UNCERTAIN`, runner-up margin и geometry metrics.

Перед первым полным production run обязательны два matcher run на одной и той же
детерминированной selection из 200 AFTER. Сначала выполните default run с `--limit 200`,
`--selection-strategy stratified_round_robin_v1` и фиксированным `--selection-seed`. Затем
повторите те же 200 IDs/selection digest в отдельной dataset version с минимум четырёхкратно
увеличенными `--max-candidates` и `--max-fallback-candidates`, а для широкого audit включите
`--all-season-fallback-contexts`. Эти параметры лишь расширяют bounded search и всё равно не
доказывают recall. Production запрещён, если хотя бы один default `MATCHED` меняет top BEFORE ID
в wide run, если есть candidate errors, неизвестный runner-up margin или небезопасная homography.
Требование допуска: **100% top-ID stability** для всех default `MATCHED`; все расхождения,
fallback tops, минимальные margins/detail/coverage и сильнейшие homography дополнительно
проверяются в bounded color/edge preview выборке, а не по имени файла.

После завершения обоих run формальный fail-closed audit выполняется только по их immutable JSONL
manifest и ничего не читает/не записывает в фотоархив:

```powershell
$matcherAuditRoot = Join-Path $env:CC_PRIVATE "reports\matcher\audits"
$matcherAudit = Join-Path $matcherAuditRoot "calibration_default_vs_wide_v002.json"

python -m colorcorrection.cli_match_audit `
  --default-manifest $defaultCalibrationManifest `
  --wide-manifest $wideCalibrationManifest `
  --output $matcherAudit
if ($LASTEXITCODE -ne 0) { throw "Matcher calibration audit rejected production" }
```

Команда пересчитывает selection digest из полного ranked AFTER-ID списка, требует одинаковые
selection method/seed/limit/population/runtime, ноль candidate errors и 100% сохранение статуса и
BEFORE-ID каждого default `MATCHED`. Для всех wide `MATCHED` она fail-closed проверяет известный
runner-up margin и полноту geometry/detail evidence. Все fallback tops перечисляются отдельным
списком для bounded preview review. JSON создаётся иммутабельно: существующий `--output` никогда
не перезаписывается; при отклонении команда всё равно печатает структурированный JSON и завершает
работу с кодом 1 (невалидный/неполный manifest — код 2).

Feature cache v3 и matcher v1.5 включают канонический fingerprint версий OpenCV, NumPy, Pillow и
scikit-image. Resume с другим runtime не смешивает результаты. RANSAC seed детерминирован каждой
парой; ошибки snapshot/I/O завершают run, а recoverable candidate error запрещает `MATCHED`.
Homography проходит denominator/grid/Jacobian/convexity checks, coverage проверяется отдельно с
обеих сторон, а локальный lower-quantile tile gate удерживает соседние кадры в `UNCERTAIN`.

Строки с подтверждённой ошибкой декодирования сохраняются для аудита, но никогда не участвуют в
поиске пары: битый BEFORE исключается, битый AFTER получает детерминированный `UNMATCHED`.
Одновременно любой читаемый файл с `icc_status=unverified` блокирует весь matcher до повторной
ICC-проверки, поэтому это исключение нельзя использовать для обхода color-management контракта.

## 3. Валидация и leakage-safe dataset

Dataset можно построить из completed matcher run в SQLite или из его JSONL manifest. Ниже
используется manifest:

```powershell
$datasetRoot = Join-Path $env:CC_PRIVATE "datasets"
$datasetVersion = "dataset_v001"
$datasetWork = Join-Path $env:CC_PRIVATE "work\dataset_v001-validation"

$datasetJson = python -m colorcorrection.cli_dataset `
  --manifest $matcherManifest `
  --output-dir $datasetRoot `
  --dataset-version $datasetVersion `
  --work-dir $datasetWork `
  --archive-root $env:CC_ARCHIVE `
  --train-ratio 0.80 `
  --val-ratio 0.10 `
  --test-ratio 0.10 `
  --seed 20260822 `
  --split-version split_v002 `
  --detect-duplicate-clusters `
  --duplicate-phash-distance 0 `
  --max-direct-aspect-error 0.005 `
  --max-alignable-aspect-error 0.005 `
  --minimum-overlap 0.97 `
  --minimum-transform-plausibility 0.90 `
  --minimum-inlier-ratio 0.80 `
  --minimum-coverage 0.10 `
  --minimum-projected-area-ratio 0.97 `
  --maximum-projected-area-ratio 1.03 `
  --maximum-direct-transform-error 0.005 `
  --no-allow-crop-alignment

$datasetResult = $datasetJson | ConvertFrom-Json
$datasetManifest = $datasetResult.manifest_path
```

Первый запуск с `--work-dir` требует, чтобы этот каталог ещё не существовал. Если процесс
прервался, повторите **ту же** команду с дополнительным `--resume`. Work directory обязан быть
вне read-only archive и не может находиться внутри `--output-dir` (или содержать его). Resume
разрешён только для незавершённого журнала с точным совпадением hash/schema входного matcher
manifest, порядка и geometry каждой пары, size/mtime/SHA-256 исходных файлов, validation/split
configuration и версий Python/NumPy/Pillow. Изменение входа, stale source, лишняя/повреждённая
cache-запись или другой runtime завершают сборку fail-closed; смешивать результаты разных
запусков нельзя.

Декодирование каждой пары записывается отдельным атомарным cache record. `dataset_vNNN` не
публикуется, пока журнал не подтверждает полное ожидаемое покрытие и порядок, а принятые пары и
validation summary не пересчитаны. После same-filesystem rename готовых `manifest.jsonl` и
`summary.json` журнал получает `dataset_complete.json`; завершённый журнал повторно resume не
принимает. Все journal/cache/output writes остаются снаружи архива.

Для matcher manifest schema v3 dataset builder до фильтрации `MATCHED` сверяет единый run,
полноту selection ranks/AFTER ids и пересчитанный `selection_digest`. По умолчанию публикация
dataset из matcher run с `--limit` запрещена: нужен полный completed run. Флаг
`--allow-diagnostic-limited-selection` существует только для диагностики, помечает результат
`diagnostic_only` и такой manifest намеренно отклоняется production training. Старые manifests
без selection provenance остаются читаемыми, но получают явную метку `provenance_unknown`.

Валидация проверяет dimensions/aspect/orientation, overlap, plausibility преобразования, RANSAC
inliers, coverage и изменение площади. Для color-only production dataset используйте строгий
пример выше: crop и заметное геометрическое преобразование тогда не допускаются. Geometry metrics
обязательны.

Повторный RAW больше не удаляет весь кластер. Эквивалентные копии получают одного
детерминированного канонического победителя; разные TARGET для одного исходника целиком уходят в
карантин как противоречивая разметка. Полностью неизменённые RAW/TARGET сохраняются с отдельным
флагом `identity_color_target`, чтобы их долю можно было проверить и ограничить до обучения.

Стадия `PP` и вложенные каталоги, явно обозначающие нецветовую производную (`вырез*`, `обтрав*`, `cutout`,
`background removed`), остаются в read-only индексе для аудита, но исключаются ещё до selection
matcher и повторно отклоняются validation с причиной `non_color_edit_target`. Замена/удаление
фона, коллаж и вырезанный объект не являются эталоном цветокоррекции и не попадают в обучение.
Немаркированные PSD/PNG с не менее чем 10% полностью прозрачных исходных пикселей блокируются
тем же правилом до того, как alpha будет визуально сплющена на белый фон.

Единица split — вся группа `season / shoot / context`; optional duplicate clustering удерживает
одинаковые кадры из разных групп в одном split. Split детерминирован seed-значением. Каждая
версия `dataset_vNNN` содержит `manifest.jsonl` и `summary.json`, является immutable и не
перезаписывается. Для повторной сборки выберите следующую версию.

Перед production training/evaluation проверьте в `summary.json` значение
`production_eligible: true`. Если хотя бы один из `train`, `val` или `test` пуст, dataset всё ещё
сохраняется как диагностический, но получает `production_eligible: false` и детерминированные
причины `empty_<split>_split`; production training и comparison/evaluation отклоняют его до выбора
GPU и загрузки checkpoint. На малом количестве целых съёмок доли могут отличаться от целевых.
Исправление — добавить независимые группы, а не переносить отдельные фотографии между splits.

## 4. Анализ BEFORE -> TARGET и baselines

```powershell
$analysisOutput = Join-Path $env:CC_PRIVATE "analysis\dataset_v001"
$analysisWork = Join-Path $env:CC_PRIVATE "work\dataset_v001-analysis"

python -m colorcorrection.cli_analyze `
  --manifest $datasetManifest `
  --output-dir $analysisOutput `
  --work-dir $analysisWork `
  --archive-root $env:CC_ARCHIVE `
  --maximum-pixels-per-pair 500000 `
  --fit-baselines
```

Первый resumable-запуск указывается через `--work-dir` без `--resume`; каталог ещё не должен
существовать. После прерывания повторите точную команду с `--resume`. Журнал и сжатая атомарная
cache-запись каждой пары находятся только во внешнем work directory. Контракт фиксирует путь,
SHA-256 и schema manifest, точный порядок пар, size/mtime/SHA-256 BEFORE, TARGET и надёжной маски,
geometry/preprocessing/sampling/skin-proxy параметры, baseline CLI config и версии
Python/NumPy/OpenCV/Pillow/scikit-image. Work/output обязаны находиться вне архива и не могут
пересекаться.

JSON/CSV публикуются одним same-filesystem rename только после проверки точного покрытия и
порядка всех выбранных пар и повторной проверки полного input/runtime contract. Resume принимает
только точное совместимое **незавершённое** состояние; повреждение cache, stale source, изменение
конфигурации/runtime или лишний entry завершают анализ fail-closed. Завершённый журнал immutable и
повторно не запускается. Если baseline fitting после публикации анализа был прерван, не продолжайте
завершённый journal: удалите недописанные внешние baseline artifacts, выберите новый analysis
output/work version и повторите команду; архив при этом всегда остаётся read-only.

По умолчанию используются только `MATCHED` записи split `train`; изображения и previews не
записываются. Команда создаёт JSON/CSV анализа и четыре детерминированных baseline-модели:
Baseline A (global RGB statistics/white balance), B (ridge-регрессия ограниченных глобальных
параметров), C (pooled monotonic RGB curves) и D (фиксированный global 3D LUT). Legacy-файл
`baseline_a_global_curves.json` сохраняется как совместимый alias Baseline C. Для versioned
production dataset дополнительно создаётся `baseline_suite.json`: он связывает SHA-256 каждого
artifact A–D с dataset/split provenance и точным упорядоченным списком train pair IDs. Флаги
`--include-non-matched` и `--include-non-train` предназначены для явных диагностических
экспериментов и небезопасны для обычного fitting из-за шума и leakage; при них formal suite
намеренно не создаётся.

Для анализа изменения оттенков в skin-like областях приоритет имеет явно предоставленная
надёжная `skin_mask_path`. Если такой маски нет или она помечена ненадёжной, CPU-анализ может
построить только консервативный `skin_like_color_proxy`: Y/Cb/Cr и saturation вычисляются
исключительно по выровненному BEFORE на bounded-копии с максимальной стороной `512 px`, после
чего одна и та же пространственная маска применяется к BEFORE и TARGET. Coverage, связность,
касание границы, загрязнение border и устойчивость к более строгим внутренним thresholds должны
пройти reliability gates; иначе результат явно имеет `available: false`. Точные формулы,
thresholds, morphology и измерения gates сохраняются в JSON provenance. Это цветовой proxy, а
не детектор людей или кожи; он не определяет личность, этничность и другие demographic attributes.

## 5. Обучение цветовой модели

Базовая конфигурация находится в `configs/train_adaptive_lut.yaml`. Основные defaults:

- LUT size `17`, восемь residual basis LUT и preview encoder `256 px`;
- training crop `256 px`, lossless read-through cache с canvas до `1024 px`, общий geometry
  transform и valid-overlap mask для BEFORE/TARGET, рабочее пространство sRGB и физический
  EXIF transpose;
- batch size `16`, AMP, `80` epochs, seed `20260822`, early stopping patience `12`;
- L1/Charbonnier, SSIM, Lab, luminance, chroma, gradient и LUT regularization losses.

Для первого интерпретируемого эксперимента доступна опциональная конфигурация
`configs/train_conditional_affine12.yaml`. `ConditionalAffine12` использует тот же preview
encoder и preprocessing, но предсказывает только глобальную RGB-матрицу `3x3` и три смещения.
Все 12 отклонений ограничены, последний слой начинается с нулей, поэтому необученная модель
строго тождественна. Она не имеет пространственных параметров и не может менять геометрию.
Если `model.architecture` не указан, по-прежнему выбирается `AdaptiveLUTModel`.
Начальные bounds (`diagonal ±0.50`, `cross-channel ±0.50`, `bias ±0.25`) выбраны как guardrail:
в калибровочном анализе 342 unconstrained affine fits 95-й перцентиль максимума на пару составил
`0.484 / 0.435 / 0.142`. Это ориентир для первого эксперимента, а не доказательство качества
bounded-модели; решение принимается только по untouched held-out split.

Опциональный запуск отличается только config и отдельным cache namespace:

```powershell
python -m colorcorrection.cli_train `
  --config .\configs\train_conditional_affine12.yaml `
  --manifest $datasetManifest `
  --runs-dir $runsRoot `
  --cache-dir (Join-Path $env:CC_PRIVATE "cache\conditional-affine12-pairs") `
  --notes "conditional-affine12 first experiment"
```

Пути в YAML разрешаются относительно самого config-файла. Для реального запуска всегда
переопределяйте manifest, runs root и preprocessing cache внешними приватными путями:

```powershell
$runsRoot = Join-Path $env:CC_PRIVATE "runs"
$trainingCache = Join-Path $env:CC_PRIVATE "cache\adaptive-lut-pairs"

python -m colorcorrection.cli_train `
  --config .\configs\train_adaptive_lut.yaml `
  --manifest $datasetManifest `
  --runs-dir $runsRoot `
  --cache-dir $trainingCache `
  --notes "adaptive-lut initial run"
```

До выбора GPU и создания `run_NNNN` training проводит тот же формальный identity audit, что и
единое сравнение: обязательны immutable `summary.json`, согласованный assignment digest,
непустые `train`/`val`/`test` и отсутствие пересечений `split_group` и
`leakage_component_id` между split. Затем training читает только `MATCHED` +
`validation_valid` записи из `train` и `val`, применяет лишь одобренное выравнивание и не
использует `test`. Production-run без внешнего cache намеренно отклоняется: cache один раз
декодирует ICC/EXIF, выравнивает пару и сохраняет lossless NPZ с непрозрачным именем, чтобы не
перечитывать 20–40 Мп исходники на каждой эпохе. Каждый запуск атомарно получает новый каталог
`run_NNNN` с resolved `config.yaml`, `provenance.json`, `metrics.jsonl` и checkpoints
`checkpoints/best.pt` и `checkpoints/last.pt`. Путь `best_checkpoint` печатается в финальном JSON.

### Resume

Resume также создаёт новый immutable `run_NNNN`; старый run не перезаписывается. Укажите
`last.pt` прерванного запуска и те же manifest/model settings:

```powershell
$resumeCheckpoint = "<path-from-training-complete-last-checkpoint>"

python -m colorcorrection.cli_train `
  --config .\configs\train_adaptive_lut.yaml `
  --manifest $datasetManifest `
  --runs-dir $runsRoot `
  --cache-dir $trainingCache `
  --resume $resumeCheckpoint `
  --notes "resume after interruption"
```

Если checkpoint уже достиг числа epochs из config, увеличьте `training.epochs` в отдельной
приватной копии YAML; scheduler будет явно перепланирован на новый horizon. Manifest и его hash,
dataset/split versions, seed, preprocessing, loss, batch size, optimizer и архитектура должны
совпадать — несовместимый resume завершается до создания нового run. Вместе с `last.pt`
обязателен sibling `best.pt`: новый run сначала наследует и перепривязывает к своей provenance
реальный лучший checkpoint всей цепочки. Поэтому даже если первая продолженная эпоха хуже,
`best.pt` не заменяется; новый лучший checkpoint записывается только при строгом улучшении.

## 6. Held-out evaluation

Evaluation допускает только `val` или `test`; production-оценка должна использовать ранее не
тронутый `test` split.

```powershell
$bestCheckpoint = "<path-from-training-complete-best-checkpoint>"
$evaluationRoot = Join-Path $env:CC_PRIVATE "evaluations"

python -m colorcorrection.cli_evaluate `
  --checkpoint $bestCheckpoint `
  --manifest $datasetManifest `
  --output $evaluationRoot `
  --split test `
  --batch-size 4 `
  --workers 2 `
  --tile-size 1024 `
  --max-previews 40 `
  --top-k 10
```

Каждый запуск создаёт новый `evaluation_NNNN`. Training по-прежнему использует `256x256` crops,
но held-out evaluation никогда не выбирает один центральный crop: она проходит весь
aspect-preserving подготовленный canvas пары после того же EXIF/ICC decode, approved alignment и
resize, а метрики считает по всем пикселям полного valid mask. Baseline E один раз предсказывает
глобальное цветовое преобразование из полного conditioning preview BEFORE и применяет его к
canvas tile-by-tile.
`report.json` фиксирует этот whole-frame контракт и содержит aggregate MAE, PSNR, SSIM, отдельные
Delta E 76 и Delta E 2000, luminance MAE и Lab chroma MAE, а также best/worst pair IDs. В каталоге
находятся aspect-preserving neutral-name previews полного canvas `BEFORE | MODEL | TARGET`,
локальный `index.html` и `preview_manifest.jsonl` для расширенного dashboard. Оригинальные
filenames не используются в именах preview assets.

До выбора GPU и создания `evaluation_NNNN` production evaluation CPU-проверяет, что checkpoint
называется `best.pt`, имеет текущие schema/pipeline и непротиворечивые model/history/config
данные, был обучен без test-device injection на разрешённой RTX 3090 и с внешним preprocessing
cache. SHA-256 и путь manifest, dataset/split versions и train/val counts обязаны точно совпадать
с checkpoint provenance; произвольный preprocessing override запрещён. `last.pt`, checkpoint
другого dataset или повреждённая provenance отклоняются до CUDA и до создания output.

### Формальное единое сравнение Baselines A–E

Baseline E — только реально обученная поддерживаемая цветовая модель из `checkpoints/best.pt`.
До такого обучения метрики E не существуют и не подменяются identity/test моделью. Единый
comparison применяет A–E к одному и тому же непустому, точному упорядоченному `test`, используя
одинаковые preprocessing, approved alignment и valid mask:

```powershell
$baselineSuite = Join-Path $analysisOutput "baseline_suite.json"
$comparisonRoot = Join-Path $env:CC_PRIVATE "comparisons"
$selectionComplete = Join-Path $validationSelectionOutput "selection_complete.json"
$testLedger = Join-Path $validationSelectionOutput "test-consumption-ledger-v1"
$validationJournal = Join-Path $env:CC_PRIVATE "work\dataset_v003-production-validation"

python -m colorcorrection.cli_compare `
  --manifest $datasetManifest `
  --baseline-suite $baselineSuite `
  --checkpoint $bestCheckpoint `
  --selection-complete $selectionComplete `
  --test-consumption-ledger $testLedger `
  --validation-journal $validationJournal `
  --output $comparisonRoot `
  --archive-root $env:CC_ARCHIVE `
  --tile-size 1024 `
  --top-k 50
```

До выбора GPU и создания output проверяются immutable val-only selection seal/report и frozen
winner A–E, production eligibility, отсутствие split-group и
duplicate-component leakage, manifest/summary/split digests, ordered train/test IDs, SHA-256
suite и A–D artifacts, а также production provenance checkpoint E. Завершённый validation
journal связывает byte-SHA-256 каждого test source с ранее рассчитанным canonical pixel hash;
после создания глобального single-use ledger все текущие test source bytes проверяются до первого
decode/inference. Checkpoint от test-device, `last.pt`, checkpoint другого dataset или
не-RTX-3090 training отклоняется. На test считается только frozen val winner и unchanged-BEFORE
identity reference: никакие метрики проигравших кандидатов test не открывает. Для E одно
image-conditioned глобальное цветовое преобразование применяется и к полному metric canvas, и к
оригинальному full-resolution RAW. Production runtime выбирает только явно индексированную RTX
3090; CPU/device override через Python API не ослабляет val seal, source proof или single-use
ledger и не представлен в CLI.

Каждый успешный запуск создаёт новый immutable `comparison_NNNN/report.json` без deployment.
До первого decode фиксируются ровно 50 group-balanced test IDs. В том же единственном проходе для
них сохраняются review-only `RAW / MODEL / TARGET`: исходные oriented-sRGB RAW и TARGET остаются
в своей полной геометрии без warp/mask/crop, frozen winner применяется к полному RAW, после чего
все три панели только для проверки уменьшаются с сохранением aspect ratio до 1600 px и кодируются
metadata-free JPEG95 4:4:4. Production output модели остаётся full-resolution. Приватный opaque
mapping и hashes отделены от deployable public-capture manifest; после аварии атомарно завершённая
тройка может восстановить pair journal без повторного чтения test source. Приватный отчёт содержит
per-pair и aggregate MAE, PSNR, SSIM, Delta E 76, Delta E 2000, luma/chroma MAE, clipping rate,
best/worst IDs только для frozen winner. Тот же единственный decode-pass считает unchanged-BEFORE
identity reference, p90/p95 распределения полнокадрового mean Delta E 2000 по test-парам и
строгий win-rate winner против identity. Это не выбирает baseline по test aggregate и не требует
второго decode frozen test. Clipping rate — доля RGB-каналов внутри
valid mask, оказавшихся на границе `0` или `1` после преобразования.

Долгое whole-frame сравнение ведёт внешний соседний журнал, отделённый от immutable reports.
Его namespace — SHA-256 точного контракта dataset/checkpoint/A–D suite/preprocessing/ordered test,
tile size, seed, metric set и runtime. Каждая завершённая пара записывается атомарно вместе с
self-hash. После прерывания повтор той же команды переиспользует только полностью валидные записи
точно совместимого контракта; иной контракт получает другой namespace, а повреждённая запись
останавливает запуск. `comparison_NNNN/report.json` создаётся только после повторной проверки
contract-файла, неизменности inputs и точного полного покрытия test в manifest-порядке.

### Детерминированный error analysis и сравнение запусков

Канонический input — полный private `comparison_NNNN/report.json`: в нём есть все per-pair
метрики Baseline E и точный ordered test digest. Также для анализа одного запуска допускается
отдельный JSON/JSONL E только при явной метке model `E` и полном точном покрытии test в
manifest-порядке. Такой generic input предназначен только для анализа одного запуска; cross-run
comparator принимает лишь formal comparison contract. `preview_manifest.jsonl` из evaluation
намеренно отклоняется как bounded subset, даже если в нём есть per-pair metrics.

```powershell
$errorAnalysisRoot = Join-Path $env:CC_PRIVATE "error-analysis"
$comparisonReport = "<comparison-output-directory>\report.json"

$errorJson = python -m colorcorrection.cli_error_analysis analyze `
  --evaluation $comparisonReport `
  --manifest $datasetManifest `
  --output $errorAnalysisRoot `
  --archive-root $env:CC_ARCHIVE `
  --top-n 50

$errorResult = $errorJson | ConvertFrom-Json
```

CPU-only analyzer безопасно читает только manifest-declared BEFORE через EXIF/ICC-aware loader;
пути из evaluation не считаются доверенными. Он создаёт новый immutable
`error_analysis_NNNN/report.json` и `per_pair.csv`, не записывает изображения и не запускает
inference. Top означает наибольший Delta E 2000 (worst), bottom — наименьший (best); tie-break
детерминирован dataset ordinal.

Категории могут пересекаться. Very bright/dark, low/high contrast и `warm_wb_proxy` /
`cool_wb_proxy` основаны на сигнальных статистиках с минимальным support. White/dark/colored
background использует только border ROI; light/dark
clothing — central-lower ROI; skin presence/tone — широкий YCbCr/Lab/R:B proxy без demographic
labels; mixed lighting — пространственную дисперсию WB proxy. Это явно proxies, а не semantic
segmentation или вывод о личности. Все ROI, формулы и численные thresholds записываются в
`signal_contract` provenance.

Для сравнения двух или трёх завершённых запусков в порядке RUN1/RUN2/RUN3:

```powershell
python -m colorcorrection.cli_error_analysis compare `
  --run "<error-analysis-run-1>" `
  --run "<error-analysis-run-2>" `
  --run "<error-analysis-run-3>" `
  --output $errorAnalysisRoot `
  --archive-root $env:CC_ARCHIVE
```

Comparator пересчитывает digests и принимает только exact same ordered test pairs, manifest,
split/assignment provenance, signal thresholds/features и metric set. Результат — новый immutable
`error_comparison_NNNN/report.json` и `category_deltas.csv`; delta convention — более поздний RUN
минус более ранний RUN. Все inputs/outputs обязаны быть локальными и вне каждого archive root.

## 7. Full-resolution inference

Один файл (для `--output` требуется имя выходного файла с поддерживаемым расширением):

```powershell
$sourceImage = "<input-image>"
$outputImage = Join-Path $env:CC_PRIVATE "outputs\corrected-example.jpg"

python -m colorcorrection.cli_infer `
  --checkpoint $bestCheckpoint `
  --input $sourceImage `
  --output $outputImage `
  --archive-root $env:CC_ARCHIVE `
  --jpeg-quality 95 `
  --tile-size 1024
```

Папка с сохранением относительной структуры:

```powershell
$sourceDirectory = "<input-directory>"
$outputDirectory = Join-Path $env:CC_PRIVATE "outputs\batch-001"

python -m colorcorrection.cli_infer `
  --checkpoint $bestCheckpoint `
  --input $sourceDirectory `
  --output $outputDirectory `
  --archive-root $env:CC_ARCHIVE `
  --recursive `
  --resume `
  --jpeg-quality 95 `
  --tile-size 1024
```

Inference принимает JPEG, PNG, TIFF, BMP и WebP, применяет один предсказанный adaptive LUT
tile-by-tile к полному разрешению и проверяет, что width/height не изменились. Хотя input может
находиться внутри read-only архива, output обязан быть вне каждого archive root. Production CLI
требует хотя бы один `--archive-root`; повторите флаг для всех защищаемых архивов. Проверка
canonical path, traversal, symlink и Windows junction выполняется до CUDA inventory, загрузки
checkpoint, декодирования изображения и создания destination-каталогов. Источник и назначение не
могут совпадать. Существующие output-файлы защищены, пока явно не указан `--overwrite`; даже с ним
заменяются только destination-файлы, не оригиналы.

`--resume` разрешён только для batch directory и несовместим с `--overwrite`. Рядом с каждым
готовым output хранится атомарный `.colorcorrection.json` sidecar: в нём есть fingerprint source,
SHA-256 checkpoint и его trust-контракта, все влияющие options, а также hash, format и geometry
output плюс self-hash записи. Resume сначала проверяет все существующие пары output+sidecar и
лишь затем начинает любой pending inference. Отсутствующая половина пары, изменённые source,
checkpoint/options/output, неверная geometry или повреждённый sidecar завершают запуск; тихого
skip по одному имени файла нет. В JSON результата `reused_count` отделён от
`newly_processed_count`. Первый batch-запуск тоже пишет sidecars, поэтому его можно продолжить
после аварийного завершения.

После проверки destination и безопасного декодирования, но до выбора CUDA, production inference
CPU-проверяет тот же trust-контракт `best.pt`, что formal comparison: текущие schema/pipeline,
best-validation state, production RTX 3090 provenance, отсутствие test injection и обязательный
внешний preprocessing cache. Inference не принимает отдельный manifest, поэтому проверяет
самосогласованность сохранённых manifest hash/path и dataset/split provenance внутри checkpoint.
Ослабленный loader доступен только через явный Python-only `test_device` в изолированных тестах;
production CLI такого параметра не предоставляет.

## 8. Локальный visual QA dashboard

Matcher dashboard:

```powershell
$matcherReportRoot = Join-Path $env:CC_PRIVATE "reports\matcher"

python -m colorcorrection.cli_report `
  --manifest $matcherManifest `
  --output-root $matcherReportRoot `
  --archive-root $env:CC_ARCHIVE `
  --mode matcher `
  --edge-previews `
  --run-label "matcher dataset_v001"
```

Evaluation dashboard:

```powershell
$evaluationDirectory = "<path-from-evaluation-complete-output-directory>"
$evaluationPreviewManifest = Join-Path $evaluationDirectory "preview_manifest.jsonl"
$evaluationReportRoot = Join-Path $env:CC_PRIVATE "reports\evaluation"

python -m colorcorrection.cli_report `
  --manifest $evaluationPreviewManifest `
  --output-root $evaluationReportRoot `
  --archive-root $env:CC_ARCHIVE `
  --mode evaluation `
  --run-label "adaptive-lut held-out test" `
  --checkpoint (Split-Path -Leaf $bestCheckpoint)
```

Каждый вызов создаёт immutable `run-<timestamp>-<id>`, checksums и обновляет внешний history
index. Dashboard поддерживает filters, best/worst sorting, keyboard navigation, zoom,
fullscreen, matcher edge previews и evaluation wipe sliders `BEFORE/MODEL` и `MODEL/TARGET`.
Для ручной разметки четырьмя verdict-кнопками запускайте специализированный localhost server:

```powershell
python -m colorcorrection.cli_review `
  --report-root $evaluationReportRoot `
  --archive-root $env:CC_ARCHIVE `
  --run-id "<run-id-from-colorcorrection-report>" `
  --port 8765
```

Он слушает только `127.0.0.1`, проверяет immutable report/item IDs и сохраняет текущие verdicts
`good`, `bad`, `overexposed`, `wrong_frame` в `$evaluationReportRoot\feedback`, то есть вне
`run-*` и вне архива. JSON state записывается атомарно, а все замены остаются в hash-chained
audit journal. Для повторно сгенерированного run из того же source manifest оценки
восстанавливаются по стабильному item ID. Откройте URL, напечатанный командой.

### Граница deployment на `testercorrection.tw1.ru`

`cli_report` создаёт **приватный локальный artifact**: его metadata содержит filesystem paths и
явный `LOCAL_PRIVATE_REPORT_DO_NOT_PUBLISH`, а previews являются производными фотографий. Никогда
не загружайте private report root или отдельный `run-*` на сайт verbatim.

Для совместной ручной проверки matcher используется отдельный opt-in exporter. Он принимает
только завершённый checksum-valid private matcher dashboard, ограничивает пакет максимум 200
парами и заново кодирует только `BEFORE`/`AFTER` в metadata-free JPEG не более 960 px. Client
payload содержит только mode, opaque run/package/item IDs, review order и два neutral preview
URL; matcher status/confidence/metrics, image IDs, archive paths и provenance туда не переносятся.

```powershell
$privateMatcherRun = "<private-report-root\run-...>"
$matcherReviewRoot = Join-Path $env:CC_PRIVATE "matcher-review-packages"

python -m colorcorrection.cli_export_matcher_review build `
  --private-run $privateMatcherRun `
  --output-root $matcherReviewRoot `
  --archive-root $env:CC_ARCHIVE `
  --allow-matcher-review-export `
  --max-items 200 `
  --preview-max-edge 960 `
  --expected-host testercorrection.tw1.ru
```

Команда только строит локальный пакет и печатает `verify_command`; сети и deployment в ней нет.
Рядом с output root она также создаёт приватный каталог `.matcher-review-packages.private-mappings`
с обратным соответствием opaque item ID исходной паре. Этот mapping нужен, чтобы вернуть оценки
проверяющих в локальный dataset, и категорически не входит в публикуемый package directory.
Перед upload обязательно выполните напечатанную verify-команду. Имя каталога
`matcher-review-<32 hex>` содержит 128 случайных бит и является invitation capability: на сервере
нужно сохранить именно этот непредсказуемый каталог, не делать короткий redirect, history/root
link или directory listing, а проверяющим передавать только полный точный URL. Встроенные
`.htaccess` действуют лишь внутри package directory, запрещают listing, чтение PHP allowlist и
случайно размещённого `.review-data`. На Timeweb Nginx отдаёт static перед Apache, поэтому защита
runtime данных и privacy **не зависит от `.htaccess`**: до upload через WebConsole нужно получить
фактический `realpath(DOCUMENT_ROOT)` целевого домена, создать строго
`dirname(DOCUMENT_ROOT)/.colorcorrection-review-data` вне `public_html` и выставить mode `700`.
Storage не входит в public bundle. PHP fail-closed проверяет этот site-root boundary, прямое
расположение package под `DOCUMENT_ROOT`, отсутствие symlink и точные permissions; затем требует
same-origin+session CSRF, проверяет reviewer/item/label по allowlist и под блокировкой атомарно
хранит отдельные verdicts каждого reviewer. После one-time name prompt интерфейс оставляет только
пару, листание и четыре кнопки. Frontend transport задаётся в `config.js`: remote PHP требует
reviewer, а local Python feedback endpoint остаётся совместимым. Subdirectories содержат
`index.html`, а CSP продублирован HTML meta, поэтому отсутствие listing и базовая browser policy не
полагаются только на static response headers от Apache. Remote frontend до reviewer bootstrap
переводит `http:` на тот же URL с `https:`, ставит `Referrer-Policy: no-referrer` через HTML meta,
а PHP независимо принимает только доказанный HTTPS (`HTTPS=on/1` или Timeweb proxy
`X-HTTPS=1/on`) и выдаёт только Secure/SameSite/HttpOnly session cookie. Это дополняет, но не
заменяет обязательное включение HTTPS redirect в настройках самого домена перед приглашением
reviewer'ов.

Для подготовки отдельной ограниченной копии сначала найдите завершённый private evaluation
dashboard run (именно каталог `run-*`, а не matcher run, manifest или `evaluation_NNNN`):

```powershell
$privateEvaluationRun = "<path-from-colorcorrection-report-output-directory>"
$publishableRoot = Join-Path $env:CC_PRIVATE "publishable-evaluation"

python -m colorcorrection.cli_publish_report `
  --private-run $privateEvaluationRun `
  --output-root $publishableRoot `
  --archive-root $env:CC_ARCHIVE `
  --max-items 30 `
  --preview-max-edge 960
```

Экспортёр принимает только checksum-valid evaluation run и fail-closed отклоняет matcher,
symlinks, path traversal, внешние или ненейтральные asset URLs. Он детерминированно выбирает
репрезентативные best/middle/worst примеры, повторно декодирует и уменьшает каждую панель, затем
заново кодирует metadata-free JPEG с новым hash-именем. Public JSON строится по allowlist: в нём
нет source/path полей, имён архива и съёмок, experiment/checkpoint labels или private marker.
Перед завершением рекурсивно сканируется весь текстовый output. Каждый вызов создаёт новый
immutable `evaluation-<timestamp>-<id>` и дополняет отдельную sanitized history, не изменяя старые
runs.

Это только локальный export — команда не использует сеть, SSH и ничего не развёртывает. До любой
публикации откройте `$publishableRoot` локально, визуально подтвердите ограниченную выборку и
убедитесь, что публикация производных изображений допустима.

Для итоговой совместной ручной проверки модели используйте отдельный минимальный exporter. Его
client payload содержит только три изображения `RAW / СЫРОЙ | MODEL | TARGET`, opaque IDs и порядок;
в интерфейсе остаются имя проверяющего, назад/дальше, счётчик и четыре verdict-кнопки. Метрики,
пути, статусы, confidence, фильтры и боковая лента кадров в пакет не попадают:

```powershell
$evaluationReviewRoot = Join-Path $env:CC_PRIVATE "evaluation-review-packages"
$formalReviewPublicManifest = "<review_public_manifest_path from comparison result>"

python -m colorcorrection.cli_export_evaluation_review build `
  --formal-capture-manifest $formalReviewPublicManifest `
  --output-root $evaluationReviewRoot `
  --archive-root $env:CC_ARCHIVE `
  --allow-evaluation-review-export `
  --expected-host testercorrection.tw1.ru
```

Команда локальна и не загружает пакет. Перед deployment обязательно выполните напечатанную
`verify_command`. Каталог `evaluation-review-<32 hex>` является отдельной 128-bit invitation
capability и использует тот же внешний server-side storage boundary, HTTPS/host/session/CSRF и
per-reviewer verdict contract, что matcher review, но отдельные package ID и cookie session.
Formal-capture режим повторно не выбирает и не кодирует кадры: он проверяет exact schema, hashes,
размеры, metadata и копирует JPEG-байты без изменений, сохраняя opaque run/item IDs и порядок.
Соседний приватный binding однозначно связывает новый package ID с formal capture для импорта
verdicts. Legacy `--private-run` режим остаётся доступен отдельно и сохраняет прежний предел 960 px.

`--private-run`, `--output-root` и все `--archive-root` обязаны находиться на локальной файловой
системе. Exporter до любого filesystem I/O отклоняет UNC/device/URI locations, а на Windows — и
буквы дисков с типом `DRIVE_REMOTE`; сетевой share нельзя использовать как неявный deployment.
Параллельные запуски защищены соседним fail-closed файлом `.<output-root-name>.publish.lock`.
Если процесс был аварийно завершён и lock остался, сначала убедитесь, что другого exporter-процесса
нет, проверьте public root на отсутствие `.building-*`/незарегистрированного `evaluation-*` и только
после этого вручную удалите stale lock. `checksums.sha256` обнаруживает порчу, но не является
криптографической подписью против локального пользователя с правом перезаписи всего run.

Перед первой серверной записью необходимо определить фактический document root именно домена
`testercorrection.tw1.ru`; путь нельзя угадывать. Любая будущая выкладка должна быть ограничена
только этим подтверждённым document root. Запрещено изменять другие сайты, домены, каталоги,
конфигурации, SSL, базы, `.htaccess` или иные ресурсы Timeweb-аккаунта. Credentials и server paths
не хранятся в Git.

## Color management и metadata

- `ImageOps.exif_transpose` физически переводит вход в display orientation до анализа и модели.
- При корректном embedded ICC pixels преобразуются в 8-bit sRGB через Pillow ImageCms. Embedded
  profile никогда не игнорируется: ошибка parse/transform получает статус `invalid`, сохраняется
  с hash и диагностикой, а matcher, dataset, training и inference fail-closed отклоняют файл.
- Текущий color-correct pipeline поддерживает только глубину до 8 bit на компонент. Scanner
  продолжает инвентаризацию 16/32-bit файлов и сохраняет их исходную глубину, но не строит для них
  lossy perceptual hashes; matcher/dataset/training/inference считают такую запись unsupported.
- Scanner сохраняет только ограниченную EXIF-сводку; GPS и MakerNote не копируются.
- PSD включён для flattened composite, который способен прочитать Pillow. Слои не
  интерпретируются; недекодируемый PSD остаётся ошибкой индекса, а не тихо пропускается.
- Inference записывает sRGB ICC, физически нормализует orientation до `1` и переносит только
  безопасный EXIF allowlist. GPS, MakerNote, thumbnails и бинарные vendor payloads не переносятся.
- Запись inference выполняется через временный файл и атомарную замену destination.

## Артефакты и воспроизводимость

| Этап | Приватный результат |
| --- | --- |
| scan | SQLite index, scan runs и decode errors |
| match | CV feature cache, SQLite rows, versioned JSONL/CSV manifests |
| dataset | immutable `dataset_vNNN/manifest.jsonl` и `summary.json` |
| analyze | analysis JSON/CSV, четыре baseline JSON (A–D) и formal suite manifest |
| train | immutable `run_NNNN`, provenance, metrics, `best.pt`, `last.pt` |
| evaluate | immutable `evaluation_NNNN`, metrics и bounded previews |
| compare | immutable private `comparison_NNNN/report.json` с единым held-out A–E |
| error analysis | immutable private JSON/CSV с top/bottom, proxy-категориями и RUN1/2/3 deltas |
| report | immutable static report runs и history index |
| infer | отдельные исправленные изображения |

Dataset manifest содержит schema/version/seed/group assignment digest. Baseline suite содержит
ordered train IDs и hashes A–D. Training provenance содержит hash manifest, split versions,
preprocessing, config и device inventory. Старые dataset, training, evaluation, comparison и
report runs не перезаписываются; новый эксперимент получает новый ID.

## Тесты и безопасность публичного репозитория

```powershell
python -m pytest
python -m ruff check .
python -m ruff format --check .
python scripts/check_public_repo.py
```

Установка Git hooks:

```powershell
pre-commit install --hook-type pre-commit --hook-type pre-push
pre-commit run --all-files
```

Guard проверяет staged/tracked files и блокирует реальные фотографии, веса, SQLite и другие
приватные binary artifacts, крупные файлы, machine-specific absolute paths, ключи и token-like
секреты. Исключение возможно только для маленьких проверенных synthetic fixtures в
`tests/fixtures/synthetic`; они должны быть без EXIF и не могут подменять реальные данные.
Pre-push режим читает Git blobs каждого изменённого пути во всех отправляемых commits, поэтому
секрет или фотография из промежуточного commit блокируются, даже если текущий working tree уже
очищен. Для initial push консервативно проверяется вся достижимая история `HEAD`.

Перед ручным `git add` нового файла его можно проверить отдельно:

```powershell
python scripts/check_public_repo.py README.md
```

Не полагайтесь только на `.gitignore`: guard и просмотр `git status` обязательны перед commit и
push. В публичный Git входят код, configs без локальных значений, документация, dashboard assets
без previews и synthetic tests — не архив, не outputs и не веса.

## Встраивание в будущую MagicBox

ColorCorrection должен остаться локальным модулем общего последовательного pipeline, а не REST
API, HTTP service, microservice или постоянно работающим backend. Текущая программная граница уже
отделена от CLI и GUI:

```python
from colorcorrection.inference import ColorCorrection

rtx_3090_cuda_index = int("<cuda-index-of-rtx-3090>")

corrector = ColorCorrection(
    checkpoint_path="<local-checkpoint>",
    requested_cuda_index=rtx_3090_cuda_index,
    archive_roots=["<read-only-archive-root>"],
)

one_result = corrector.process(
    input_path="<previous-stage-output>",
    output_path="<next-stage-input>",
)

batch_results = corrector.process_batch(
    inputs="<previous-stage-directory>",
    output_directory="<next-stage-directory>",
    recursive=True,
    resume=True,
)
```

`process` возвращает `ProcessedImage`, а `process_batch` — tuple таких результатов. Веса остаются
локальными и передаются модулю как путь к checkpoint. Будущие MagicBox и standalone desktop
должны вызывать тот же core inference pipeline; бизнес-логика не должна переезжать в GUI или на
сайт. Конкретная структура каталогов MagicBox пока не фиксируется и полный GUI/installer в этот
проект не входят.

## Troubleshooting

**`CUDA is unavailable` или `RTX 3090 was not found`.** Проверьте NVIDIA driver, CUDA-enabled
PyTorch, `torch.cuda.is_available()` и device inventory. CPU fallback намеренно отсутствует.

**Выбран другой GPU или найдено несколько RTX 3090.** Передайте корректный `--cuda-index` либо
задайте `COLORCORRECTION_CUDA_INDEX`. Имя устройства будет проверено независимо от индекса.

**Training сообщает, что split пуст.** Проверьте `summary.json`: для production dataset нужны
approved-пары во всех трёх splits (`train`, `val`, `test`). Не исправляйте это переносом отдельных
кадров между split-группами.

**Dataset/report output rejected as inside archive.** Измените `$env:CC_PRIVATE`; защита
намеренно запрещает создавать артефакты под read-only archive root.

**Файл не декодируется.** Посмотрите scanner error rows и формат. PSD требует читаемый flattened
composite; некоторые RAW/HEIF-контейнеры требуют дополнительных Pillow codecs. Не включайте
глобальное чтение truncated images ради увеличения recall.

**Matching слишком медленный.** Повторный совместимый run использует feature cache и
per-AFTER resume. Для диагностики допустим `--limit`, но итоговый dataset должен строиться из
полного completed run.

**Report не открывает данные через `file://`.** Запустите локальный `colorcorrection.cli_review`
из раздела visual QA и откройте напечатанный localhost URL.

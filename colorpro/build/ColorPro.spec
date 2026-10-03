# Explicit staged product only. Never glob the research workspace or datasets.
import hashlib
import json
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

stage = Path(os.environ['COLORPRO_STAGE']).resolve()
payload = stage / 'payload'
legacy = json.loads((payload / 'manifest.json').read_text('utf8'))['platform'] == 'win7'
data = [(str(payload), 'payload'), (str(stage / 'third-party-licenses'), 'third-party-licenses')]
data.append((str(stage / 'colorpro/assets'), 'colorpro/assets'))
for name in ['README-SETUP.txt', 'README-WIN7.txt', 'THIRD_PARTY_NOTICES.txt']:
    data.append((str(stage / name), '.'))
for name in ['torch', 'numpy', 'Pillow', 'opencv-python-headless',
             'PySide2' if legacy else 'PySide6-Essentials', 'shiboken2' if legacy else 'shiboken6']:
    data += copy_metadata(name)
data += collect_data_files('torch', includes=['lib/*.dll'])
a = Analysis([str(stage / 'colorpro/launcher.py')], pathex=[str(stage), str(payload / 'python')],
    binaries=[], datas=data,
    hiddenimports=['PIL.JpegImagePlugin','PIL.MpoImagePlugin','PIL.PngImagePlugin','PIL.TiffImagePlugin',
                   'PIL.WebPImagePlugin','PIL.BmpImagePlugin'] + (['importlib_resources'] if legacy else []),
    hookspath=[], runtime_hooks=[],
    excludes=['IPython','notebook','pytest','tkinter', 'PyQt5','PyQt6',
              'PySide6' if legacy else 'PySide2','tensorflow','jax','jaxlib','scipy','pandas',
              'tensorboard','torchvision','torchaudio','triton','onnxruntime','onnx','transformers',
              'matplotlib','cv2.gapi'], noarchive=False)
# Load the sealed source files from payload/python (including importlib resources),
# not a second bytecode copy with a different __file__ location inside the PYZ.
a.pure = [entry for entry in a.pure if entry[0] != 'colorcorrection'
          and not entry[0].startswith('colorcorrection.')]
if legacy:
    crt = Path(os.environ['COLORPRO_LEGACY_CRT'])
    pins = json.loads(Path(os.environ['COLORPRO_LEGACY_CRT_PINS']).read_text('utf8'))['files']
    native = {p.name.lower(): p for p in crt.glob('*.dll')}
    assert set(native) == set(pins)
    for name, path in native.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == pins[name], name
    replacement = []
    for destination, source, kind in a.binaries:
        name = Path(destination).name.lower()
        if name in native:
            replacement.append((destination, str(native[name]), kind))
        elif not name.startswith('api-ms-win-') and name != 'ucrtbase.dll':
            replacement.append((destination, source, kind))
    a.binaries = replacement + [(p.name,str(p),'BINARY') for p in native.values()]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='ColorPro', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, icon=str(stage / 'colorpro.ico'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ColorPro')

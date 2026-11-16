"""Use TensorFlow's public compatibility API in the tf-slim 1.1 image decoder."""

import importlib.util
from pathlib import Path

OLD_IMPORT = 'from tensorflow.python.ops import control_flow_ops'
NEW_IMPORT = 'from tensorflow.compat import v1 as control_flow_ops'


def patch_decoder(path=None):
    if path is None:
        spec = importlib.util.find_spec('tf_slim')
        if spec is None or spec.origin is None:
            raise ValueError('tf-slim belum terpasang pada environment Python ini.')
        path = Path(spec.origin).parent / 'data/tfexample_decoder.py'
    path = Path(path)
    source = path.read_text(encoding='utf-8')
    if NEW_IMPORT in source:
        return False
    if OLD_IMPORT not in source:
        if 'control_flow_ops.case(' in source or 'control_flow_ops.cond(' in source:
            raise ValueError(f'Bentuk decoder tidak dikenali; file tidak diubah: {path}')
        return False
    if source.count(OLD_IMPORT) != 1:
        raise ValueError(f'Import decoder tidak sesuai; file tidak diubah: {path}')
    path.write_text(source.replace(OLD_IMPORT, NEW_IMPORT), encoding='utf-8')
    return True


def check_decoder():
    import tensorflow as tf
    from tf_slim.data import tfexample_decoder

    handler = tfexample_decoder.Image(channels=3)
    image = tf.zeros([4, 6, 3], dtype=tf.uint8)

    @tf.function
    def decode(encoded, image_format):
        return handler.tensors_to_item({'image/encoded': encoded, 'image/format': image_format})

    for image_format, encoded in ((b'jpeg', tf.io.encode_jpeg(image)), (b'png', tf.io.encode_png(image))):
        result = decode(encoded, tf.constant(image_format)).numpy()
        if result.shape != (4, 6, 3):
            raise ValueError(f'Hasil decoder tidak sesuai: {result.shape}')
    print('Decoder JPEG/PNG tf-slim berhasil diuji di dalam tf.function.', flush=True)


def fix_decoder():
    changed = patch_decoder()
    print('Kompatibilitas tf-slim diperbarui.' if changed else 'Kompatibilitas tf-slim sudah sesuai.', flush=True)
    check_decoder()

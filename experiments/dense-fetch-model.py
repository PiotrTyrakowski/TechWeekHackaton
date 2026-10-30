"""Fetch the two pinned, public model assets; no credentials or inference APIs."""
import hashlib
from pathlib import Path
from urllib.request import urlopen

REVISION = '751bff37182d3f1213fa05d7196b954e230abad9'
DESTINATION = Path(__file__).parent / 'dense-model'
DESTINATION.mkdir(parents=True, exist_ok=True)
for filename in ('onnx/model_quantized.onnx', 'tokenizer.json'):
    target = DESTINATION / Path(filename).name
    if not target.exists():
        url = f'https://huggingface.co/Xenova/all-MiniLM-L6-v2/resolve/{REVISION}/{filename}'
        with urlopen(url) as response, target.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
    print(target, hashlib.sha256(target.read_bytes()).hexdigest())

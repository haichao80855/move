"""One isolated MLX process per job. Results are JSON, logs stay on stderr."""

import argparse
import contextlib
import json
import platform
import sys
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("audio")
parser.add_argument("output")
parser.add_argument("--engine", choices=["parakeet", "whisper"], default="parakeet")
args = parser.parse_args()
if platform.system() != "Darwin" or platform.machine() != "arm64":
    raise SystemExit("MLX requires an Apple Silicon Mac")

with contextlib.redirect_stdout(sys.stderr):
    if args.engine == "parakeet":
        from parakeet_mlx import DecodingConfig, SentenceConfig, from_pretrained

        model = from_pretrained("mlx-community/parakeet-tdt-0.6b-v3")
        result = model.transcribe(
            args.audio,
            chunk_duration=120,
            overlap_duration=15,
            decoding_config=DecodingConfig(sentence=SentenceConfig(max_duration=20, max_words=35)),
        )
        cues = [
            {
                "start": s.start,
                "end": s.end,
                "original": s.text,
                "words": [{"start": t.start, "end": t.end, "text": t.text} for t in s.tokens],
            }
            for s in result.sentences
        ]
    else:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            args.audio,
            path_or_hf_repo="mlx-community/whisper-large-v3-mlx",
            word_timestamps=True,
            language="en",
        )
        cues = [
            {
                "start": s["start"],
                "end": s["end"],
                "original": s["text"].strip(),
                "words": s.get("words", []),
            }
            for s in result["segments"]
        ]
Path(args.output).write_text(json.dumps(cues, ensure_ascii=False), encoding="utf-8")

"""Run once per batch in the isolated Apple Silicon MLX environment."""

import json
import sys
import wave
from pathlib import Path


def write_json(path: Path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def main():
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model

    mode, manifest = sys.argv[1:]
    values = json.loads(Path(manifest).read_text())
    folder = Path(values["model_dir"])

    def progress(value, message):
        write_json(Path(values["progress_file"]), {"progress": value, "message": message})

    if mode == "prepare":
        from huggingface_hub import HfApi, snapshot_download

        progress(0.1, "下载 Qwen3-TTS 0.6B Base 模型及语音编码器；首次下载可能需要数分钟")
        revision = HfApi().model_info(values["model"]).sha
        snapshot_download(values["model"], revision=revision, local_dir=folder)
        progress(0.8, "验证本机模型及参考音频编码器可加载")
    else:
        revision = json.loads((folder / "ready.json").read_text())["revision"]
        progress(0.1, "加载本机 Qwen3-TTS 模型")
    model = load_model(str(folder))
    if model.speech_tokenizer is None or not model.speech_tokenizer.has_encoder:
        raise RuntimeError("Base 模型的参考音频编码器未正确加载，请重新准备模型")
    if mode == "prepare":
        write_json(
            folder / "ready.json",
            {"model": values["model"], "revision": revision, "worker": values["worker"]},
        )
        progress(1, "模型已准备")
        return

    items = values["items"]
    for index, item in enumerate(items):
        progress(index / len(items), f"本地配音 {index + 1} / {len(items)}")
        chunks = []
        sample_rate = model.sample_rate
        for result in model.generate(
            text=item["text"],
            ref_audio=values["reference_audio"],
            ref_text=values["reference_text"],
            lang_code="chinese",
            temperature=0.9,
            max_tokens=2048,
            verbose=False,
        ):
            if result.token_count >= 2048:
                raise RuntimeError("配音文字过长，生成达到上限；请拆分字幕后重新生成")
            sample_rate = result.sample_rate
            audio = np.asarray(result.audio, dtype=np.float32).reshape(-1)
            if len(audio):
                chunks.append(audio)
        if not chunks:
            raise RuntimeError("模型未返回语音")
        audio = np.concatenate(chunks)
        if not np.isfinite(audio).all() or not np.any(audio):
            raise RuntimeError("模型返回的语音无效")
        pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
        output = Path(item["path"])
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".tmp.wav")
        with wave.open(str(temporary), "wb") as target:
            target.setnchannels(1)
            target.setsampwidth(2)
            target.setframerate(sample_rate)
            target.writeframes(pcm.tobytes())
        temporary.replace(output)
        del audio, pcm, chunks
        mx.clear_cache()
    progress(1, "本地配音生成完成")


if __name__ == "__main__":
    main()

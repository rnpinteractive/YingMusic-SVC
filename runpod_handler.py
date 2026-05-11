"""
RunPod Serverless handler — YingMusic-SVC test endpoint.

ISOLATED from main STUDIO-MV endpoint. Does NOT touch RVC pipeline.

Input:
    job_id: str (R2 prefix)
    target_url: str (source vocal/song — what gets converted)
    prompt_url: str (target timbre reference — your recorded voice clip ~30s)
    diffusion_steps: int (default 100, lower=faster but worse)
    fp16: bool (default true)
    accompany_url: str optional (instrumental, mixed back after conversion)

Output:
    {
      "status": "completed" | "failed",
      "urls": {"converted": "https://..."},
      "elapsed_s": float,
      "error": str (if failed)
    }
"""
import os
import sys
import time
import traceback
import subprocess
import shutil
import runpod

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/YingMusic-SVC")
os.chdir("/app/YingMusic-SVC")

from r2_storage import download, upload  # noqa: E402

_BUILD_TAG = "ysvc-v1"


def _run_inference(
    target_path: str,
    prompt_path: str,
    output_dir: str,
    exp_name: str,
    diffusion_steps: int = 100,
    fp16: bool = True,
    accompany_path: str | None = None,
) -> str:
    """Calls my_inference.py CLI and returns path to output audio."""
    os.makedirs(output_dir, exist_ok=True)
    # Default checkpoint + config from HF
    ckpt_path = "/app/checkpoints/hf_cache/models--GiantAILab--YingMusic-SVC/snapshots"
    # Resolve actual snapshot dir (HF caches by hash)
    import glob
    snap_dirs = glob.glob(f"{ckpt_path}/*")
    if not snap_dirs:
        # Fallback: try downloading at runtime
        from huggingface_hub import snapshot_download
        snapshot_download(
            "GiantAILab/YingMusic-SVC",
            cache_dir="/app/checkpoints/hf_cache",
            allow_patterns=["*.pt", "*.ckpt", "*.yml", "*.yaml", "*.json"],
        )
        snap_dirs = glob.glob(f"{ckpt_path}/*")
    if not snap_dirs:
        raise RuntimeError("YingMusic-SVC checkpoint not found")

    ckpt_dir = snap_dirs[0]
    ckpt_file = os.path.join(ckpt_dir, "YingMusic-SVC-full.pt")
    config_file = "./configs/YingMusic-SVC.yml"

    cmd = [
        "python", "my_inference.py",
        "--source", target_path,
        "--target", prompt_path,
        "--diffusion-steps", str(diffusion_steps),
        "--checkpoint", ckpt_file,
        "--expname", exp_name,
        "--cuda", "0",
        "--fp16", "True" if fp16 else "False",
        "--config", config_file,
    ]
    if accompany_path:
        cmd.extend(["--accompany", accompany_path])

    print(f"[Handler] Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError(f"YingMusic-SVC inference failed:\nSTDOUT: {result.stdout[-2000:]}\nSTDERR: {result.stderr[-2000:]}")

    # Find output file (YingMusic writes to a results/ folder based on expname)
    candidates = []
    for root, _, files in os.walk("./results"):
        for f in files:
            if f.endswith((".wav", ".mp3", ".flac")):
                fp = os.path.join(root, f)
                candidates.append((os.path.getmtime(fp), fp))
    if not candidates:
        # Try other common output paths
        for root, _, files in os.walk("./output"):
            for f in files:
                if f.endswith((".wav", ".mp3", ".flac")):
                    fp = os.path.join(root, f)
                    candidates.append((os.path.getmtime(fp), fp))

    if not candidates:
        raise RuntimeError(f"No output audio produced. Stdout: {result.stdout[-500:]}")

    # Pick most recently modified file
    candidates.sort(reverse=True)
    return candidates[0][1]


def handler(job):
    t0 = time.time()
    job_input = job["input"]
    job_id = job_input["job_id"]
    target_url = job_input["target_url"]
    prompt_url = job_input["prompt_url"]
    accompany_url = job_input.get("accompany_url")
    diffusion_steps = int(job_input.get("diffusion_steps", 100))
    fp16 = bool(job_input.get("fp16", True))

    workdir = f"/tmp/{job_id}"
    os.makedirs(workdir, exist_ok=True)

    target_path = f"{workdir}/target.wav"
    prompt_path = f"{workdir}/prompt.wav"
    accompany_path = None

    try:
        runpod.serverless.progress_update(job, {"percent": 5, "message": "Baixando áudios..."})
        download(target_url, target_path)
        download(prompt_url, prompt_path)
        if accompany_url:
            accompany_path = f"{workdir}/accompany.wav"
            download(accompany_url, accompany_path)

        runpod.serverless.progress_update(job, {"percent": 20, "message": "Convertendo voz (YingMusic-SVC)..."})
        output_audio = _run_inference(
            target_path=target_path,
            prompt_path=prompt_path,
            output_dir=workdir,
            exp_name=job_id,
            diffusion_steps=diffusion_steps,
            fp16=fp16,
            accompany_path=accompany_path,
        )

        runpod.serverless.progress_update(job, {"percent": 90, "message": "Enviando resultado..."})

        # Convert to MP3 320k for storage (smaller, universal)
        mp3_path = f"{workdir}/converted.mp3"
        subprocess.run(
            ["ffmpeg", "-y", "-i", output_audio, "-b:a", "320k", "-codec:a", "libmp3lame", mp3_path],
            check=True, capture_output=True,
        )

        # Also keep lossless original (WAV or FLAC depending on YingMusic output)
        ext = os.path.splitext(output_audio)[1]
        lossless_key = f"outputs/{job_id}/converted{ext}"
        lossless_url = upload(output_audio, lossless_key, "audio/wav")
        mp3_url = upload(mp3_path, f"outputs/{job_id}/converted.mp3", "audio/mpeg")

        elapsed = time.time() - t0
        print(f"[Handler] Done in {elapsed:.1f}s — {mp3_url}")
        return {
            "status": "completed",
            "urls": {
                "converted": mp3_url,
                "converted_lossless": lossless_url,
            },
            "elapsed_s": round(elapsed, 1),
            "_build": _BUILD_TAG,
        }

    except Exception as e:
        traceback.print_exc()
        return {
            "status": "failed",
            "error": str(e),
            "error_traceback": traceback.format_exc()[-2000:],
            "_build": _BUILD_TAG,
        }
    finally:
        # Cleanup workdir (not output files which already went to R2)
        try:
            shutil.rmtree(workdir, ignore_errors=True)
        except Exception:
            pass


def _type_handler(job):
    """Dispatch based on input.type (parity with main endpoint)."""
    job_type = job["input"].get("type", "svc2")
    if job_type == "version":
        return {"build": _BUILD_TAG, "service": "yingmusic-svc", "status": "ok"}
    return handler(job)


runpod.serverless.start({"handler": _type_handler})

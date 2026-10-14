"""Standalone JSONL worker; load real Qwen once, one seeded generation per line."""
from __future__ import annotations
import argparse
import contextlib
import json
import signal
import sys

interrupted = False


def interrupt(signum, frame):
    global interrupted
    interrupted = True


def emit(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main():
    global interrupted
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(args.config)
    signal.signal(signal.SIGUSR1, interrupt)
    try:
        # Import only inside the worker: scheduler/tests need no torch dependency.
        with contextlib.redirect_stdout(sys.stderr):
            import torch
            import transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
            torch.set_num_threads(config["threads"])
            tokenizer = AutoTokenizer.from_pretrained(
                config["model"], revision=config["revision"],
                local_files_only=config["local_files_only"])
            model = AutoModelForCausalLM.from_pretrained(
                config["model"], revision=config["revision"], torch_dtype=torch.float32,
                local_files_only=config["local_files_only"]).to(config["device"]).eval()
        class CancelGeneration(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                return interrupted
        emit({"ready": True, "metadata": {"torch_version": torch.__version__,
                                           "transformers_version": transformers.__version__}})
    except Exception as exc:
        emit({"ready": False, "error": type(exc).__name__,
              "hint": "Install .[local] and make the pinned HF snapshot available"})
        return
    for line in sys.stdin:
        interrupted = False
        try:
            payload = json.loads(line)
            torch.manual_seed(int(payload.get("seed", 0)) % (2 ** 63))
            messages = [
                {"role": "system", "content": "You fix Python code. Follow the supplied instruction and return only one valid JSON object."},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
            text = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
            inputs = tokenizer(text, return_tensors="pt").to(config["device"])
            options = dict(max_new_tokens=config["max_new_tokens"],
                           do_sample=config["temperature"] > 0,
                           pad_token_id=tokenizer.eos_token_id,
                           stopping_criteria=StoppingCriteriaList([CancelGeneration()]))
            if options["do_sample"]:
                options.update(temperature=config["temperature"], top_p=config["top_p"])
            with torch.inference_mode():
                output = model.generate(**inputs, **options)
            generated = output[0, inputs["input_ids"].shape[1]:]
            emit({"text": tokenizer.decode(generated, skip_special_tokens=True),
                  "cancelled": interrupted, "generated_tokens": len(generated)})
        except Exception as exc:
            emit({"error": type(exc).__name__})


if __name__ == "__main__":
    main()

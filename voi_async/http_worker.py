"""Stdlib OpenAI-compatible chat-completions bridge, run as a child process.

Invoke with python -I and this absolute path; no package install is needed.
Credentials stay in an environment variable, never in model payloads/logs.
Killing this HTTP client cannot guarantee cancellation at a remote provider.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="API prefix, e.g. http://localhost:8000/v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--key-env", default="OPENAI_API_KEY")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=2048)
    parser.add_argument("--json-mode", action="store_true")
    args = parser.parse_args()
    payload = json.load(sys.stdin)
    body = dict(model=args.model, temperature=args.temperature,
                max_tokens=args.max_tokens, seed=payload.get("seed", 0) % (2 ** 31),
                messages=[
                    {"role": "system", "content": "Follow the supplied instruction. Return only one valid JSON object."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}])
    if args.json_mode:
        body["response_format"] = {"type": "json_object"}
    headers = {"Content-Type": "application/json"}
    key = os.environ.get(args.key_env)
    if key:
        headers["Authorization"] = "Bearer " + key
    request = urllib.request.Request(
        args.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            answer = json.load(response)
        content = answer["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("non-text model answer")
        sys.stdout.write(content)
    except urllib.error.HTTPError as exc:
        # Do not dump provider error bodies or request credentials.
        sys.stderr.write(f"chat-completions HTTP status {exc.code}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

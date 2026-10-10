"""Chat client for NVIDIA NIM (OpenAI-compatible API). Stdlib only; secrets stay local.

Default model: openai/gpt-oss-20b, an open-weight model hosted by NVIDIA (21B total parameters, mixture-of-experts with
3.6B active per token). It uses NVIDIA_API_KEY and NVIDIA's endpoint, never the OpenAI API. It was the smallest
model that completed the whole agent workflow on our account (docs/team/MODEL_CHECK_FINDINGS.md).
Other models: NIM_MODEL. Extra request fields a model needs: NIM_EXTRA_BODY (JSON), e.g. for Nemotron
  NIM_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b NIM_EXTRA_BODY='{"chat_template_kwargs": {"enable_thinking": false}}'
Key: NVIDIA_API_KEY (environment or .env). Check the key with one tiny call:  python3 -m chaosmind.agents.llm --ping

The client doesn't trust the model's formatting: it folds the system prompt into the user turn (works on every chat
template), doesn't depend on a JSON mode, extracts the JSON object from the reply, and retries once if it's invalid.
Reasoning models spend output tokens on thinking first, so max_tokens is generous. Everything the model says is
still validated by code downstream.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
from pathlib import Path
import random
import re
import sys
import time
import urllib.error
import urllib.request


def setting(name, default=None):
    """Read environment first, then the project .env without executing it."""
    if os.environ.get(name):
        return os.environ[name]
    env = Path(__file__).resolve().parents[2] / '.env'
    for line in env.read_text().splitlines() if env.exists() else []:
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        key, separator, value = line.partition('=')
        if separator and key.strip() == name:
            value = value.strip().strip("\"'")
            if value:
                return value
    return default


LABEL = 'NVIDIA NIM'
API = setting('NIM_BASE_URL', 'https://integrate.api.nvidia.com/v1').rstrip('/') + '/chat/completions'
MODEL = setting('NIM_MODEL', 'openai/gpt-oss-20b')
MODELS = {'large': MODEL, 'small': MODEL}  # call sites ask for 'large'/'small'; one model serves both
MAX_TOKENS = int(setting('NIM_MAX_TOKENS', '8192'))  # reasoning tokens count against this
EXTRA_BODY = json.loads(setting('NIM_EXTRA_BODY', '{}'))


def api_key():
    key = setting('NVIDIA_API_KEY')
    if not key:
        raise RuntimeError('Set NVIDIA_API_KEY (environment or .env)')
    return key


def extract_json(text):
    """The JSON object inside a reply that may carry ```json fences or a sentence around it."""
    if not isinstance(text, str):
        return None
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip(), flags=re.I)
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        reply = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return reply if isinstance(reply, dict) else None


def _post(messages):
    body = json.dumps({'model': MODEL, 'messages': messages, 'temperature': 0.2, 'top_p': 0.9,
                       'max_tokens': MAX_TOKENS, 'stream': False, **EXTRA_BODY}).encode()
    request = urllib.request.Request(API, body, {'Content-Type': 'application/json', 'Accept': 'application/json',
                                                 'Authorization': f'Bearer {api_key()}'})
    for retry in range(5):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                choice = json.load(response)['choices'][0]
            if choice.get('finish_reason') == 'length' and not choice['message'].get('content'):
                print(f'{LABEL}: output limit reached while reasoning; raise NIM_MAX_TOKENS.', file=sys.stderr)
            return choice['message'].get('content') or ''  # reasoning models can return content None
        except urllib.error.HTTPError as error:
            code, retry_after = error.code, error.headers.get('Retry-After') if error.headers else None
            message = error.read().decode(errors='replace')[:300]
            error.close()
            if code not in (429, 500, 502, 503, 504) or retry == 4:
                raise RuntimeError(f'{LABEL} API {code}: {message}') from None
            delay = min(60, 15 * 2 ** retry) + random.uniform(0, 1)
            if retry_after:
                try:
                    requested = float(retry_after)
                except ValueError:
                    try:
                        requested = (parsedate_to_datetime(retry_after) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        requested = 0
                if requested > 300:
                    raise RuntimeError(f'{LABEL} API {code}: Retry-After exceeds 5 minutes; retry later.') from None
                delay = max(delay, requested)
            print(f'{LABEL} API {code}; retry {retry + 1}/4 in {delay:.0f}s.', file=sys.stderr, flush=True)
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError) as error:  # network blip or slow reply: retry, don't kill the run
            if retry == 4:
                raise RuntimeError(f'{LABEL} unreachable: {error}') from None
            print(f'{LABEL} {error}; retry {retry + 1}/4 in 15s.', file=sys.stderr, flush=True)
            time.sleep(15)


def ask(system, user, model='large'):
    """Return the model's reply as a JSON object (dict). One retry with a correction if it isn't valid JSON."""
    data = user if isinstance(user, str) else json.dumps(user, indent=1)
    messages = [{'role': 'user', 'content': f'{system}\n\n### Input\n{data}\n\nReply with ONE JSON object only.'}]
    for attempt in range(2):
        content = _post(messages)
        reply = extract_json(content)
        if reply is not None:
            return reply
        messages += [{'role': 'assistant', 'content': content},
                     {'role': 'user', 'content': 'That was not a single valid JSON object. Reply with only the JSON object, no prose.'}]
    raise RuntimeError(f'{LABEL} returned invalid JSON twice')


if __name__ == '__main__':
    if '--ping' in sys.argv:
        print(f'{LABEL} · {MODEL}: ', end='', flush=True)
        print(ask('Return {"ok": true}.', 'ping'))

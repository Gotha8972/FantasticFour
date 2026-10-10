"""OpenAI or Mistral chat in JSON mode. Stdlib only; secrets stay local."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
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


PROVIDER = setting('AI_PROVIDER', 'openai').lower()
if PROVIDER not in ('openai', 'mistral'):
    raise RuntimeError('AI_PROVIDER must be openai or mistral')
LABEL = 'OpenAI' if PROVIDER == 'openai' else 'Mistral'
API = ('https://api.openai.com/v1/chat/completions' if PROVIDER == 'openai'
       else 'https://api.mistral.ai/v1/chat/completions')
MODELS = ({'large': setting('OPENAI_MODEL_LARGE', setting('OPENAI_MODEL', 'gpt-5.6-luna')),
           'small': setting('OPENAI_MODEL', 'gpt-5.6-luna')} if PROVIDER == 'openai'
          else {'large': setting('MISTRAL_LARGE', 'mistral-small-2603'),
                'small': setting('MISTRAL_SMALL', 'mistral-small-2603')})


def api_key():
    name = 'OPENAI_API_KEY' if PROVIDER == 'openai' else 'MISTRAL_API_KEY'
    key = setting(name)
    if not key:
        raise RuntimeError(f'Set {name} (environment or .env)')
    return key


def ask(system, user, model='large'):
    """Return the model's reply parsed as a JSON object. One retry on invalid JSON."""
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': user if isinstance(user, str) else json.dumps(user, indent=1)}]
    for attempt in range(2):
        payload = {'model': MODELS[model], 'messages': messages,
                   'response_format': {'type': 'json_object'}}
        if PROVIDER == 'openai':
            payload['reasoning_effort'] = setting('OPENAI_REASONING_EFFORT', 'low')
        body = json.dumps(payload).encode()
        request = urllib.request.Request(API, body, {'Content-Type': 'application/json',
                                                     'Authorization': f'Bearer {api_key()}'})
        for retry in range(5):
            try:
                with urllib.request.urlopen(request, timeout=180) as response:
                    content = json.load(response)['choices'][0]['message']['content']
                break
            except urllib.error.HTTPError as error:
                code = error.code
                retry_after = error.headers.get('Retry-After') if error.headers else None
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
                # Short sleeps keep Ctrl-C responsive even with a long Retry-After.
                deadline = time.monotonic() + delay
                while remaining := deadline - time.monotonic():
                    if remaining <= 0:
                        break
                    time.sleep(min(remaining, 15))
        try:
            reply = json.loads(content)
            if isinstance(reply, dict):
                return reply
        except (TypeError, json.JSONDecodeError):
            pass
        messages += [{'role': 'assistant', 'content': content or ''},
                     {'role': 'user', 'content': 'That was not a single valid JSON object. Reply with only the JSON object.'}]
    raise RuntimeError(f'{LABEL} returned invalid JSON twice')

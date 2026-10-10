"""Mistral chat in JSON mode. Stdlib only. Key from MISTRAL_API_KEY or .env."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

API = 'https://api.mistral.ai/v1/chat/completions'
MODELS = {'large': os.environ.get('MISTRAL_LARGE', 'mistral-small-latest'),
          'small': os.environ.get('MISTRAL_SMALL', 'mistral-small-latest')}


def api_key():
    if os.environ.get('MISTRAL_API_KEY'):
        return os.environ['MISTRAL_API_KEY']
    env = Path(__file__).resolve().parents[2] / '.env'
    for line in env.read_text().splitlines() if env.exists() else []:
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'MISTRAL_API_KEY':
            key = value.strip().strip('"\'')
            if key:
                return key
    raise RuntimeError('Set MISTRAL_API_KEY (environment or .env)')


def ask(system, user, model='large'):
    """Return the model's reply parsed as a JSON object. One retry on invalid JSON."""
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': user if isinstance(user, str) else json.dumps(user, indent=1)}]
    for attempt in range(2):
        body = json.dumps({'model': MODELS[model], 'messages': messages, 'temperature': 0.2,
                           'response_format': {'type': 'json_object'}}).encode()
        request = urllib.request.Request(API, body, {'Content-Type': 'application/json',
                                                     'Authorization': f'Bearer {api_key()}'})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content = json.load(response)['choices'][0]['message']['content']
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'Mistral API {error.code}: {error.read().decode()[:300]}') from None
        try:
            reply = json.loads(content)
            if isinstance(reply, dict):
                return reply
        except json.JSONDecodeError:
            pass
        messages += [{'role': 'assistant', 'content': content},
                     {'role': 'user', 'content': 'That was not a single valid JSON object. Reply with only the JSON object.'}]
    raise RuntimeError('Mistral returned invalid JSON twice')

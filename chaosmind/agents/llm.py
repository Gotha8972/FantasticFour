"""OpenAI chat completions in JSON mode. Stdlib only. Key from OPENAI_API_KEY or .env.

Model: OPENAI_MODEL (default gpt-5.6-luna, the model used for our recorded runs);
reasoning effort: OPENAI_REASONING_EFFORT (default low). `model='small'|'large'` is kept for call-site
compatibility; set OPENAI_MODEL_LARGE to use a different model for the reasoning-heavy agents.
"""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

API = 'https://api.openai.com/v1/chat/completions'
DEFAULT_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-5.6-luna')
MODELS = {'small': DEFAULT_MODEL, 'large': os.environ.get('OPENAI_MODEL_LARGE', DEFAULT_MODEL)}
EFFORT = os.environ.get('OPENAI_REASONING_EFFORT', 'low')


def api_key():
    if os.environ.get('OPENAI_API_KEY'):
        return os.environ['OPENAI_API_KEY']
    env = Path(__file__).resolve().parents[2] / '.env'
    for line in env.read_text().splitlines() if env.exists() else []:
        line = line.strip()
        if line.startswith('export '):
            line = line[7:].strip()
        name, separator, value = line.partition('=')
        if separator and name.strip() == 'OPENAI_API_KEY' and value.strip().strip('"\''):
            return value.strip().strip('"\'')
    raise RuntimeError('Set OPENAI_API_KEY (environment or .env)')


def ask(system, user, model='large'):
    """Return the model's reply parsed as a JSON object. One retry on invalid JSON."""
    messages = [{'role': 'system', 'content': system},
                {'role': 'user', 'content': user if isinstance(user, str) else json.dumps(user, indent=1)}]
    for attempt in range(2):
        body = json.dumps({'model': MODELS[model], 'messages': messages, 'reasoning_effort': EFFORT,
                           'response_format': {'type': 'json_object'}}).encode()
        request = urllib.request.Request(API, body, {'Content-Type': 'application/json',
                                                     'Authorization': f'Bearer {api_key()}'})
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                content = json.load(response)['choices'][0]['message']['content']
        except urllib.error.HTTPError as error:
            raise RuntimeError(f'OpenAI API {error.code}: {error.read().decode()[:300]}') from None
        try:
            reply = json.loads(content)
            if isinstance(reply, dict):
                return reply
        except (TypeError, json.JSONDecodeError):
            pass
        messages += [{'role': 'assistant', 'content': content or ''},
                     {'role': 'user', 'content': 'That was not a single valid JSON object. Reply with only the JSON object.'}]
    raise RuntimeError('OpenAI returned invalid JSON twice')

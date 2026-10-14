from __future__ import annotations
import json, time, consul
from config.environment import settings
_MAX_RETRIES = 3

def _client(): return consul.Consul(host=settings.CONSUL_HOST, port=settings.CONSUL_PORT)
class ConsulClient:
    def _retry(self, fn, *args, **kwargs):
        last = None
        for i in range(1, _MAX_RETRIES + 1):
            try: return fn(*args, **kwargs)
            except Exception as exc: last = exc; time.sleep(0.5 * i)
        raise last
    def get(self, key):
        def fn():
            _, data = _client().kv.get(key)
            if not data or data.get("Value") is None: return None
            raw = data["Value"].decode("utf-8")
            try: return json.loads(raw)
            except Exception: return raw
        return self._retry(fn)
    def put(self, key, value):
        serialized = json.dumps(value, default=str) if isinstance(value, (dict, list)) else str(value)
        return self._retry(lambda: _client().kv.put(key, serialized))
    def get_int(self, key, default=0):
        v = self.get(key)
        try: return int(v) if v is not None else default
        except Exception: return default
    def get_bool(self, key, default=False):
        v = self.get(key)
        if v is None: return default
        if isinstance(v, bool): return v
        return str(v).lower() == "true"
    def get_str(self, key, default=""):
        v = self.get(key)
        return str(v) if v is not None else default
    def check_connectivity(self):
        try: _client().status.leader(); return True
        except Exception: return False
consul_client = ConsulClient()

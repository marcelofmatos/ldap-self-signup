"""Rate limit em memória (janela deslizante). Vale para 1 réplica, como no deploy previsto."""
import threading
import time
from collections import defaultdict, deque


class LimiteTaxa:
    def __init__(self, maximo: int, janela_s: int, relogio=time.monotonic):
        self.maximo, self.janela, self.relogio = maximo, janela_s, relogio
        self._eventos = defaultdict(deque)
        self._lock = threading.Lock()

    def permitir(self, chave: str) -> bool:
        agora = self.relogio()
        with self._lock:
            fila = self._eventos[chave]
            while fila and fila[0] <= agora - self.janela:
                fila.popleft()
            if len(fila) >= self.maximo:
                return False
            fila.append(agora)
            return True

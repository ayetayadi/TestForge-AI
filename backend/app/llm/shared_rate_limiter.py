import time
import threading
from collections import deque


class SharedRateLimiter:
    """Rate limiter thread-safe partagé entre tous les workers."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, requests_per_minute: int = 8):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, requests_per_minute: int = 8):
        if self._initialized:
            return
        
        self.requests_per_minute = requests_per_minute
        self.window = 60  # secondes
        self.timestamps = deque(maxlen=requests_per_minute)
        self._lock = threading.Lock()
        self._initialized = True
        
        print(f"[RATE LIMITER] Initialized: {requests_per_minute} req/min")
    
    def can_make_request(self) -> tuple[bool, float]:
        """Vérifie si on peut faire une requête."""
        with self._lock:
            now = time.time()
            
            # Nettoie les timestamps trop vieux
            while self.timestamps and now - self.timestamps[0] > self.window:
                self.timestamps.popleft()
            
            if len(self.timestamps) >= self.requests_per_minute:
                oldest = self.timestamps[0]
                wait_time = self.window - (now - oldest)
                return False, wait_time
            
            return True, 0
    
    def record_request(self):
        """Enregistre une requête."""
        with self._lock:
            now = time.time()
            self.timestamps.append(now)
            print(f"[RATE LIMITER] Request recorded. {len(self.timestamps)}/{self.requests_per_minute} in last minute")
    
    def get_wait_time(self) -> float:
        """Retourne le temps d'attente nécessaire."""
        can, wait_time = self.can_make_request()
        return wait_time if not can else 0.0


# Instance globale
_rate_limiter = None

def get_rate_limiter() -> SharedRateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = SharedRateLimiter(requests_per_minute=8)
    return _rate_limiter
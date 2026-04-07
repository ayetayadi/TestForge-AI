import numpy as np
from typing import Optional, Any
from collections import OrderedDict
from app.core.config import settings


class LRUCache:
    """
    LRU (Least Recently Used) cache.
    Cache mémoire partagé entre tous les modules.
    """
    
    def __init__(self, max_size: int = 1000):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Récupère une valeur du cache."""
        if key in self.cache:
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any):
        """Ajoute ou met à jour une valeur dans le cache."""
        if key in self.cache:
            self.cache.move_to_end(key)
        else:
            if len(self.cache) >= self.max_size:
                self.cache.popitem(last=False)
        self.cache[key] = value
    
    def delete(self, key: str) -> bool:
        """Supprime une clé du cache."""
        if key in self.cache:
            del self.cache[key]
            return True
        return False
    
    def exists(self, key: str) -> bool:
        """Vérifie si une clé existe dans le cache."""
        return key in self.cache
    
    def clear(self):
        """Vide complètement le cache."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    def stats(self) -> dict:
        """Retourne les statistiques du cache."""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": f"{hit_rate:.1f}%",
        }
    
    def get_all(self) -> dict:
        """Retourne tout le cache (utile pour le debugging)."""
        return dict(self.cache)
    
    def keys(self) -> list:
        """Retourne toutes les clés du cache."""
        return list(self.cache.keys())


# =========================
# CACHES SPÉCIALISÉS
# =========================

class EmbeddingCache(LRUCache):
    """Cache spécialisé pour les embeddings."""
    
    def __init__(self):
        super().__init__(max_size=settings.MEMORY_CACHE_SIZE)
        self.embedding_dim = settings.EMBEDDING_DIM
    
    def stats(self) -> dict:
        """Statistiques spécifiques aux embeddings."""
        base_stats = super().stats()
        base_stats["memory_kb"] = len(self.cache) * self.embedding_dim * 4 / 1024
        return base_stats


class SSECache(LRUCache):
    """Cache pour les connexions SSE."""
    
    def __init__(self):
        super().__init__(max_size=1000)  # Max 1000 job_ids
    
    def add_connection(self, job_id: str, queue):
        """Ajoute une connexion SSE pour un job."""
        connections = self.get(job_id)
        if connections is None:
            connections = []
            self.set(job_id, connections)
        connections.append(queue)
    
    def remove_connection(self, job_id: str, queue):
        """Retire une connexion SSE."""
        connections = self.get(job_id)
        if connections:
            try:
                connections.remove(queue)
            except ValueError:
                pass
            if not connections:
                self.delete(job_id)
    
    def get_connections(self, job_id: str) -> list:
        """Récupère toutes les connexions pour un job."""
        return self.get(job_id) or []
    
    def has_connections(self, job_id: str) -> bool:
        """Vérifie si un job a des connexions actives."""
        connections = self.get(job_id)
        return bool(connections)


# =========================
# INSTANCES GLOBALES
# =========================

# Cache général pour embeddings
_embedding_cache = None

# Cache pour SSE
_sse_cache = None

# Cache pour d'autres usages (temporaire)
_temp_cache = None


def get_embedding_cache() -> EmbeddingCache:
    """Retourne l'instance du cache d'embeddings."""
    global _embedding_cache
    if _embedding_cache is None:
        _embedding_cache = EmbeddingCache()
    return _embedding_cache


def get_sse_cache() -> SSECache:
    """Retourne l'instance du cache SSE."""
    global _sse_cache
    if _sse_cache is None:
        _sse_cache = SSECache()
    return _sse_cache


def get_temp_cache(max_size: int = 1000) -> LRUCache:
    """Retourne un cache temporaire."""
    global _temp_cache
    if _temp_cache is None:
        _temp_cache = LRUCache(max_size=max_size)
    return _temp_cache


def clear_all_caches():
    """Vide tous les caches mémoire."""
    if _embedding_cache:
        _embedding_cache.clear()
    if _sse_cache:
        _sse_cache.clear()
    if _temp_cache:
        _temp_cache.clear()
    print("[CACHE] All memory caches cleared")


def get_all_cache_stats() -> dict:
    """Retourne les statistiques de tous les caches."""
    stats = {}
    
    if _embedding_cache:
        stats["embeddings"] = _embedding_cache.stats()
    if _sse_cache:
        stats["sse"] = _sse_cache.stats()
    if _temp_cache:
        stats["temp"] = _temp_cache.stats()
    
    return stats
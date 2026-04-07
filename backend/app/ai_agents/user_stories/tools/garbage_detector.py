import re
from typing import Dict


class GarbageDetector:
    """Détecte les stories qui sont du garbage (textes invalides)"""
    
    def __init__(self):
        self.min_length = 10
        self.max_length = 5000
        
        # Patterns de garbage
        self.garbage_patterns = [
            r"^[0-9\s]+$",           # Seulement des chiffres
            r"^[a-zA-Z\s]{0,5}$",     # Trop court
            r"lorem ipsum",           # Texte de remplissage
            r"test test test",        # Répétition
            r"^[^a-zA-Z]+$",          # Pas de lettres
        ]
    
    def is_garbage(self, story: str) -> bool:
        """Vérifie si une story est du garbage"""
        if not story:
            return True
        
        story_lower = story.lower().strip()
        
        # Longueur
        if len(story_lower) < self.min_length:
            return True
        
        if len(story_lower) > self.max_length:
            return True
        
        # Patterns
        for pattern in self.garbage_patterns:
            if re.search(pattern, story_lower):
                return True
        
        return False
    
    def get_garbage_score(self, story: str) -> float:
        """Retourne un score de garbage (0 = normal, 1 = garbage)"""
        if self.is_garbage(story):
            return 0.3
        return 1.0


garbage_detector = GarbageDetector()
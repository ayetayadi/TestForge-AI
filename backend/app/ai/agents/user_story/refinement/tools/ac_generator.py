import re
from typing import List
from app.utils.common.text_quality_utils import detect_language

class ACGenerator:

    def generate(self, story: str, existing_ac: List[str] = None) -> List[str]:

        lang = detect_language(story)
        text = story.lower()

        if self._is_login_story(text):
            return self._login_ac(lang)

        if self._is_register_story(text):
            return self._register_ac(lang)

        if self._is_create_story(text):
            return self._create_ac(lang)

        if self._is_delete_story(text):
            return self._delete_ac(lang)

        if self._is_update_story(text):
            return self._update_ac(lang)

        if existing_ac:
            print("[AC] Using existing AC")
            return existing_ac
    
        print("[AC] No AC generated (unknown story)")
        return []


    # ======================
    # Detection
    # ======================

    def _is_login_story(self, text: str) -> bool:
        return any(w in text for w in ["login", "log in", "connexion", "connecter"])

    def _is_register_story(self, text: str) -> bool:
        return any(w in text for w in ["register", "sign up", "inscription", "créer un compte"])

    def _is_create_story(self, text: str) -> bool:
        return any(w in text for w in ["create", "add", "créer", "ajouter"])

    def _is_delete_story(self, text: str) -> bool:
        return any(w in text for w in ["delete", "remove", "supprimer"])

    def _is_update_story(self, text: str) -> bool:
        return any(w in text for w in ["update", "edit", "modifier", "mettre à jour"])

    # ======================
    # Templates (TESTABLE)
    # ======================

    def _login_ac(self, lang):
        if lang == "fr":
            return [
                "L'utilisateur saisit un email et un mot de passe",
                "L'utilisateur est connecté avec des identifiants valides",
                "Un message d’erreur est affiché si les identifiants sont invalides",
                "L'utilisateur est redirigé vers la page principale après connexion",
            ]
        return [
            "The user enters an email and password",
            "The user is logged in with valid credentials",
            "An error message is displayed if credentials are invalid",
            "The user is redirected after login",
        ]

    def _register_ac(self, lang):
        if lang == "fr":
            return [
                "L'utilisateur saisit un email et un mot de passe valides",
                "Un message d’erreur est affiché si l’email est invalide",
                "Le compte est créé après soumission valide",
                "Un message de confirmation est affiché après inscription",
            ]
        return [
            "The user enters a valid email and password",
            "An error message is displayed if the email is invalid",
            "The account is created after valid submission",
            "A confirmation message is displayed after registration",
        ]

    def _create_ac(self, lang):
        if lang == "fr":
            return [
                "L'utilisateur saisit les données requises pour créer un élément",
                "Un message d’erreur est affiché si un champ obligatoire est manquant",
                "L’élément est créé après validation des données",
                "L’élément créé est visible dans la liste",
            ]
        return [
            "The user enters required data to create an item",
            "An error message is displayed if a required field is missing",
            "The item is created after validation",
            "The created item is visible in the list",
        ]

    def _delete_ac(self, lang):
        if lang == "fr":
            return [
                "L'utilisateur déclenche la suppression d’un élément",
                "Une confirmation est demandée avant suppression",
                "L’élément est supprimé après confirmation",
                "L’élément supprimé n’est plus visible",
            ]
        return [
            "The user triggers item deletion",
            "A confirmation is required before deletion",
            "The item is removed after confirmation",
            "The deleted item is no longer visible",
        ]

    def _update_ac(self, lang):
        if lang == "fr":
            return [
                "L'utilisateur modifie les données d’un élément existant",
                "Un message d’erreur est affiché si les données sont invalides",
                "Les modifications sont enregistrées après validation",
                "Les données mises à jour sont affichées",
            ]
        return [
            "The user updates an existing item",
            "An error message is displayed if data is invalid",
            "Changes are saved after validation",
            "Updated data is displayed",
        ]


ac_generator = ACGenerator()
"""
Génère risk_dataset.xlsx avec 300 user stories réalistes.

Catégories : Auth, CRUD simple, CRUD critique, Paiement,
             Recherche/Filtre, Notification, Export/Rapport,
             Admin/Rôles, Intégration API, Validation/Upload

Principe INVEST respecté :
  - Indépendant, Négociable, Valuable, Estimable, Small, Testable
  - Critères d'acceptation spécifiques et testables pour chaque US
"""

import pandas as pd
import random

random.seed(42)

# ============================================================
# POOL DE USER STORIES  (user_story, criteres, probabilite, impact)
# ============================================================

RAW = []

# ─────────────────────────────────────────────────
# P=1 / I=1  — Cosmétique / UI statique
# ─────────────────────────────────────────────────
UI_COSMETIC = [
    (
        "En tant qu'utilisateur, je veux modifier la couleur principale du thème afin que l'interface respecte la charte graphique.",
        "Le changement s'applique immédiatement sans rechargement | La couleur reste après déconnexion/reconnexion | Aucune donnée métier n'est modifiée",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux changer l'icône du bouton de validation afin que l'action soit plus reconnaissable.",
        "La nouvelle icône s'affiche sur tous les navigateurs supportés | L'ancienne icône disparaît | Le comportement du bouton reste inchangé",
        1, 1
    ),
    (
        "En tant qu'administrateur, je veux corriger une faute de frappe dans le libellé 'Enrgistrer' afin que l'interface soit professionnelle.",
        "Le libellé affiche 'Enregistrer' après correction | Aucun autre texte n'est modifié | La correction est présente sur tous les écrans concernés",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux ajuster la taille de la police des titres afin que la lecture soit plus confortable.",
        "La taille appliquée correspond à la valeur configurée | Le changement est cohérent sur mobile et desktop | Aucune donnée n'est affectée",
        1, 1
    ),
    (
        "En tant qu'agent support, je veux renommer le bouton 'OK' en 'Confirmer' afin que l'action soit plus explicite.",
        "Le bouton affiche 'Confirmer' dans toutes les langues configurées | Le comportement on-click reste identique | Aucune régression visuelle sur les autres boutons",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir une infobulle sur le champ 'Code postal' afin de comprendre le format attendu.",
        "L'infobulle s'affiche au survol et au focus | Le texte indique le format exact (ex: 5 chiffres) | L'infobulle disparaît quand le champ perd le focus",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que le logo de l'application soit centré dans la barre de navigation afin que l'en-tête soit équilibré.",
        "Le logo est centré sur desktop et mobile | La position est stable au scroll | Aucun autre élément de navigation n'est déplacé",
        1, 1
    ),
    (
        "En tant qu'administrateur, je veux mettre à jour l'année affichée dans le pied de page afin que l'application paraisse à jour.",
        "L'année affichée est l'année courante | La modification est visible sur toutes les pages | Aucun lien du pied de page n'est cassé",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les messages de succès s'affichent en vert afin de les distinguer facilement des erreurs.",
        "Les messages de succès utilisent la couleur #28a745 | Les messages d'erreur restent en rouge | Le changement s'applique à tous les types de toast/alert",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux un placeholder explicite dans le champ de recherche afin de savoir quoi saisir.",
        "Le placeholder affiche 'Rechercher par nom, email...' | Le placeholder disparaît dès la première saisie | Le comportement de recherche est inchangé",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que le menu latéral se replie automatiquement sur mobile afin de libérer de l'espace.",
        "Le menu est replié par défaut sur écrans < 768px | Un bouton burger permet de l'ouvrir | Le contenu principal occupe 100% de la largeur quand le menu est replié",
        1, 1
    ),
    (
        "En tant qu'administrateur, je veux personnaliser le message d'accueil de la page d'accueil afin de l'adapter à la saison.",
        "Le message s'affiche sur la page d'accueil | La modification est visible sans cache | Aucune logique métier n'est affectée",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les lignes du tableau alternent de couleur afin de faciliter la lecture.",
        "Les lignes paires et impaires ont des couleurs distinctes | Le contraste respecte WCAG AA | Le tri et la pagination ne brisent pas l'alternance",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir une animation de chargement pendant les requêtes afin de savoir que le système traite.",
        "Le spinner s'affiche dès le déclenchement de la requête | Le spinner disparaît à la fin du chargement | Aucune interaction n'est bloquée pendant l'animation",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les champs obligatoires soient marqués d'un astérisque afin de savoir ce qui est requis.",
        "Un astérisque rouge apparaît après le libellé des champs requis | Une légende 'Champ obligatoire' est présente sur le formulaire | Les champs non obligatoires n'ont pas d'astérisque",
        1, 1
    ),
]

# ─────────────────────────────────────────────────
# P=1 / I=2  — UI avec légère valeur fonctionnelle
# ─────────────────────────────────────────────────
UI_FUNCTIONAL_LOW = [
    (
        "En tant qu'utilisateur, je veux réorganiser les colonnes du tableau de bord afin de prioriser les informations importantes.",
        "Le glisser-déposer fonctionne pour réordonner les colonnes | L'ordre est sauvegardé pour l'utilisateur | La réorganisation ne modifie pas les données affichées",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux masquer les colonnes non pertinentes du tableau afin de ne voir que l'essentiel.",
        "Un menu permet de cocher/décocher chaque colonne | Les préférences sont conservées entre sessions | Au minimum une colonne reste visible",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux que la barre de navigation reste visible au scroll afin d'accéder rapidement aux menus.",
        "La barre reste fixe en haut au défilement | L'en-tête ne cache pas le contenu en dessous | Le comportement est identique sur mobile",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux un bouton 'Retour en haut' afin de revenir au sommet des longues pages.",
        "Le bouton apparaît après 300px de scroll | Un clic ramène le scroll à 0 avec animation fluide | Le bouton disparaît quand on est en haut",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le formulaire garde mes saisies si je navigue accidentellement afin de ne pas tout ressaisir.",
        "Les données sont conservées en mémoire de session | Un message d'avertissement s'affiche avant de quitter | Les données effacées après soumission réussie",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux un mode sombre afin de réduire la fatigue visuelle en soirée.",
        "Le mode sombre inverse les couleurs de fond/texte | La préférence est sauvegardée | Tous les composants respectent le thème (tableaux, modales, formulaires)",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir le nombre de résultats trouvés lors d'une recherche afin d'évaluer la pertinence.",
        "Le compteur affiche 'X résultat(s) trouvé(s)' | Il se met à jour à chaque filtre appliqué | Affiche '0 résultat' si aucun match",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux ajouter des éléments à mes favoris afin d'y accéder rapidement.",
        "Un clic sur l'étoile ajoute/retire l'élément des favoris | Les favoris sont accessibles depuis le menu utilisateur | La liste des favoris persiste entre sessions",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir une pagination afin de naviguer entre les pages de résultats.",
        "La pagination affiche les boutons Précédent/Suivant et les numéros de page | La page courante est mise en évidence | Naviguer entre pages ne recharge pas la page entière",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux trier un tableau par colonne afin d'organiser les données selon mes besoins.",
        "Un clic sur l'en-tête de colonne trie par ordre croissant | Un second clic trie par ordre décroissant | Une flèche indique la colonne et le sens de tri actif",
        1, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=2  — CRUD simple, profil utilisateur
# ─────────────────────────────────────────────────
CRUD_SIMPLE = [
    (
        "En tant qu'utilisateur, je veux modifier mon nom d'affichage afin que mon profil soit à jour.",
        "Le nouveau nom est visible immédiatement sur le profil | Le nom est limité à 50 caractères | Un message de confirmation s'affiche après sauvegarde",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux changer ma photo de profil afin de personnaliser mon compte.",
        "Les formats acceptés sont JPG et PNG uniquement | La taille maximale est 2 Mo | La photo est redimensionnée à 200x200px automatiquement",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux mettre à jour ma biographie afin que les autres membres me connaissent mieux.",
        "La biographie accepte jusqu'à 500 caractères | Un compteur de caractères restants s'affiche | La mise à jour est visible immédiatement sur le profil public",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux supprimer un commentaire que j'ai posté afin de corriger une erreur.",
        "Seul l'auteur peut supprimer son commentaire | Une confirmation est demandée avant suppression | Le commentaire disparaît immédiatement de la liste",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux créer une note personnelle afin de sauvegarder des informations importantes.",
        "La note accepte texte brut jusqu'à 2000 caractères | La date de création est enregistrée automatiquement | La note est visible uniquement par son auteur",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux modifier une note existante afin de la mettre à jour.",
        "Le contenu modifié est sauvegardé à la validation | La date de dernière modification est mise à jour | L'historique des modifications n'est pas conservé",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux supprimer une note afin de ne garder que les informations pertinentes.",
        "La suppression est définitive après confirmation | La note disparaît immédiatement de la liste | Aucun autre utilisateur n'est affecté",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux créer un tag sur un article afin de le catégoriser.",
        "Le tag est limité à 30 caractères alphanumériques | Un article peut avoir jusqu'à 10 tags | Les tags sont visibles publiquement sur l'article",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux modifier mon adresse email de contact afin de recevoir les notifications sur la bonne adresse.",
        "La nouvelle adresse doit être confirmée par email avant d'être active | L'ancienne adresse reste active jusqu'à confirmation | Un email de notification est envoyé à l'ancienne adresse",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux gérer mes préférences de notifications afin de ne recevoir que les alertes utiles.",
        "Chaque type de notification est activable/désactivable indépendamment | Les préférences sont sauvegardées immédiatement | Les notifications désactivées ne sont pas envoyées",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux archiver un document afin de le retirer de la vue principale sans le supprimer.",
        "L'archivage déplace le document dans la section 'Archives' | Le document archivé reste accessible et consultable | Un bouton 'Désarchiver' permet de le restaurer",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux dupliquer un formulaire existant afin de gagner du temps lors de la création.",
        "La copie inclut tous les champs et configurations du formulaire original | La copie est créée avec le suffixe '(copie)' | La copie est indépendante de l'original",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux ajouter une adresse de livraison afin d'avoir plusieurs adresses disponibles.",
        "Jusqu'à 5 adresses de livraison peuvent être enregistrées | Chaque adresse a un libellé (Maison, Bureau...) | Une adresse peut être définie comme adresse par défaut",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux modifier une adresse de livraison existante afin de la maintenir à jour.",
        "Tous les champs de l'adresse sont éditables | La modification est sauvegardée à la confirmation | Les commandes passées avec l'ancienne adresse ne sont pas affectées",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux supprimer une adresse de livraison afin de nettoyer mon carnet d'adresses.",
        "La suppression est impossible si l'adresse est utilisée dans une commande en cours | Une confirmation est demandée avant suppression | L'adresse par défaut ne peut être supprimée que si une autre existe",
        2, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Recherche, filtre, export simple
# ─────────────────────────────────────────────────
SEARCH_FILTER = [
    (
        "En tant qu'utilisateur, je veux filtrer la liste des produits par catégorie afin de trouver rapidement ce que je cherche.",
        "Le filtre s'applique instantanément sans rechargement | Plusieurs catégories peuvent être sélectionnées simultanément | Un bouton 'Effacer les filtres' remet la liste à l'état initial",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux rechercher un utilisateur par nom ou email afin de le trouver rapidement.",
        "La recherche s'active dès 3 caractères saisis | Les résultats s'affichent en moins de 500ms | La recherche est insensible aux accents et à la casse",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux filtrer les commandes par statut (en attente, expédié, livré) afin de suivre mes achats.",
        "Chaque statut correspond à une couleur distincte | Le filtre est persistant pendant la session | Le total de commandes par statut est affiché",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux filtrer les entrées par plage de dates afin d'analyser une période précise.",
        "Un calendrier permet de sélectionner les dates de début et de fin | La plage s'applique au champ 'date de création' | Un message s'affiche si aucun résultat ne correspond",
        2, 3
    ),
    (
        "En tant qu'administrateur, je veux exporter la liste des utilisateurs en CSV afin de l'analyser dans Excel.",
        "L'export contient les colonnes : nom, email, rôle, date d'inscription | Les données sont encodées en UTF-8 | L'export ne contient pas de mots de passe ni tokens",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux rechercher dans le contenu des documents afin de retrouver un fichier précis.",
        "La recherche porte sur le nom et les métadonnées du document | Les résultats affichent le nom, la date et le propriétaire | Aucun contenu sensible n'est indexé sans permission",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux filtrer les tâches par priorité afin de me concentrer sur les plus urgentes.",
        "Les priorités disponibles sont : faible, moyenne, haute, critique | Plusieurs priorités peuvent être sélectionnées | Le nombre de tâches par priorité est affiché",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux exporter un rapport en PDF afin de le partager avec des collègues hors-ligne.",
        "Le PDF inclut les en-têtes, le logo et la date de génération | Les tableaux sont correctement formatés | L'export est limité à 1000 lignes par défaut",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux trier les résultats de recherche par pertinence afin de voir les meilleures correspondances en premier.",
        "Le tri par défaut est par pertinence décroissante | D'autres tris sont disponibles (date, nom) | La pertinence est calculée sur le titre et la description",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux sauvegarder un filtre personnalisé afin de le réutiliser sans le reconfigurer.",
        "Le filtre sauvegardé est nommé par l'utilisateur | Jusqu'à 10 filtres sauvegardés par utilisateur | Un filtre sauvegardé peut être supprimé",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=2  — Fonctionnalités utiles, risque moyen, impact limité
# ─────────────────────────────────────────────────
FUNCTIONAL_MEDIUM_LOW = [
    (
        "En tant qu'utilisateur, je veux importer un fichier CSV de contacts afin d'ajouter plusieurs contacts en une seule fois.",
        "Les formats acceptés sont CSV et XLSX uniquement | La taille maximale est 5 Mo | Les lignes en erreur sont signalées dans un rapport d'import sans bloquer les lignes valides",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux planifier l'envoi d'un message afin qu'il parte à une heure précise.",
        "La date et l'heure de planification sont sélectionnables | Un message planifié peut être annulé avant l'envoi | L'heure de planification est en heure locale de l'utilisateur",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux recevoir un rappel avant l'expiration de mon abonnement afin de le renouveler à temps.",
        "Le rappel est envoyé 30, 7 et 1 jour avant expiration | Le canal de rappel (email/SMS) est configurable | Le rappel contient un lien direct vers la page de renouvellement",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir l'historique de mes actions afin d'auditer mes modifications.",
        "L'historique affiche les 30 derniers jours | Chaque entrée indique l'action, la date et l'IP | L'historique est en lecture seule et non modifiable",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux générer un lien de partage temporaire afin de partager un document sans compte.",
        "Le lien expire après 7 jours par défaut | La durée d'expiration est configurable (1-30 jours) | Le lien permet uniquement la consultation, pas la modification",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux télécharger un document en plusieurs formats (PDF, DOCX) afin de l'utiliser dans différents outils.",
        "Les formats disponibles sont PDF et DOCX | Le téléchargement démarre sans délai | Le fichier téléchargé contient exactement le contenu affiché",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux commenter une tâche afin de communiquer avec l'équipe sans quitter l'application.",
        "Les commentaires sont visibles par tous les membres du projet | Un commentaire peut être édité dans les 15 minutes | Les membres sont notifiés des nouveaux commentaires",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir les statistiques de consultation de mes documents partagés afin de mesurer leur impact.",
        "Les statistiques incluent nombre de vues et téléchargements | Les données sont agrégées par jour | Les stats sont disponibles pour les 30 derniers jours",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer la durée de session inactive afin de contrôler la sécurité des connexions.",
        "La durée configurable est entre 5 et 480 minutes | La valeur par défaut est 30 minutes | Un avertissement s'affiche 5 minutes avant l'expiration de session",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir une carte de chaleur des visites afin d'identifier les sections les plus consultées.",
        "La carte s'affiche sur un overlay de la page | Les zones chaudes sont en rouge, les zones froides en bleu | Les données sont basées sur les 7 derniers jours",
        3, 2
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=3  — Workflow, notification, intégration légère
# ─────────────────────────────────────────────────
WORKFLOW_MEDIUM = [
    (
        "En tant qu'utilisateur, je veux être notifié par email quand une tâche m'est assignée afin de réagir rapidement.",
        "L'email est envoyé dans les 2 minutes suivant l'assignation | L'email contient le nom de la tâche, son échéance et un lien direct | L'utilisateur peut se désabonner de ce type de notification",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux soumettre un formulaire de demande de congé afin que mon manager puisse l'approuver.",
        "Le formulaire exige : dates, type de congé, motif optionnel | La demande est visible immédiatement dans le tableau du manager | L'utilisateur est notifié de l'approbation ou du rejet",
        3, 3
    ),
    (
        "En tant que manager, je veux approuver ou rejeter une demande de congé afin de gérer le planning de l'équipe.",
        "L'approbation ou le rejet est transmis à l'employé par email | Le solde de congés est mis à jour après approbation | Une décision peut être accompagnée d'un commentaire",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux recevoir des notifications push dans le navigateur afin d'être alerté même hors de l'application.",
        "L'utilisateur est invité à autoriser les notifications | Les notifications push arrivent en moins de 5 secondes | L'utilisateur peut révoquer la permission depuis ses paramètres",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir toutes mes notifications dans un centre de notifications afin de ne rien manquer.",
        "Les notifications non lues s'affichent avec un badge | Un clic sur une notification redirige vers la ressource concernée | Les notifications peuvent être marquées comme lues en masse",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux définir des alertes automatiques sur des seuils afin d'être prévenu quand une valeur dépasse un seuil.",
        "Chaque alerte porte sur une métrique et un seuil configurable | L'alerte est envoyée une seule fois par dépassement | L'alerte se réinitialise quand la valeur repasse sous le seuil",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux synchroniser mon calendrier avec Google Calendar afin d'avoir mes tâches dans un seul outil.",
        "L'autorisation OAuth est requise et révocable | Les événements sont synchronisés en temps réel | Seules les tâches avec échéance sont exportées",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux générer un rapport hebdomadaire automatique afin de suivre l'avancement sans effort manuel.",
        "Le rapport est généré chaque lundi à 8h | Il est envoyé par email au format PDF | Le rapport couvre les 7 derniers jours d'activité",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux créer un modèle de document réutilisable afin d'accélérer la création de nouveaux documents.",
        "Le modèle peut contenir des champs variables remplaçables | Les modèles sont listés lors de la création d'un document | Un modèle peut être partagé avec l'équipe",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux suivre l'état d'avancement d'une tâche (à faire, en cours, terminé) afin de gérer mon travail.",
        "Le changement d'état déclenche une notification aux membres concernés | L'historique des changements d'état est conservé | Seul le responsable peut marquer la tâche 'terminé'",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux ajouter une pièce jointe à une tâche afin de partager des documents associés.",
        "Les formats acceptés : PDF, DOCX, XLSX, PNG, JPG | Taille maximale par fichier : 10 Mo | Jusqu'à 5 pièces jointes par tâche",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux mentionner un collègue dans un commentaire afin de l'informer directement.",
        "La mention @nom propose une liste d'autocomplétion | La personne mentionnée reçoit une notification | La mention est cliquable et redirige vers le profil",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux recevoir un résumé quotidien des activités afin d'avoir une vue d'ensemble.",
        "Le résumé est envoyé à l'heure configurée par l'utilisateur | Il liste les tâches créées, modifiées et terminées | L'utilisateur peut désactiver le résumé quotidien",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux lier une tâche à une autre afin d'exprimer une dépendance.",
        "Les types de liens disponibles sont : 'bloque', 'est bloqué par', 'est lié à' | Un avertissement s'affiche si une tâche bloquante n'est pas terminée | Les liens sont visibles sur la fiche de chaque tâche",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux exporter l'historique de mes commandes afin de le comptabiliser.",
        "L'export est disponible en CSV et PDF | Les colonnes exportées : référence, date, montant, statut | L'export peut être filtré par période (mois, trimestre, année)",
        3, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=4  — Gestion de rôles, données partagées
# ─────────────────────────────────────────────────
ROLES_MEDIUM_HIGH = [
    (
        "En tant qu'administrateur, je veux assigner un rôle à un utilisateur afin de contrôler ses accès.",
        "Les rôles disponibles sont : Lecteur, Éditeur, Administrateur | Un utilisateur ne peut avoir qu'un seul rôle à la fois | Le changement de rôle est immédiatement effectif sans reconnexion",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux créer un nouveau groupe d'utilisateurs afin de gérer les permissions par groupe.",
        "Le groupe a un nom unique et une description | Les membres peuvent être ajoutés/retirés individuellement | Les permissions du groupe s'appliquent à tous ses membres",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux suspendre temporairement un compte utilisateur afin de bloquer l'accès sans le supprimer.",
        "Un compte suspendu ne peut pas se connecter | L'utilisateur reçoit un email expliquant la suspension | La suspension est réversible par un administrateur",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux voir le journal d'audit des connexions afin de détecter des accès suspects.",
        "Chaque connexion est enregistrée avec IP, navigateur, date | Les connexions échouées sont distinguées des réussies | Le journal est filtrable par utilisateur et par plage de dates",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer des restrictions d'accès par adresse IP afin de limiter l'accès à certains réseaux.",
        "Les plages IP autorisées sont configurables en CIDR | Toute connexion hors plage est bloquée et journalisée | Un email est envoyé à l'administrateur en cas de tentative bloquée",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux désactiver un compte utilisateur inactif depuis 90 jours afin de respecter la politique de sécurité.",
        "La désactivation est automatique après 90 jours sans connexion | L'utilisateur reçoit un avertissement à J-7 | La désactivation est réversible par un administrateur",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux forcer la réinitialisation du mot de passe de tous les utilisateurs afin de réagir à un incident de sécurité.",
        "Tous les utilisateurs sont déconnectés immédiatement | Chaque utilisateur reçoit un email de réinitialisation | L'action est journalisée avec le compte administrateur ayant déclenché l'action",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux exporter la liste complète des rôles et permissions afin de documenter la politique d'accès.",
        "L'export est au format CSV ou PDF | Il inclut : utilisateur, rôle, dernière modification | L'export n'est accessible qu'aux super-administrateurs",
        3, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=3  — Intégration API, import critique
# ─────────────────────────────────────────────────
API_INTEGRATION = [
    (
        "En tant qu'utilisateur, je veux synchroniser mes données avec un service externe via API afin de centraliser mes informations.",
        "L'intégration utilise OAuth 2.0 pour l'autorisation | En cas d'échec de l'API externe, les données locales ne sont pas corrompues | Un journal de synchronisation est disponible",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer un webhook pour recevoir des événements d'un système tiers afin d'automatiser les traitements.",
        "L'URL du webhook est validée avant enregistrement | Les événements reçus sont journalisés avec leur payload | Un mécanisme de retry est en place en cas d'échec de réception",
        4, 3
    ),
    (
        "En tant qu'utilisateur, je veux importer une facture depuis un logiciel de comptabilité externe afin d'éviter la double saisie.",
        "Les formats supportés sont XML et JSON selon le standard de l'API | Les doublons sont détectés par numéro de facture | En cas d'erreur, l'import partiel est annulé (rollback)",
        4, 3
    ),
    (
        "En tant qu'utilisateur, je veux connecter mon compte à Slack afin de recevoir les alertes directement dans mon canal.",
        "L'autorisation passe par OAuth Slack | L'utilisateur choisit le canal cible | La déconnexion révoque l'accès sans supprimer les messages passés",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer une clé API pour un partenaire afin qu'il accède aux données en lecture seule.",
        "La clé API est générée de façon cryptographiquement sécurisée | La clé peut être révoquée à tout moment | L'accès est limité aux endpoints définis dans les permissions de la clé",
        4, 3
    ),
    (
        "En tant qu'utilisateur, je veux envoyer des données vers un ERP externe afin de maintenir la cohérence entre systèmes.",
        "L'envoi déclenche une validation côté ERP | Les erreurs de validation sont retournées et affichées clairement | Une file d'attente garantit la livraison même en cas de panne temporaire",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux monitorer les appels API sortants afin de détecter les anomalies de consommation.",
        "Le tableau de bord affiche le nombre d'appels par heure | Les codes d'erreur sont agrégés par type | Une alerte est déclenchée si le taux d'erreur dépasse 5%",
        4, 3
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=4  — Auth avancée, 2FA, gestion sécurisée
# ─────────────────────────────────────────────────
AUTH_COMPLEX = [
    (
        "En tant qu'utilisateur, je veux activer l'authentification à deux facteurs afin de sécuriser mon compte.",
        "L'activation nécessite de scanner un QR code TOTP (ex. Google Authenticator) | Le code TOTP expire après 30 secondes | La désactivation du 2FA exige le mot de passe actuel",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux me connecter via Google OAuth afin de ne pas gérer un mot de passe supplémentaire.",
        "Le flux OAuth respecte la RFC 6749 | L'adresse email Google est utilisée comme identifiant unique | En cas de révocation Google, la session est immédiatement invalidée",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux réinitialiser mon mot de passe par email afin de récupérer l'accès à mon compte.",
        "Le lien de réinitialisation expire après 1 heure | Le lien est à usage unique | L'ancien mot de passe est invalidé dès la création du nouveau",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux que ma session expire automatiquement après inactivité afin de protéger mon compte.",
        "La session expire après 30 minutes d'inactivité par défaut | Un avertissement s'affiche 2 minutes avant expiration | L'utilisateur est redirigé vers la page de connexion à l'expiration",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux gérer les sessions actives de mon compte afin de révoquer les connexions non reconnues.",
        "La liste affiche chaque session avec appareil, IP et date | L'utilisateur peut révoquer n'importe quelle session individuelle | 'Déconnecter toutes les sessions' est disponible et immédiat",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux être averti par email lors d'une connexion depuis un nouvel appareil afin de détecter un accès non autorisé.",
        "L'email est envoyé dans les 60 secondes suivant la connexion | Il contient l'IP, le navigateur et la date | Un lien 'Ce n'était pas moi' permet de révoquer la session immédiatement",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux changer mon mot de passe afin de maintenir la sécurité de mon compte.",
        "Le nouveau mot de passe doit contenir 8 caractères minimum, une majuscule, un chiffre et un caractère spécial | L'ancien mot de passe est exigé pour valider le changement | Toutes les autres sessions sont révoquées après le changement",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer une politique de mot de passe afin d'imposer des règles de sécurité uniformes.",
        "La politique définit : longueur minimale, complexité, durée de validité | Les utilisateurs sont avertis 7 jours avant l'expiration | Le non-respect bloque la connexion jusqu'à changement",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux recevoir un code OTP par SMS lors de la connexion afin d'ajouter une couche de sécurité.",
        "Le code OTP est à 6 chiffres et expire en 5 minutes | Trois échecs consécutifs bloquent le compte 15 minutes | Le numéro de téléphone doit être préalablement vérifié",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux bloquer l'accès après 5 tentatives de connexion échouées afin de prévenir les attaques par force brute.",
        "Le blocage dure 15 minutes après 5 tentatives | L'utilisateur reçoit un email indiquant le blocage | L'administrateur peut débloquer manuellement depuis le panneau d'administration",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux me connecter avec mon empreinte digitale sur mobile afin d'accéder rapidement sans saisir mon mot de passe.",
        "L'authentification biométrique utilise l'API WebAuthn | Le fallback vers le mot de passe est toujours disponible | La biométrie est stockée uniquement sur l'appareil, jamais sur le serveur",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer le SSO SAML afin que les employés se connectent avec leurs identifiants d'entreprise.",
        "La configuration requiert les métadonnées du fournisseur d'identité | La déconnexion du SSO déconnecte l'application | Les attributs SAML sont mappés aux rôles de l'application",
        4, 4
    ),
    (
        "En tant qu'utilisateur, je veux voir les permissions associées à mon rôle afin de comprendre ce que je peux faire.",
        "La liste des permissions est consultable depuis le profil | Les permissions sont regroupées par fonctionnalité | Les permissions ne sont pas modifiables par l'utilisateur lui-même",
        4, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=5  — Données sensibles, conformité RGPD
# ─────────────────────────────────────────────────
GDPR_SENSITIVE = [
    (
        "En tant qu'utilisateur, je veux télécharger une copie de toutes mes données personnelles afin d'exercer mon droit à la portabilité (RGPD).",
        "L'export est disponible en JSON et CSV dans les 72 heures | Il contient toutes les données : profil, activité, préférences | La demande est journalisée avec la date et l'identité",
        4, 5
    ),
    (
        "En tant qu'utilisateur, je veux demander la suppression de mon compte et de toutes mes données afin d'exercer mon droit à l'oubli (RGPD).",
        "La suppression est irréversible et confirmée par email | Les données anonymisées pour les statistiques sont conservées | La suppression est effective dans les 30 jours",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux anonymiser les données des utilisateurs inactifs afin de respecter les obligations RGPD.",
        "L'anonymisation remplace nom/email par des identifiants aléatoires | Les données anonymisées ne peuvent être rétablies | Un rapport d'anonymisation est généré",
        4, 5
    ),
    (
        "En tant qu'utilisateur, je veux retirer mon consentement au traitement marketing afin de ne plus recevoir de communications.",
        "Le retrait est effectif immédiatement | Aucun email marketing n'est envoyé après retrait | Le retrait est journalisé avec horodatage pour preuve légale",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux journaliser tous les accès aux données personnelles afin de respecter les exigences d'audit RGPD.",
        "Chaque accès enregistre : qui, quoi, quand, pourquoi | Le journal est conservé 3 ans | Le journal est en lecture seule et protégé contre la modification",
        4, 5
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=4  — Paiement, transactions sensibles
# ─────────────────────────────────────────────────
PAYMENT_HIGH = [
    (
        "En tant que client, je veux payer ma commande par carte bancaire afin de finaliser mon achat en ligne.",
        "Le formulaire de paiement utilise un champ iframe sécurisé (Stripe/Adyen) | Les données de carte ne transitent jamais par nos serveurs | Un reçu est envoyé par email après paiement réussi",
        5, 4
    ),
    (
        "En tant que client, je veux sauvegarder ma carte bancaire pour les achats futurs afin de ne pas la ressaisir.",
        "La carte est tokenisée par le prestataire de paiement | Le numéro complet n'est jamais stocké, seulement les 4 derniers chiffres | L'utilisateur peut supprimer une carte sauvegardée",
        5, 4
    ),
    (
        "En tant que client, je veux payer en plusieurs fois afin de faciliter mon budget.",
        "Les options disponibles sont : 2x, 3x, 4x sans frais | Un tableau récapitulatif des échéances est affiché | Le premier prélèvement est effectué immédiatement à la commande",
        5, 4
    ),
    (
        "En tant que client, je veux recevoir une facture PDF après chaque paiement afin de la transmettre à ma comptabilité.",
        "La facture est générée dans les 5 minutes suivant le paiement | Elle contient : montant TTC, TVA, numéro de commande, SIRET de l'émetteur | Elle est téléchargeable depuis l'espace client",
        5, 4
    ),
    (
        "En tant que client, je veux payer via PayPal afin d'utiliser mon solde PayPal.",
        "La redirection vers PayPal se fait dans la même fenêtre | En cas d'annulation sur PayPal, l'utilisateur revient au panier sans perte | Le statut de la commande est mis à jour en temps réel via webhook PayPal",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux voir le tableau de bord des transactions afin de détecter les anomalies de paiement.",
        "Le tableau affiche en temps réel les transactions des dernières 24h | Les transactions en échec sont signalées en rouge | Un filtre par montant, statut et méthode est disponible",
        5, 4
    ),
    (
        "En tant que client, je veux annuler un abonnement afin de ne plus être prélevé.",
        "L'annulation est possible à tout moment depuis l'espace client | L'accès reste actif jusqu'à la fin de la période payée | Un email de confirmation d'annulation est envoyé",
        5, 4
    ),
    (
        "En tant que client, je veux payer en cryptomonnaie afin d'utiliser mes actifs numériques.",
        "Les cryptos acceptées sont BTC et ETH | Le taux de change est fixé au moment de la génération de l'adresse de paiement | La transaction est confirmée après 3 confirmations réseau",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux émettre un avoir client afin de compenser une commande défectueuse.",
        "L'avoir est créé en saisissant le montant et la référence commande | L'avoir est envoyé par email au client | Il peut être utilisé partiellement sur une commande future",
        5, 4
    ),
    (
        "En tant que client, je veux choisir ma devise de paiement afin de connaître le montant exact dans ma monnaie locale.",
        "Les devises supportées sont : EUR, USD, GBP, CHF | Le taux de change est affiché avec la source et la date | Le montant débité correspond à la devise sélectionnée",
        5, 4
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=5  — Paiement 3DS, fraude, sécurité critique
# ─────────────────────────────────────────────────
PAYMENT_CRITICAL = [
    (
        "En tant que client, je veux valider mon paiement par carte avec l'authentification 3D Secure afin que ma transaction soit protégée contre la fraude.",
        "Le flux 3DS 2.0 est déclenché pour tous les paiements supérieurs à 30€ | L'authentification échouée annule la transaction sans débit | Un message d'erreur explicite s'affiche en cas d'échec 3DS",
        5, 5
    ),
    (
        "En tant que client, je veux effectuer un virement bancaire sécurisé vers un bénéficiaire enregistré afin de transférer des fonds.",
        "Un code de confirmation OTP est exigé pour tout virement | Le bénéficiaire doit être pré-enregistré avec un délai de 24h | Le plafond journalier est de 10 000€ configurable par l'utilisateur",
        5, 5
    ),
    (
        "En tant que client, je veux contester une transaction non reconnue afin d'être remboursé en cas de fraude.",
        "La contestation est possible dans les 60 jours suivant la transaction | Le compte est bloqué provisoirement en attente d'investigation | L'utilisateur reçoit un numéro de dossier et un délai de traitement",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux déclencher un remboursement total ou partiel afin de corriger une erreur de facturation.",
        "Le remboursement est traité en 3 à 5 jours ouvrés | Le remboursement partiel ne peut dépasser le montant initial | Un email de confirmation est envoyé au client et à l'administrateur",
        5, 5
    ),
    (
        "En tant que système, je veux détecter automatiquement les tentatives de fraude afin de bloquer les transactions suspectes.",
        "Un score de fraude est calculé en temps réel pour chaque transaction | Les transactions avec score > 80 sont bloquées automatiquement | Un analyste peut débloquer manuellement après vérification",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux chiffrer toutes les données de carte bancaire stockées afin de se conformer à la norme PCI-DSS.",
        "Le chiffrement utilise AES-256 | Les clés de chiffrement sont rotées tous les 90 jours | Aucune donnée de carte n'est lisible sans la clé privée",
        5, 5
    ),
    (
        "En tant que client, je veux que mon abonnement soit renouvelé automatiquement afin de ne pas perdre l'accès au service.",
        "Le prélèvement automatique intervient 24h avant la date d'expiration | En cas d'échec de paiement, 3 tentatives sont effectuées à 24h d'intervalle | L'accès est maintenu pendant la période de grâce de 7 jours",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux bloquer instantanément une carte bancaire compromise afin de stopper les transactions frauduleuses.",
        "Le blocage est effectif en moins de 30 secondes | Toutes les transactions en cours avec cette carte sont annulées | L'utilisateur est notifié par email et SMS immédiatement",
        5, 5
    ),
    (
        "En tant que client, je veux effectuer un paiement récurrent par mandat SEPA afin d'automatiser mes règlements mensuels.",
        "La signature du mandat SEPA est électronique et conforme à la réglementation | Le premier prélèvement nécessite un délai de préavis de 5 jours ouvrés | L'utilisateur peut révoquer le mandat avec effet au prochain prélèvement",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux générer un rapport de réconciliation bancaire afin de vérifier la cohérence entre transactions système et relevés bancaires.",
        "Le rapport compare transactions système vs relevés bancaires importés | Les écarts sont signalés avec montant et référence | Le rapport est généré quotidiennement à 6h et archivé 10 ans",
        5, 5
    ),
    (
        "En tant que client, je veux payer avec Apple Pay afin de finaliser mon achat rapidement depuis mon iPhone.",
        "Apple Pay est disponible uniquement sur les navigateurs Safari iOS | L'authentification biométrique (Face ID/Touch ID) est requise | La transaction est confirmée en moins de 3 secondes",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux configurer des règles anti-fraude personnalisées afin d'adapter la protection au profil de risque de notre activité.",
        "Les règles portent sur : montant, pays, fréquence, type de carte | Les règles sont testables en mode simulation avant activation | Une alerte est envoyée pour chaque transaction bloquée par une règle",
        5, 5
    ),
    (
        "En tant que système, je veux journaliser chaque tentative de paiement (réussie ou échouée) afin d'assurer la traçabilité réglementaire.",
        "Chaque entrée contient : timestamp, montant, devise, statut, IP, navigateur | Les logs sont conservés 10 ans conformément aux obligations légales | Les logs sont immuables et protégés contre toute modification",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux imposer l'authentification forte (SCA) pour tous les paiements conformément à la DSP2 afin de respecter la réglementation européenne.",
        "La SCA combine au moins deux facteurs parmi : connaissance, possession, inhérence | Les exemptions SCA (faible montant < 30€, marchand de confiance) sont gérées automatiquement | Tout refus de SCA annule la transaction sans débit",
        5, 5
    ),
    (
        "En tant que client, je veux recevoir une alerte immédiate pour tout paiement supérieur à 500€ afin de détecter rapidement un usage frauduleux.",
        "L'alerte est envoyée par email et SMS en moins de 60 secondes | Elle contient le montant, le marchand et la date | Un lien 'Signaler une fraude' est inclus dans l'alerte",
        5, 5
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=1  — Actions utilisateur sans impact métier
# ─────────────────────────────────────────────────
LOW_IMPACT = [
    (
        "En tant qu'utilisateur, je veux ajouter un élément à ma liste de souhaits afin de le retrouver plus tard.",
        "L'ajout est instantané et visible sans rechargement | La liste de souhaits est accessible depuis le menu utilisateur | Un article déjà dans la liste ne peut être ajouté en double",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux noter un article de 1 à 5 étoiles afin de partager mon avis.",
        "La note est visible immédiatement sur la fiche article | Un utilisateur ne peut noter qu'une seule fois par article | La note peut être modifiée en cliquant sur une autre étoile",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux partager un lien vers un article sur les réseaux sociaux afin de le recommander.",
        "Les boutons de partage couvrent : Twitter, LinkedIn, Facebook | Le lien partagé est canonique et permanent | Aucune donnée personnelle n'est transmise aux réseaux sociaux",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux imprimer une fiche produit afin de l'avoir en version papier.",
        "La version imprimée masque les éléments de navigation | Les images sont incluses dans l'impression | La mise en page est adaptée au format A4",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux laisser un commentaire public sur un article afin de partager mon expérience.",
        "Le commentaire est publié après validation manuelle | Les commentaires sont limités à 1000 caractères | L'auteur peut supprimer son propre commentaire",
        2, 1
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=3  — Sécurité importante mais impact contenu
# ─────────────────────────────────────────────────
SECURITY_HIGH = [
    (
        "En tant qu'administrateur, je veux scanner les fichiers uploadés à la recherche de malwares afin de protéger l'application.",
        "Chaque fichier est scanné avant d'être accepté | Les fichiers infectés sont rejetés avec un message d'erreur clair | Le scan s'effectue en moins de 5 secondes pour les fichiers < 10 Mo",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux chiffrer les communications internes entre microservices afin d'empêcher les interceptions.",
        "TLS 1.3 est utilisé pour toutes les communications internes | Les certificats sont renouvelés automatiquement 30 jours avant expiration | Les communications non chiffrées sont rejetées",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer un pare-feu applicatif (WAF) afin de bloquer les attaques courantes (SQLi, XSS).",
        "Le WAF bloque les payloads SQLi et XSS connus | Les tentatives bloquées sont journalisées avec IP et payload | Le WAF est en mode détection avant passage en mode blocage",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux mettre en place un rate limiting sur l'API afin de prévenir les abus.",
        "La limite est de 100 requêtes par minute par IP | Les requêtes au-delà de la limite reçoivent une réponse 429 | Un header Retry-After indique quand retenter",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux valider et assainir toutes les entrées utilisateur afin de prévenir les injections.",
        "Toutes les entrées sont validées côté serveur (pas uniquement côté client) | Les caractères spéciaux sont échappés avant insertion en base | Les champs de type numérique rejettent les chaînes non numériques",
        5, 5
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=2  — Validation avancée, upload sécurisé
# ─────────────────────────────────────────────────
VALIDATION_UPLOAD = [
    (
        "En tant qu'utilisateur, je veux uploader une pièce jointe afin de compléter mon dossier.",
        "Les extensions autorisées sont : PDF, DOCX, JPG, PNG | La taille maximale est 20 Mo | Le nom du fichier est assaini pour éviter les path traversal",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le formulaire valide mon numéro de SIRET en temps réel afin de corriger les erreurs immédiatement.",
        "La validation utilise l'algorithme de Luhn | Le message d'erreur précise si le numéro est invalide ou inexistant | La validation ne bloque pas la saisie, elle s'effectue au blur",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le champ email soit validé avant soumission afin d'éviter les erreurs de saisie.",
        "La validation respecte le format RFC 5322 | Le domaine est vérifié par une requête DNS MX | Un message d'erreur précis est affiché en cas d'email invalide",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux uploader une photo de profil avec recadrage afin de choisir la partie à afficher.",
        "L'outil de recadrage est disponible après sélection du fichier | Le ratio imposé est 1:1 | La photo finale ne dépasse pas 500 Ko après compression",
        4, 2
    ),
    (
        "En tant qu'administrateur, je veux limiter les types de fichiers uploadables afin d'empêcher l'exécution de fichiers malveillants.",
        "La vérification porte sur le type MIME réel, pas l'extension | Les fichiers exécutables (.exe, .sh, .php) sont systématiquement rejetés | Une liste blanche de types MIME est configurable",
        4, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=2  — Inscription / Onboarding
# ─────────────────────────────────────────────────
REGISTRATION = [
    (
        "En tant que visiteur, je veux créer un compte avec mon email et un mot de passe afin d'accéder aux fonctionnalités.",
        "L'email doit être unique dans le système | Le mot de passe doit contenir 8 caractères minimum | Un email de vérification est envoyé après inscription",
        2, 2
    ),
    (
        "En tant que visiteur, je veux m'inscrire via mon compte Google afin d'éviter de créer un nouveau mot de passe.",
        "Le flux OAuth Google est conforme à la RFC 6749 | L'adresse Gmail est importée automatiquement comme email principal | Un compte local est créé à la première connexion Google",
        2, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux compléter un tutoriel d'onboarding afin de comprendre les fonctionnalités principales.",
        "Le tutoriel est présenté en 5 étapes maximum | Chaque étape peut être passée | Le tutoriel ne se réaffiche pas après completion",
        2, 2
    ),
    (
        "En tant que visiteur, je veux vérifier mon adresse email après inscription afin d'activer mon compte.",
        "Le lien de vérification est valide 24 heures | Un second email peut être demandé si le premier n'arrive pas | Le compte est actif immédiatement après clic sur le lien",
        2, 2
    ),
    (
        "En tant qu'administrateur, je veux inviter un utilisateur par email afin qu'il rejoigne la plateforme.",
        "L'invitation expire après 7 jours | L'invité reçoit un lien pré-rempli avec son email | L'invitant est notifié quand l'invité accepte",
        2, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Panier e-commerce (CRUD standard, impact moyen si cassé)
# ─────────────────────────────────────────────────
CART = [
    (
        "En tant que client, je veux ajouter un produit à mon panier afin de préparer ma commande.",
        "Le compteur du panier se met à jour immédiatement | Le même produit peut être ajouté plusieurs fois | Le panier est conservé 30 jours même sans connexion (cookie)",
        2, 3
    ),
    (
        "En tant que client, je veux modifier la quantité d'un article dans mon panier afin d'ajuster ma commande.",
        "La quantité minimum est 1, maximum 99 | Le sous-total se recalcule immédiatement | Si le stock est insuffisant, un message d'avertissement s'affiche",
        2, 3
    ),
    (
        "En tant que client, je veux supprimer un article de mon panier afin de ne commander que ce dont j'ai besoin.",
        "La suppression est immédiate sans confirmation | Un lien 'Annuler' est disponible pendant 5 secondes | Le total du panier se met à jour automatiquement",
        2, 3
    ),
    (
        "En tant que client, je veux appliquer un code promo afin de bénéficier d'une réduction.",
        "Le code est validé en temps réel à la saisie | La réduction s'affiche avant la validation de la commande | Un code expiré ou invalide affiche un message d'erreur précis",
        2, 3
    ),
    (
        "En tant que client, je veux voir le récapitulatif de ma commande avant de payer afin de vérifier les articles.",
        "Le récapitulatif liste : articles, quantités, prix unitaires, frais de livraison, total TTC | Les taxes appliquées sont détaillées | Un bouton 'Modifier' permet de retourner au panier",
        2, 3
    ),
    (
        "En tant que client, je veux choisir mon mode de livraison afin d'adapter la vitesse et le coût à mes besoins.",
        "Au moins deux modes sont proposés (standard et express) | Les délais et coûts sont affichés clairement | Le mode choisi est mémorisé pour la prochaine commande",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=4  — Gestion de stock, inventaire
# ─────────────────────────────────────────────────
INVENTORY = [
    (
        "En tant que gestionnaire, je veux ajouter un nouveau produit au catalogue afin de le rendre disponible à la vente.",
        "Le produit doit avoir un nom, un prix et une référence unique | Les images acceptées sont JPG/PNG jusqu'à 5 Mo | Le produit est publié uniquement après validation",
        3, 4
    ),
    (
        "En tant que gestionnaire, je veux modifier le stock disponible d'un produit afin de refléter les mouvements d'inventaire.",
        "La modification du stock est journalisée avec l'utilisateur et la date | Un stock négatif est impossible | Une alerte est déclenchée si le stock passe sous le seuil minimum configuré",
        3, 4
    ),
    (
        "En tant que gestionnaire, je veux désactiver un produit afin de le retirer de la vente sans le supprimer.",
        "Le produit désactivé n'apparaît plus dans le catalogue client | Les commandes en cours avec ce produit ne sont pas affectées | Le produit peut être réactivé à tout moment",
        3, 4
    ),
    (
        "En tant que gestionnaire, je veux configurer une alerte de stock bas afin d'être prévenu avant la rupture.",
        "Le seuil d'alerte est configurable par produit | L'alerte est envoyée par email au gestionnaire | L'alerte ne se répète pas tant que le stock reste bas (une alerte par franchissement de seuil)",
        3, 4
    ),
    (
        "En tant que gestionnaire, je veux importer une liste de produits depuis un fichier Excel afin d'alimenter le catalogue en masse.",
        "Les colonnes requises sont : référence, nom, prix, stock | Les lignes en erreur sont signalées dans un rapport d'import | Les produits existants sont mis à jour, les nouveaux sont créés",
        3, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=4  — Gestion des commandes, fulfillment
# ─────────────────────────────────────────────────
ORDER_MANAGEMENT = [
    (
        "En tant que gestionnaire, je veux valider une commande afin de déclencher la préparation.",
        "La validation déclenche une notification au préparateur | Le stock des articles est décrémenté à la validation | Un bon de préparation est généré automatiquement",
        4, 4
    ),
    (
        "En tant que gestionnaire, je veux annuler une commande afin de libérer les articles réservés.",
        "L'annulation est possible uniquement si la commande n'est pas expédiée | Le stock est restitué immédiatement | Le client est notifié de l'annulation avec le motif",
        4, 4
    ),
    (
        "En tant que client, je veux suivre ma commande en temps réel afin de connaître sa position et le délai de livraison.",
        "Un numéro de suivi est fourni dans l'email d'expédition | La page de suivi affiche les étapes : préparé, expédié, en transit, livré | La date de livraison estimée est affichée",
        4, 4
    ),
    (
        "En tant que gestionnaire, je veux traiter un retour produit afin de rembourser le client ou d'envoyer un remplacement.",
        "Le retour doit être initié dans les 30 jours suivant la livraison | Le motif du retour est obligatoire | Le remboursement ou le remplacement est traité dans les 5 jours ouvrés",
        4, 4
    ),
    (
        "En tant que gestionnaire, je veux voir le tableau de bord des commandes du jour afin de piloter la logistique.",
        "Le tableau affiche : commandes reçues, en préparation, expédiées, livrées | Les données se rafraîchissent toutes les 5 minutes | Les commandes urgentes (J-1 de la promesse) sont signalées",
        4, 4
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Multilingue, internationalisation
# ─────────────────────────────────────────────────
I18N = [
    (
        "En tant qu'utilisateur, je veux choisir la langue de l'interface afin de l'utiliser dans ma langue maternelle.",
        "Les langues disponibles sont : français, anglais, arabe | Le changement de langue est immédiat sans rechargement | La préférence de langue est sauvegardée sur le compte",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux que les dates soient affichées dans mon format local afin de les lire naturellement.",
        "Le format FR est JJ/MM/AAAA, le format EN est MM/DD/YYYY | Les fuseaux horaires sont respectés pour les heures | Le format est déduit de la langue sélectionnée",
        2, 3
    ),
    (
        "En tant qu'administrateur, je veux ajouter une traduction manquante depuis l'interface d'administration afin de corriger une lacune.",
        "L'interface affiche les clés de traduction manquantes par langue | Une traduction peut être ajoutée sans redémarrer l'application | Les traductions modifiées sont actives immédiatement",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=5  — Données médicales / bancaires critiques
# ─────────────────────────────────────────────────
CRITICAL_DATA = [
    (
        "En tant qu'administrateur, je veux chiffrer les données de santé des patients stockées en base afin de respecter la réglementation HDS.",
        "Le chiffrement est AES-256 au niveau des colonnes sensibles | Les clés sont gérées par un HSM | L'accès aux données déchiffrées est journalisé et soumis à authentification forte",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux effacer de manière sécurisée les données sensibles supprimées afin d'empêcher toute récupération.",
        "La suppression logique est suivie d'une suppression physique sous 30 jours | Les sauvegardes contenant ces données sont purgées | Une preuve d'effacement est générée",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux mettre en place une procédure de reprise après sinistre afin d'assurer la continuité de service.",
        "Le RPO est de 1 heure maximum | Le RTO est de 4 heures maximum | La procédure est testée trimestriellement et documentée",
        5, 5
    ),
]

# ─────────────────────────────────────────────────
# P=1 / I=1  — Accessibilité, aide contextuelle (nouveaux)
# ─────────────────────────────────────────────────
ACCESSIBILITY_COSMETIC = [
    (
        "En tant qu'utilisateur, je veux que tous les boutons icône aient un aria-label afin que les lecteurs d'écran les lisent correctement.",
        "Chaque bouton icône a un aria-label descriptif | Les lecteurs d'écran NVDA et VoiceOver lisent l'aria-label | Aucun bouton ne reste sans libellé accessible",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les éléments interactifs aient un focus visible afin de naviguer au clavier.",
        "Un contour visible s'affiche sur les éléments focusés | Le focus suit l'ordre logique de la page | Le style de focus est cohérent sur tous les navigateurs supportés",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux un lien 'Aller au contenu principal' en haut de page afin de sauter la navigation au clavier.",
        "Le lien s'affiche uniquement au focus clavier | Il redirige vers le contenu principal sans rechargement | Il est le premier élément focusable de la page",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les images informatives aient un texte alternatif afin que les non-voyants comprennent leur contenu.",
        "Chaque image informative a un attribut alt non vide et descriptif | Les images décoratives ont un alt vide | L'audit WCAG AA ne signale aucune violation sur les images",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que le contraste texte/fond respecte le standard WCAG AA afin de lire confortablement.",
        "Le ratio de contraste est au minimum 4.5:1 pour le texte normal | Il est 3:1 pour les grands textes (18px et plus) | Un audit automatisé ne signale aucune violation de contraste",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir une page d'aide contextuelle pour chaque section afin de comprendre comment l'utiliser.",
        "La page d'aide s'ouvre dans un panneau latéral | Elle contient captures d'écran et description textuelle | Elle peut être fermée sans quitter la fonctionnalité en cours",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les messages d'erreur de formulaire soient associés aux champs via aria-describedby afin que les lecteurs d'écran les lisent.",
        "Chaque erreur est reliée au champ via aria-describedby | L'erreur est annoncée à l'apparition par une region live | L'association est vérifiée par un audit axe-core sans erreur",
        1, 1
    ),
    (
        "En tant qu'administrateur, je veux changer le favicon de l'application afin que l'onglet du navigateur soit reconnaissable.",
        "Le nouveau favicon s'affiche sur tous les navigateurs supportés | Le favicon est lisible en mode clair et sombre | Aucune autre ressource statique n'est affectée",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux une barre de progression dans un formulaire multi-étapes afin de savoir à quelle étape je suis.",
        "La barre affiche le numéro d'étape actuelle sur le total | Les étapes complétées sont marquées d'un checkmark | La barre est présente et cohérente sur chaque étape",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux que les tableaux de données aient des en-têtes corrects afin que les lecteurs d'écran les interprètent bien.",
        "Les cellules d'en-tête utilisent la balise th avec scope approprié | Les lecteurs d'écran annoncent l'en-tête avec chaque cellule de données | L'audit WCAG ne signale aucun problème sur les tableaux",
        1, 1
    ),
]

# ─────────────────────────────────────────────────
# P=1 / I=2  — UX utile mais non critique (nouveaux)
# ─────────────────────────────────────────────────
UX_USEFUL = [
    (
        "En tant qu'utilisateur, je veux voir un aperçu du document avant de le télécharger afin de m'assurer que c'est le bon fichier.",
        "L'aperçu s'affiche dans une modale sans télécharger le fichier | Il est disponible pour les formats PDF et image | La modale se ferme via Échap ou le bouton Fermer",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux copier le lien vers une ressource en un clic afin de le partager facilement.",
        "Un bouton 'Copier le lien' est présent sur chaque ressource | Un toast confirme la copie dans le presse-papiers | Le lien copié est le lien permanent de la ressource",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un fil d'Ariane afin de comprendre ma position dans la hiérarchie de l'application.",
        "Le fil d'Ariane reflète la hiérarchie de navigation actuelle | Chaque élément sauf le dernier est cliquable | La page courante est affichée sans lien",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux que les champs du formulaire soient pré-remplis avec mes informations de profil afin de gagner du temps.",
        "Le nom et l'email sont pré-remplis depuis le profil utilisateur | L'utilisateur peut modifier les valeurs avant soumission | Aucun champ sensible comme le mot de passe n'est pré-rempli",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux accéder à mes 5 derniers éléments consultés afin de reprendre mon travail rapidement.",
        "La liste des récents est accessible depuis le menu principal | Elle contient les 5 derniers éléments uniques consultés | Un clic sur un élément l'ouvre directement",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir une page 404 personnalisée avec des suggestions de navigation afin de ne pas me retrouver bloqué.",
        "La page 404 affiche un message clair et un lien vers l'accueil | Elle propose 3 liens vers des sections populaires | Le code HTTP retourné est bien 404",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le focus se place automatiquement sur le premier champ du formulaire afin de commencer la saisie immédiatement.",
        "Le focus est positionné au chargement sur le premier champ vide | Le focus automatique ne perturbe pas les lecteurs d'écran | Le comportement ne s'active pas si l'URL contient une ancre",
        1, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un message de confirmation avant de quitter une page avec des modifications non sauvegardées afin d'éviter la perte de données.",
        "Un dialog de confirmation s'affiche si des modifications sont en cours | L'utilisateur peut choisir de rester ou de quitter | Le dialog ne s'affiche pas si le formulaire a été soumis avec succès",
        1, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=1  — Actions utilisateur légères (nouveaux)
# ─────────────────────────────────────────────────
MINOR_ACTIONS = [
    (
        "En tant qu'utilisateur, je veux marquer un article comme lu afin de distinguer les contenus déjà consultés.",
        "Un article marqué comme lu apparaît en grisé | Le statut lu est conservé entre sessions | L'utilisateur peut remettre un article en statut non lu",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux signaler un contenu inapproprié afin d'alerter les modérateurs.",
        "Le signalement soumet le contenu à la file de modération | L'utilisateur reçoit une confirmation du signalement | Un même utilisateur ne peut signaler le même contenu qu'une fois",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir le temps de lecture estimé d'un article afin de décider si je peux le lire maintenant.",
        "Le temps est calculé sur la base de 200 mots par minute | Il s'affiche sous le titre de l'article | Il est exprimé en minutes, arrondi à la minute supérieure",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux pouvoir surligner des passages dans un document afin de mettre en évidence les informations importantes.",
        "Le surlignage est disponible via un outil de sélection de texte | La couleur de surlignage est configurable | Les surlignages sont conservés entre sessions",
        2, 1
    ),
    (
        "En tant qu'utilisateur, je veux envoyer un pouce vers le haut sur un article afin d'exprimer mon appréciation.",
        "Un clic sur le bouton incrémente le compteur de likes | L'utilisateur ne peut liker qu'une fois par article | Il peut retirer son like en cliquant à nouveau",
        2, 1
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=2  — CRUD étendu, gestion de projets (nouveaux)
# ─────────────────────────────────────────────────
CRUD_EXTENDED = [
    (
        "En tant qu'utilisateur, je veux créer un projet afin d'organiser mes tâches et documents.",
        "Le projet a un nom (max 100 caractères), une description et une date de fin | Il peut être partagé avec plusieurs membres | La création notifie les membres invités",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux archiver un projet terminé afin de le conserver sans encombrer la vue principale.",
        "Le projet archivé disparaît de la liste active | Il reste accessible depuis la section Projets archivés | L'archivage est réversible par le propriétaire",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux définir une date d'échéance pour une tâche afin de respecter les délais.",
        "La date est sélectionnable via un calendrier | La tâche affiche un badge rouge si la date est dépassée | Un rappel est envoyé 24h avant l'échéance",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux assigner une tâche à un collègue afin de déléguer le travail.",
        "La liste des membres du projet est proposée pour l'assignation | L'assigné reçoit une notification par email | Une tâche ne peut être assignée qu'à un seul membre à la fois",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux créer une checklist dans une tâche afin de décomposer le travail en étapes.",
        "La checklist accepte jusqu'à 20 éléments | Chaque élément peut être coché indépendamment | Le pourcentage de complétion est affiché sur la fiche tâche",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux déplacer une tâche vers un autre projet afin de la réorganiser.",
        "Le déplacement conserve les commentaires et pièces jointes | Les deux projets sont notifiés du déplacement | La tâche est visible immédiatement dans le nouveau projet",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux cloner un projet existant afin de réutiliser sa structure.",
        "La copie inclut la structure des sections et tâches types mais pas les données | Le projet cloné est préfixé par Copie de | Les membres du projet original ne sont pas copiés",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux ajouter un label coloré à une tâche afin de la catégoriser visuellement.",
        "Les labels sont colorés et personnalisables par projet | Plusieurs labels peuvent être appliqués à une même tâche | Les labels sont filtrables dans la vue liste",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux configurer mon fuseau horaire afin que les dates et heures soient correctes.",
        "Le fuseau horaire est sélectionnable depuis les paramètres du profil | Toutes les dates affichées sont converties dans ce fuseau | Les événements planifiés respectent le fuseau horaire de l'organisateur",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux activer ou désactiver les notifications pour un projet spécifique afin de ne pas être submergé.",
        "Le paramètre est accessible depuis les paramètres du projet | La désactivation ne supprime pas les notifications dans le centre | Le paramètre est indépendant pour chaque projet",
        2, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer les champs personnalisés d'un formulaire afin d'adapter la collecte de données.",
        "Les types de champs disponibles sont texte, nombre, date et liste déroulante | Chaque champ peut être rendu obligatoire | Les champs s'affichent dans l'ordre de configuration",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux dupliquer une tâche afin de créer rapidement des tâches similaires.",
        "La copie inclut la description, les labels et la checklist | La copie est préfixée par Copie de | La copie est non assignée et sans date d'échéance par défaut",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux ajouter une estimation de temps à une tâche afin de planifier la charge de travail.",
        "L'estimation est saisie en heures et minutes | Le total des estimations est affiché par projet | L'estimation peut être révisée après création",
        2, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer les statuts disponibles pour les tâches afin d'adapter le workflow à l'équipe.",
        "Les statuts sont personnalisables en nom et couleur | L'ordre des statuts est configurable par glisser-déposer | Supprimer un statut nécessite de migrer les tâches concernées",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux configurer mes heures de travail afin que les rappels soient envoyés aux bonnes heures.",
        "Les heures de travail sont définies par jour de la semaine | Aucune notification n'est envoyée hors des heures configurées | Les paramètres sont modifiables à tout moment",
        2, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Collaboration légère, recherche avancée (nouveaux)
# ─────────────────────────────────────────────────
COLLABORATION_LIGHT = [
    (
        "En tant qu'utilisateur, je veux filtrer les tâches qui me sont assignées afin de voir uniquement mon travail.",
        "Un filtre Mes tâches est accessible en un clic | Le filtre agrège toutes les tâches de tous les projets actifs | Les tâches terminées peuvent être exclues par un second filtre",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir les tâches sur une vue Kanban afin de visualiser le flux de travail.",
        "Chaque statut correspond à une colonne Kanban | Les tâches sont déplaçables entre colonnes par glisser-déposer | Le changement de statut est sauvegardé instantanément",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir les tâches avec échéance sur un calendrier afin de planifier visuellement.",
        "Les tâches avec date d'échéance apparaissent sur le calendrier | La vue peut être mensuelle ou hebdomadaire | Cliquer une tâche ouvre sa fiche détail",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux filtrer les notifications par type afin de ne voir que les alertes pertinentes.",
        "Les types de notifications filtrables sont : mention, assignation, commentaire, échéance | Plusieurs types peuvent être sélectionnés simultanément | Le filtre est persistant pendant la session",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir les activités récentes d'un projet afin de me tenir informé des changements.",
        "Le journal d'activité affiche les 50 dernières actions | Chaque entrée indique l'utilisateur, l'action et la date | Le journal est en lecture seule",
        2, 3
    ),
    (
        "En tant qu'administrateur, je veux exporter les tâches d'un projet en CSV afin de les analyser dans un tableur.",
        "L'export contient : titre, statut, assigné, date d'échéance, priorité | Le fichier est encodé en UTF-8 | L'export est limité à 5000 tâches par fichier",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir un tableau de bord récapitulatif de mes tâches afin d'avoir une vue d'ensemble.",
        "Le tableau affiche les tâches en retard, dues aujourd'hui et dues cette semaine | Un graphique montre l'évolution des tâches terminées sur 30 jours | Les données sont mises à jour en temps réel",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir les projets auxquels je contribue regroupés par équipe afin d'avoir une vision organisée.",
        "Les projets sont regroupés par équipe dans la vue liste | Un projet appartient à une seule équipe | Les équipes sans projet actif sont masquées par défaut",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux rechercher dans l'historique des commentaires afin de retrouver une information passée.",
        "La recherche porte sur le contenu des commentaires | Les résultats affichent la tâche parente et la date du commentaire | La recherche est disponible depuis la barre de recherche globale",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir les membres actifs d'un projet et leur charge de travail afin de mieux répartir les tâches.",
        "La vue affiche chaque membre avec son nombre de tâches en cours | Les membres en surcharge (plus de 10 tâches) sont signalés en orange | La vue est accessible depuis le tableau de bord du projet",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=2  — Notifications avancées, reporting léger (nouveaux)
# ─────────────────────────────────────────────────
NOTIFICATION_EXTRA = [
    (
        "En tant qu'utilisateur, je veux choisir la fréquence de mes résumés email afin de contrôler le volume de courriels reçus.",
        "Les fréquences disponibles sont immédiate, quotidienne et hebdomadaire | Le paramètre est modifiable depuis les préférences | Le résumé regroupe toutes les notifications de la période",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux personnaliser le template des emails transactionnels afin qu'ils respectent la charte graphique.",
        "L'éditeur de template supporte HTML et variables dynamiques | Un aperçu est disponible avant sauvegarde | Le template est versionné pour permettre un retour en arrière",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir le nombre de notifications non lues dans le titre de l'onglet navigateur afin d'être alerté sans regarder l'application.",
        "Le titre affiche (N) NomApp où N est le nombre de notifications non lues | Le titre revient à la normale quand toutes les notifications sont lues | Le compteur se met à jour en temps réel",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux voir un rapport mensuel d'usage des fonctionnalités afin d'identifier celles qui sont peu utilisées.",
        "Le rapport liste les fonctionnalités triées par nombre d'utilisations | Il est disponible le 1er de chaque mois pour le mois précédent | Il est exportable en CSV",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux surveiller le temps de réponse de l'API afin de détecter les dégradations de performance.",
        "Un graphique affiche le percentile 50, 95 et 99 des temps de réponse | Une alerte est déclenchée si le p95 dépasse 2 secondes | Les données sont conservées 90 jours",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux activer un mode ne pas déranger pour une durée donnée afin de me concentrer sans interruption.",
        "La durée est configurable parmi 1h, 4h, 8h ou personnalisée | Les notifications reçues pendant ce mode sont conservées non lues | Un badge indique que le mode est actif",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer des rappels automatiques pour les tâches sans activité depuis 7 jours afin d'éviter les blocages.",
        "Le rappel est envoyé à l'assigné et au responsable du projet | Le rappel cesse si une activité est enregistrée sur la tâche | Le délai de 7 jours est configurable par projet",
        3, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un graphique d'activité sur mon profil afin de visualiser mes contributions au fil du temps.",
        "Le graphique couvre les 52 dernières semaines à l'image d'un heatmap | La densité de couleur correspond au nombre d'actions effectuées | Un clic sur une semaine filtre les activités de cette semaine",
        3, 2
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=3  — Chat, collaboration, mobile (nouveaux)
# ─────────────────────────────────────────────────
COLLAB_WORKFLOW_EXTRA = [
    (
        "En tant qu'utilisateur, je veux envoyer un message instantané à un collègue afin de communiquer sans email.",
        "Le message est livré en moins de 1 seconde | L'historique des messages est conservé 90 jours | Les messages peuvent contenir du texte et des emoji",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux créer un canal de discussion par projet afin de centraliser les échanges de l'équipe.",
        "Le canal est créé automatiquement à la création du projet | Les membres du projet rejoignent le canal automatiquement | L'historique est consultable par tous les membres",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux réagir à un message avec un emoji afin d'exprimer une réponse rapide.",
        "Les réactions sont visibles sous le message | Le nombre de réactions et les utilisateurs sont affichés au survol | Un utilisateur peut retirer sa propre réaction",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux épingler un message important dans un canal afin qu'il reste facilement accessible.",
        "Les messages épinglés sont accessibles via un bouton dédié dans le canal | Maximum 10 messages épinglés par canal | Seuls les membres avec le rôle Éditeur peuvent épingler",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux rechercher dans l'historique des messages d'un canal afin de retrouver une information.",
        "La recherche porte sur le contenu des messages | Les résultats affichent le contexte de 3 messages avant et après | La recherche s'effectue en moins de 500ms",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux utiliser l'application sur mobile avec une interface adaptée afin de travailler en déplacement.",
        "L'interface est responsive et fonctionne sur iOS et Android | Les gestes tactiles swipe et pinch sont supportés | Les fonctionnalités principales sont accessibles sans défilement horizontal",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux installer l'application comme PWA sur mon téléphone afin d'y accéder sans navigateur.",
        "L'invite d'installation s'affiche sur les navigateurs compatibles | L'application PWA fonctionne en mode hors ligne pour les données en cache | L'icône de l'application est présente sur l'écran d'accueil",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux collaborer en temps réel sur un document afin que plusieurs personnes puissent éditer simultanément.",
        "Les modifications de chaque utilisateur sont visibles en temps réel | Un curseur coloré identifie chaque co-éditeur | Les conflits d'édition sont résolus automatiquement",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir qui est en ligne dans mon équipe afin de savoir à qui je peux poser une question.",
        "Un indicateur vert ou gris s'affiche à côté de chaque membre | Le statut en ligne disparaît après 5 minutes d'inactivité | L'utilisateur peut manuellement se mettre en statut absent",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux créer un sondage dans un canal afin de recueillir les avis de l'équipe rapidement.",
        "Le sondage peut avoir jusqu'à 5 options | Chaque membre vote une seule fois | Les résultats s'affichent en temps réel en pourcentage",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir une vue Gantt de mon projet afin de visualiser les dépendances et le planning.",
        "Les tâches avec dates apparaissent sur la ligne de temps | Les dépendances sont représentées par des flèches | Le Gantt peut être exporté en image PNG",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux configurer des raccourcis clavier afin d'accélérer ma navigation dans l'application.",
        "La liste des raccourcis est accessible via la touche point d'interrogation | Les raccourcis couvrent nouvelle tâche, recherche et navigation entre sections | Les raccourcis sont personnalisables",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir les modifications d'un document sous forme de diff coloré afin de comprendre ce qui a changé.",
        "Les ajouts apparaissent en vert et les suppressions en rouge | Le diff est disponible pour chaque version sauvegardée | L'utilisateur peut restaurer une version précédente",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux configurer des automatisations de tâches afin de réduire le travail répétitif.",
        "L'interface propose des déclencheurs : changement de statut, nouvelle assignation | L'action associée peut être : notifier, changer le statut, créer une tâche liée | Les automatisations sont listées et désactivables",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux partager un document en mode lecture seule avec un lien externe afin de le présenter sans donner accès au compte.",
        "Le lien externe ne nécessite pas de connexion | Le mode lecture seule empêche toute modification | Le lien peut être révoqué à tout moment par le propriétaire",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir les statistiques de productivité de mon équipe afin de mesurer l'avancement.",
        "Les statistiques couvrent les 30 derniers jours | Elles sont affichées sous forme de graphique en barres | Elles sont filtrables par membre et par projet",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux intégrer des vidéoconférences depuis l'application afin de réunir l'équipe sans changer d'outil.",
        "Un lien de réunion est généré en un clic | L'intégration supporte Zoom et Google Meet | La réunion peut être attachée à une tâche ou un canal",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux définir des objectifs OKR pour mon équipe afin d'aligner le travail sur la stratégie.",
        "Les objectifs ont un titre, une description et une date de fin | Chaque objectif peut avoir plusieurs résultats clés mesurables | La progression est visible en pourcentage",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux recevoir un rapport de sprint automatique afin de partager l'avancement avec les parties prenantes.",
        "Le rapport est généré à la fin de chaque sprint | Il inclut les tâches complétées, en cours et bloquées | Il est envoyé par email aux membres du projet et aux observateurs",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux transférer un message à un autre canal afin de partager l'information avec la bonne équipe.",
        "Le transfert inclut le message original avec l'auteur et la date | L'utilisateur choisit le canal de destination | Un lien vers le message original est inclus dans le transfert",
        3, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=4  — Gestion documentaire, contenu critique (nouveaux)
# ─────────────────────────────────────────────────
DOCUMENT_MGMT = [
    (
        "En tant qu'utilisateur, je veux versionner un document afin de conserver l'historique complet des modifications.",
        "Chaque sauvegarde crée une nouvelle version numérotée | Une version peut être restaurée en deux clics | Les 50 dernières versions sont conservées automatiquement",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux définir des droits d'accès sur un document (lecture, commentaire, édition) afin de contrôler qui peut le modifier.",
        "Les droits sont configurables par utilisateur ou par groupe | Le propriétaire garde toujours les droits complets | Les droits peuvent être hérités du projet parent",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux signer électroniquement un document afin d'officialiser son acceptation.",
        "La signature est horodatée et liée à l'identité de l'utilisateur connecté | Le document signé est verrouillé contre les modifications | Un certificat de signature est disponible en téléchargement",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer la durée de rétention des documents afin de respecter les obligations légales.",
        "La durée est configurable par catégorie de document | Les documents expirés sont archivés automatiquement | Un avertissement est envoyé 30 jours avant l'expiration",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux voir qui a consulté un document confidentiel afin d'auditer les accès.",
        "Chaque accès est enregistré avec l'identité et la date | Le journal est consultable par le propriétaire et l'administrateur | Les accès sont filtrables par période",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux convertir un document Word en PDF afin de le partager dans un format universel.",
        "La conversion est disponible depuis le menu du document | Le PDF généré est fidèle à la mise en page originale | La conversion s'effectue en moins de 10 secondes pour les fichiers de moins de 5 Mo",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux organiser les documents dans une arborescence de dossiers afin de faciliter la navigation.",
        "L'arborescence supporte jusqu'à 5 niveaux de profondeur | Un document ne peut appartenir qu'à un seul dossier | Un dossier peut être partagé indépendamment de son contenu",
        3, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=2  — Validation avancée, formulaires complexes (nouveaux)
# ─────────────────────────────────────────────────
VALIDATION_EXTRA = [
    (
        "En tant qu'utilisateur, je veux que le numéro de TVA intracommunautaire soit validé en temps réel afin d'éviter les erreurs de facturation.",
        "La validation utilise le service VIES de la Commission européenne | Le résultat est mis en cache 24h pour éviter les appels répétés | Un message d'erreur précise si le numéro est invalide ou non trouvé",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que les numéros de téléphone soient normalisés au format international afin de gérer plusieurs pays.",
        "La normalisation utilise la bibliothèque libphonenumber | Le format international est stocké (exemple: +33 6 12 34 56 78) | Le champ propose un sélecteur de code pays",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le formulaire multi-étapes sauvegarde automatiquement ma progression afin de reprendre sans tout ressaisir.",
        "La progression est sauvegardée à chaque étape validée | La sauvegarde est associée à la session utilisateur | Les données sont supprimées après soumission réussie ou après 72h",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux uploader plusieurs fichiers simultanément afin de gagner du temps.",
        "L'upload multi-fichiers supporte jusqu'à 10 fichiers à la fois | La progression totale et par fichier est affichée | Les fichiers en erreur sont signalés sans bloquer les autres",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le champ IBAN soit validé en temps réel afin d'éviter les erreurs de virement.",
        "La validation utilise l'algorithme ISO 7064 MOD-97-10 | Le BIC est déduit automatiquement depuis l'IBAN si possible | Un message d'erreur précise si l'IBAN est invalide",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux capturer une signature manuscrite électronique dans un formulaire afin de valider une demande.",
        "La signature est capturée via un canvas tactile ou souris | Elle est sauvegardée en SVG avec horodatage | Le formulaire ne peut être soumis sans signature",
        4, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer des règles de validation conditionnelles afin d'adapter les champs selon les réponses.",
        "Un champ peut être affiché ou masqué selon la valeur d'un autre champ | La logique conditionnelle supporte les opérateurs ET et OU | Les règles sont configurables sans écrire de code",
        4, 2
    ),
    (
        "En tant qu'utilisateur, je veux que la taille et le type réel des fichiers uploadés soient vérifiés côté serveur afin d'empêcher les contournements.",
        "La vérification côté serveur est indépendante de la validation côté client | Les fichiers non conformes sont rejetés avec un message d'erreur explicite | La vérification se produit avant tout traitement du fichier",
        4, 2
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=3  — API avancée, performance, cache (nouveaux)
# ─────────────────────────────────────────────────
API_PERFORMANCE = [
    (
        "En tant qu'utilisateur, je veux que les pages se chargent en moins de 2 secondes afin d'avoir une expérience fluide.",
        "Le LCP est inférieur à 2.5 secondes mesuré sur un réseau 4G | Les ressources statiques sont mises en cache côté navigateur | Les images sont chargées en lazy loading",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux mettre en cache les résultats des requêtes coûteuses afin de réduire la charge serveur.",
        "Le cache est invalidé automatiquement lors de la modification des données | La durée du cache est configurable par type de requête | Un hit de cache est signalé dans le header HTTP X-Cache-Hit",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer une pagination côté serveur pour les grandes listes afin d'éviter les timeouts.",
        "Chaque réponse API inclut le token de page suivante | La taille de page par défaut est 50 et le maximum est 200 | L'endpoint retourne le nombre total de résultats",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux mettre en place une file d'attente pour les traitements longs afin de ne pas bloquer l'interface.",
        "Les jobs sont créés et traités de manière asynchrone | L'utilisateur reçoit une notification à la fin du traitement | L'état du job (en attente, en cours, terminé, échec) est consultable",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux versionner l'API afin de garantir la compatibilité des clients lors des mises à jour.",
        "Le versioning utilise le préfixe /api/v1 et /api/v2 | Les versions antérieures sont supportées 12 mois après la sortie d'une nouvelle version | Un header Deprecation est ajouté sur les endpoints obsolètes",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux générer automatiquement la documentation de l'API afin que les partenaires puissent l'intégrer.",
        "La documentation est générée depuis les annotations du code en OpenAPI 3.0 | Elle est accessible via /api/docs | La documentation est mise à jour automatiquement à chaque déploiement",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux implémenter un retry avec backoff exponentiel pour les appels API externes afin de gérer les pannes temporaires.",
        "3 tentatives maximum avec délai de 1s, 2s puis 4s | Les erreurs HTTP 4xx ne déclenchent pas de retry | Les erreurs après 3 tentatives sont journalisées et déclenchent une alerte",
        4, 3
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=4  — Abonnements, facturation complexe (nouveaux)
# ─────────────────────────────────────────────────
SUBSCRIPTION = [
    (
        "En tant que client, je veux changer de plan d'abonnement afin d'accéder à plus de fonctionnalités.",
        "La mise à niveau est effective immédiatement avec facturation au prorata | Le downgrade prend effet à la prochaine date de renouvellement | Un email confirme le changement de plan",
        4, 4
    ),
    (
        "En tant que client, je veux voir l'historique de mes factures afin de les récupérer pour ma comptabilité.",
        "Les factures sont listées avec date, montant et statut payé ou en attente | Chaque facture est téléchargeable en PDF | Les factures sont disponibles pendant 5 ans après émission",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer une période d'essai gratuite afin d'acquérir de nouveaux clients.",
        "La période d'essai est configurable de 7 à 30 jours | Aucune carte bancaire n'est requise pour démarrer l'essai | Un email est envoyé 3 jours avant la fin de l'essai",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer les remises commerciales par client afin de pratiquer des tarifs négociés.",
        "Une remise en pourcentage est applicable par client | La remise est visible sur la facture | La remise est tracée dans le journal d'audit commercial",
        4, 4
    ),
    (
        "En tant que client, je veux mettre à jour ma carte bancaire de facturation afin de continuer mon abonnement sans interruption.",
        "La mise à jour se fait via un formulaire sécurisé conforme PCI-DSS | L'ancienne carte est remplacée immédiatement | Une confirmation est envoyée par email",
        4, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=5  — Conformité RGPD avancée, données sensibles (nouveaux)
# ─────────────────────────────────────────────────
PRIVACY_COMPLIANCE = [
    (
        "En tant qu'administrateur, je veux gérer les consentements RGPD de chaque utilisateur afin de prouver la conformité.",
        "Un registre des consentements est maintenu par utilisateur | Chaque consentement indique la version des CGU et la date d'acceptation | Le registre est exportable pour audit externe",
        4, 5
    ),
    (
        "En tant qu'utilisateur, je veux voir et modifier mes préférences de cookies afin de contrôler le traitement de mes données.",
        "La bannière cookies s'affiche à la première visite | Chaque catégorie (analytique, marketing, fonctionnel) est activable indépendamment | Les préférences sont conservées 13 mois conformément aux recommandations CNIL",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux masquer les données PII dans les logs afin d'éviter l'exposition accidentelle d'informations sensibles.",
        "Les champs email, téléphone et numéro de carte sont masqués dans les logs | Le masquage utilise des remplacements comme ****@****.** | Les logs bruts ne sont jamais accessibles aux développeurs",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux mettre en place une procédure de notification en cas de violation de données afin de respecter l'article 33 du RGPD.",
        "La procédure de notification est documentée et testée annuellement | La notification à l'autorité de contrôle est préparée dans les 72h suivant la détection | Les utilisateurs affectés sont notifiés par email",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux documenter les analyses d'impact sur la protection des données afin de valider les nouveaux traitements.",
        "L'AIPD est documentée dans un formulaire structuré accessible en ligne | Elle couvre la finalité, les données traitées, les risques et les mesures | Le DPO est notifié et peut approuver en ligne",
        4, 5
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=3  — Sécurité critique, monitoring (nouveaux)
# ─────────────────────────────────────────────────
SECURITY_CRITICAL = [
    (
        "En tant qu'administrateur, je veux mettre en place des headers HTTP de sécurité afin de protéger contre les attaques web courantes.",
        "Les headers configurés sont CSP, HSTS, X-Frame-Options et X-Content-Type-Options | La politique CSP bloque les ressources non autorisées | Un audit automatique vérifie la présence des headers à chaque déploiement",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux mettre en place un monitoring de sécurité en temps réel afin de détecter les intrusions.",
        "Le monitoring alerte en moins de 5 minutes sur les comportements anormaux | Les événements surveillés sont la force brute, le scan et l'injection | Les alertes sont envoyées par email et Slack",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux chiffrer les sauvegardes de la base de données afin de protéger les données en cas de vol de support.",
        "Le chiffrement est AES-256 avec une clé séparée des données | Les sauvegardes sont stockées dans un emplacement géographiquement distinct de la production | La procédure de restauration est testée mensuellement",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer les secrets d'application dans un vault sécurisé afin d'éliminer les secrets en dur dans le code.",
        "Les secrets sont stockés dans HashiCorp Vault ou AWS Secrets Manager | La rotation des secrets est automatique selon un calendrier configurable | L'accès aux secrets est journalisé par service et par utilisateur",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux effectuer des tests de pénétration réguliers afin d'identifier les vulnérabilités avant les attaquants.",
        "Les tests sont planifiés trimestriellement par un prestataire externe | Un rapport est produit avec les vulnérabilités classées par criticité CVSS | Les vulnérabilités critiques sont corrigées sous 72h",
        5, 4
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=4  — Paiement avancé, compliance bancaire (nouveaux)
# ─────────────────────────────────────────────────
PAYMENT_ADVANCED = [
    (
        "En tant que client, je veux payer via virement SEPA instantané afin de finaliser mon achat immédiatement.",
        "Le virement est confirmé en moins de 10 secondes | La commande est validée dès réception de la confirmation bancaire | En cas d'échec, le client est redirigé vers une méthode de paiement alternative",
        5, 4
    ),
    (
        "En tant que client, je veux recevoir une alerte si ma carte bancaire est sur le point d'expirer afin de la mettre à jour avant renouvellement.",
        "L'alerte est envoyée 30 jours avant l'expiration | Un lien direct vers la page de mise à jour de la carte est inclus | L'alerte est envoyée par email et notification push",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer les remboursements automatiques suite à une annulation afin de réduire les délais de traitement.",
        "Le remboursement automatique est déclenché dans les 24h suivant l'annulation | Le montant remboursé est calculé selon la politique d'annulation configurée | Un email de confirmation est envoyé au client",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux intégrer un module de calcul de taxes automatique afin de gérer les différentes juridictions fiscales.",
        "Le module calcule la TVA selon le pays du client et la nature du produit | Les taux de TVA sont mis à jour automatiquement depuis une source officielle | La facture détaille les taxes par juridiction",
        5, 4
    ),
    (
        "En tant que client, je veux utiliser mon portefeuille virtuel pour payer afin d'utiliser mes crédits accumulés.",
        "Le solde du wallet est affiché avant le paiement | Le wallet peut être utilisé en combinaison avec une autre méthode de paiement | Chaque transaction wallet est journalisée avec montant et date",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux générer les déclarations fiscales périodiques afin de respecter les obligations comptables.",
        "Les déclarations sont générées au format requis par l'administration fiscale | Elles couvrent la TVA collectée et la TVA déductible | Elles sont archivées pendant 10 ans",
        5, 4
    ),
    (
        "En tant que client, je veux fractionner une facture entre plusieurs payeurs afin de partager les frais.",
        "La facture peut être divisée en parts égales ou personnalisées | Chaque payeur reçoit un lien de paiement individuel | La commande est confirmée quand tous les paiements sont reçus",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux voir le taux de conversion de la page de paiement afin d'identifier les abandons de panier.",
        "L'entonnoir de conversion affiche chaque étape du processus de checkout | Les points d'abandon sont identifiés avec le taux et le montant moyen abandonné | Les données sont disponibles par période jour, semaine et mois",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer des règles de cashback afin d'offrir des remises sur les achats futurs.",
        "Le cashback est crédité dans le wallet après la période de rétractation de 14 jours | Le taux de cashback est configurable par catégorie de produit | Le cashback est non transférable et expire après 12 mois",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer des prix dynamiques afin d'ajuster les tarifs selon la demande et le profil client.",
        "Les règles portent sur l'heure, la date, l'inventaire disponible et le profil client | Le prix affiché est recalculé en temps réel avant validation | L'historique des prix appliqués est conservé pour audit",
        5, 4
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=5  — Conformité réglementaire critique (nouveaux)
# ─────────────────────────────────────────────────
CRITICAL_COMPLIANCE = [
    (
        "En tant qu'administrateur, je veux mettre en place un plan de continuité d'activité documenté afin d'assurer le service en cas de sinistre.",
        "Le plan documente les procédures pour les 5 scénarios de sinistre les plus probables | Les procédures sont testées semestriellement avec rapport | Le personnel clé est formé et connaît son rôle",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux préparer l'organisation à une certification ISO 27001 afin de prouver notre maturité en sécurité de l'information.",
        "Toutes les politiques de sécurité sont documentées et approuvées par la direction | Les contrôles sont audités annuellement par un organisme tiers accrédité | Les non-conformités majeures sont corrigées sous 30 jours",
        5, 5
    ),
]

# ─────────────────────────────────────────────────
# P=1 / I=1  — Aide, FAQ, documentation statique (nouveaux)
# ─────────────────────────────────────────────────
HELP_SUPPORT = [
    (
        "En tant qu'utilisateur, je veux accéder à une page FAQ afin de trouver des réponses sans contacter le support.",
        "La FAQ est organisée par catégorie | La recherche plein texte filtre les questions en temps réel | Chaque réponse est réductible pour ne pas encombrer la page",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir un guide de démarrage rapide afin de comprendre les fonctions essentielles.",
        "Le guide est accessible depuis le menu d'aide | Il comporte moins de 10 étapes illustrées | Il peut être rouvert à tout moment depuis les paramètres",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux consulter la page de statut des services afin de savoir si une panne est en cours.",
        "La page affiche le statut temps réel de chaque service clé | Les incidents passés sont listés avec leur durée | La page est accessible sans être connecté",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux voir un lien d'aide contextuel sur chaque page d'erreur afin de comprendre comment la résoudre.",
        "Le lien pointe vers un article d'aide pertinent selon le code d'erreur | L'article s'ouvre dans un panneau latéral sans quitter la page | Un bouton 'Contacter le support' est disponible si l'article ne répond pas",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux consulter la liste des raccourcis clavier afin d'accélérer mon travail.",
        "La liste est accessible via Ctrl+? ou depuis le menu Aide | Les raccourcis sont groupés par contexte (liste, formulaire, global) | La liste est imprimable en PDF",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux regarder des tutoriels vidéo intégrés afin d'apprendre les fonctionnalités avancées.",
        "Les vidéos sont accessibles depuis le menu Aide sans quitter l'application | Chaque vidéo dure moins de 3 minutes | La progression de visionnage est mémorisée",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux lancer une visite guidée interactive afin de découvrir les nouvelles fonctionnalités.",
        "La visite guidée se déclenche automatiquement à la première connexion | L'utilisateur peut l'interrompre à tout moment | Elle peut être relancée depuis le menu Aide",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux accéder à un glossaire des termes métier afin de comprendre le vocabulaire de l'application.",
        "Le glossaire est consultable par lettre et par recherche | Chaque terme affiche une définition courte et un exemple | Les termes sont liés aux sections de documentation correspondantes",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux pouvoir noter l'utilité d'un article d'aide afin d'améliorer la documentation.",
        "Un pouce haut ou pouce bas est disponible sous chaque article | Le vote est anonyme et ne nécessite pas de connexion | Un commentaire optionnel peut accompagner le vote négatif",
        1, 1
    ),
    (
        "En tant qu'utilisateur, je veux consulter les notes de version afin de savoir ce qui a changé lors d'une mise à jour.",
        "Les notes sont accessibles depuis le menu Aide | Elles sont organisées par version avec date | Les changements importants sont mis en évidence avec une icône",
        1, 1
    ),
]

# ─────────────────────────────────────────────────
# P=1 / I=2  — Onboarding utilisateur (nouveaux)
# ─────────────────────────────────────────────────
USER_ONBOARDING = [
    (
        "En tant que nouvel utilisateur, je veux recevoir un email de bienvenue avec les premières étapes afin de démarrer rapidement.",
        "L'email est envoyé dans les 5 minutes après la création du compte | Il contient un lien direct vers le guide de démarrage | Le contenu est personnalisé selon le rôle sélectionné",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux voir un assistant de configuration de compte afin de personnaliser l'application dès le départ.",
        "L'assistant se lance à la première connexion | Il comporte 4 étapes maximum | Les paramètres configurés sont appliqués immédiatement",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux avoir une checklist de démarrage afin de savoir quelles actions effectuer en premier.",
        "La checklist affiche les tâches avec leur statut complété ou à faire | Elle disparaît automatiquement quand toutes les tâches sont complétées | Elle est accessible depuis le tableau de bord",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux que des données d'exemple soient créées automatiquement afin de comprendre l'application sans saisir moi-même.",
        "Les données d'exemple couvrent tous les objets principaux de l'application | Un bandeau indique clairement qu'il s'agit de données fictives | Elles sont supprimables en un clic depuis les paramètres",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux accéder à une bibliothèque de modèles prêts à l'emploi afin de gagner du temps.",
        "La bibliothèque contient au moins 10 modèles par catégorie | Chaque modèle est prévisualisable avant import | L'import remplit automatiquement les champs standards",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux voir mes jalons d'onboarding afin de savoir à quelle étape j'en suis.",
        "Un indicateur de progression est visible dans le menu latéral pendant les 30 premiers jours | Chaque jalon complété affiche une confirmation visuelle | Le dernier jalon complété déclenche un message de félicitations",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux recevoir des conseils personnalisés basés sur mon comportement afin d'utiliser les fonctions les plus utiles.",
        "Les conseils apparaissent dans une section dédiée du tableau de bord | Ils sont basés sur les actions que l'utilisateur n'a pas encore effectuées | L'utilisateur peut masquer les conseils individuellement",
        1, 2
    ),
    (
        "En tant que responsable, je veux pouvoir inviter plusieurs membres de l'équipe à la fois afin d'accélérer l'intégration.",
        "L'invitation peut se faire par liste d'emails séparés par virgule ou virgule | Un rôle par défaut peut être assigné à tous les invités | Un rapport indique les invitations envoyées et les acceptations",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux accéder à un guide PDF téléchargeable afin de consulter la documentation hors ligne.",
        "Le PDF est généré depuis la documentation en ligne | Il est disponible dans la langue de l'utilisateur | Il est téléchargeable depuis le centre d'aide",
        1, 2
    ),
    (
        "En tant que nouvel utilisateur, je veux pouvoir sauter l'onboarding afin de commencer directement à utiliser l'application.",
        "Un bouton 'Passer' est visible à chaque étape de l'onboarding | Sauter l'onboarding ne supprime pas les données d'exemple | L'onboarding peut être relancé depuis les paramètres",
        1, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=2  — Paramètres utilisateur (nouveaux)
# ─────────────────────────────────────────────────
USER_SETTINGS = [
    (
        "En tant qu'utilisateur, je veux mettre à jour ma photo de profil afin que mes collègues me reconnaissent.",
        "Le recadrage de photo est disponible avant upload | Les formats JPG et PNG jusqu'à 5 Mo sont acceptés | La photo est affichée dans les commentaires et les assignations",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux modifier mon nom d'affichage afin qu'il corresponde à mon usage professionnel.",
        "Le nom d'affichage est distinct de l'identifiant de connexion | Le changement se répercute sur tous les commentaires existants | Le nom doit comporter entre 2 et 50 caractères",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux choisir la langue de l'interface afin de travailler dans ma langue native.",
        "Les langues disponibles incluent au moins le français, l'anglais et l'espagnol | Le changement s'applique immédiatement sans rechargement | La préférence est sauvegardée par compte",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux définir mon fuseau horaire afin que les dates et heures s'affichent correctement.",
        "Le fuseau horaire est sélectionnable dans une liste | Toutes les dates affichées sont converties dans le fuseau choisi | Le fuseau par défaut est détecté automatiquement depuis le navigateur",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux activer le mode sombre afin de réduire la fatigue visuelle.",
        "Le mode sombre est activable depuis les paramètres ou via un bouton dans l'en-tête | Le choix est mémorisé entre les sessions | Le contraste respecte les normes WCAG AA",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux gérer mes préférences de notifications afin de ne recevoir que les alertes pertinentes.",
        "Chaque type de notification peut être activé ou désactivé indépendamment | Les canaux disponibles sont email et push | Les préférences sont sauvegardées immédiatement",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux définir une vue par défaut pour les listes afin de retrouver ma configuration préférée.",
        "Les options sont liste, kanban et tableau | La vue par défaut est chargée automatiquement à chaque visite | L'utilisateur peut passer à une autre vue sans perdre le défaut",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux exporter mes données personnelles afin de les conserver ou les transférer.",
        "L'export contient toutes les données associées au compte au format JSON ou CSV | L'export est disponible en moins de 24h après la demande | Un email notifie quand l'export est prêt",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux configurer mes filtres de liste par défaut afin de retrouver mes éléments rapidement.",
        "Les filtres par défaut sont applicables par type d'objet | Ils sont chargés automatiquement à l'ouverture de la liste | Un bouton 'Réinitialiser' restaure les filtres d'origine",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux configurer l'intervalle de sauvegarde automatique afin de ne pas perdre mon travail.",
        "L'intervalle est configurable de 30 secondes à 10 minutes | La dernière sauvegarde automatique est affichée dans la barre d'état | Une notification signale si la sauvegarde automatique échoue",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux gérer les applications tierces connectées à mon compte afin de contrôler les accès.",
        "La liste des apps connectées affiche la date de connexion et les permissions | La déconnexion révoque immédiatement les tokens d'accès | Une notification est envoyée lors d'une nouvelle connexion d'app",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux masquer ou afficher la barre latérale afin d'adapter l'espace de travail.",
        "La barre est masquable via un bouton toggle visible | L'état ouvert ou fermé est mémorisé entre les sessions | Masquer la barre n'affecte pas les fonctionnalités accessibles",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux configurer la densité d'affichage des listes afin d'adapter la quantité d'informations visibles.",
        "Trois densités sont disponibles : compacte, normale, confortable | Le changement s'applique immédiatement | La préférence est conservée entre les sessions",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux épingler mes sections favorites dans le menu afin d'y accéder rapidement.",
        "Jusqu'à 5 sections peuvent être épinglées | L'ordre des épingles est modifiable par glisser-déposer | Les épingles sont personnelles et ne sont pas partagées",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux définir le nombre d'éléments affichés par page dans les listes afin d'adapter la navigation.",
        "Les options disponibles sont 10, 25, 50 et 100 éléments | La préférence est mémorisée par type de liste | Le passage à une autre page respecte le nombre configuré",
        2, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=2  — Tableau de bord et widgets (nouveaux)
# ─────────────────────────────────────────────────
DASHBOARD_WIDGETS = [
    (
        "En tant qu'utilisateur, je veux voir un résumé des activités récentes sur mon tableau de bord afin d'avoir une vue d'ensemble.",
        "Le widget affiche les 10 dernières activités de l'équipe | Chaque activité est horodatée et cliquable | Le widget se met à jour automatiquement toutes les 5 minutes",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux personnaliser la disposition des widgets de mon tableau de bord afin d'afficher les informations qui me sont utiles.",
        "Les widgets sont déplaçables par glisser-déposer | La disposition est sauvegardée automatiquement | Une option restaure la disposition par défaut",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux ajouter ou supprimer des widgets sur mon tableau de bord afin de le personnaliser.",
        "Un catalogue de widgets disponibles est accessible | Chaque widget peut être ajouté en un clic | Les widgets supprimés peuvent être réajoutés depuis le catalogue",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux filtrer les données du tableau de bord par période afin d'analyser une fenêtre temporelle précise.",
        "Les filtres disponibles sont aujourd'hui, cette semaine, ce mois et personnalisé | Le filtre s'applique à tous les widgets en même temps | La période sélectionnée est conservée lors du rechargement",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux exporter mon tableau de bord en PDF afin de le partager lors d'une réunion.",
        "L'export PDF conserve la disposition et les couleurs | Il inclut la date de génération en pied de page | L'export est disponible depuis un bouton dans l'en-tête du tableau de bord",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux comparer les métriques de deux périodes sur le tableau de bord afin de mesurer l'évolution.",
        "La comparaison est activable via un toggle | Les variations sont affichées en pourcentage avec une flèche directionnelle | Les deux périodes sont sélectionnables indépendamment",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir l'indicateur de progression vers mes objectifs sur le tableau de bord afin de suivre mon avancement.",
        "L'indicateur affiche la valeur actuelle, l'objectif et le pourcentage atteint | Il change de couleur selon le taux d'atteinte (rouge, orange, vert) | Les objectifs sont modifiables depuis les paramètres",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux avoir un widget de recherche rapide sur le tableau de bord afin d'accéder directement à un élément.",
        "La recherche s'effectue sur tous les types d'objets de l'application | Les résultats apparaissent en moins de 300 ms | Les 5 dernières recherches sont mémorisées",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un widget de statut de l'équipe sur le tableau de bord afin de savoir qui est disponible.",
        "Le widget affiche la liste des membres avec leur statut en ligne ou absent | Le statut est mis à jour en temps réel | Le responsable peut voir le statut de toute son équipe",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un graphique de tendance hebdomadaire sur le tableau de bord afin de visualiser les variations.",
        "Le graphique affiche 8 semaines de données par défaut | Il est interactif avec des tooltips au survol | La granularité peut être changée en jour, semaine ou mois",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux épingler des éléments importants sur le tableau de bord afin d'y accéder rapidement.",
        "Tout objet de l'application peut être épinglé | Les épingles sont affichées dans un widget dédié | L'ordre des épingles est modifiable par glisser-déposer",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux voir un récapitulatif des tâches en retard sur le tableau de bord afin d'agir en priorité.",
        "Le widget liste les tâches dépassant leur échéance | Chaque tâche affiche le nombre de jours de retard | Un clic sur une tâche ouvre directement sa fiche de détail",
        2, 2
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Fonctionnalités mobile (nouveaux)
# ─────────────────────────────────────────────────
MOBILE_APP = [
    (
        "En tant qu'utilisateur mobile, je veux naviguer avec des gestes de balayage afin d'accéder rapidement aux sections suivantes et précédentes.",
        "Le glissement horizontal vers la gauche ouvre l'élément suivant | Vers la droite revient à l'élément précédent | Les zones de glissement ne déclenchent pas d'actions accidentelles sur les listes",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux recevoir des notifications push afin d'être alerté des événements importants même sans avoir l'app ouverte.",
        "La permission de notification est demandée à la première connexion | Les types de notifications sont configurables dans les paramètres | Un tap sur la notification ouvre directement l'élément concerné",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux utiliser des formulaires adaptés au toucher afin de saisir des données sans erreur sur petit écran.",
        "Les champs ont une hauteur minimale de 44px | Le clavier numérique s'affiche automatiquement pour les champs de nombre | Les menus déroulants utilisent le sélecteur natif de la plateforme",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux scanner un QR code afin d'ouvrir rapidement un élément sans le rechercher.",
        "Le scanner s'ouvre directement depuis la barre de navigation | Il supporte les QR codes générés par l'application et les codes standards | Un retour haptique confirme la reconnaissance du code",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux prendre une photo depuis l'application afin de l'attacher directement à un enregistrement.",
        "L'accès à la caméra est demandé uniquement à la première utilisation | La photo est compressée automatiquement si elle dépasse 5 Mo | Un aperçu est affiché avant confirmation de l'upload",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux naviguer avec une barre de navigation en bas de l'écran afin d'accéder aux sections principales d'un seul pouce.",
        "La barre contient au maximum 5 icônes | L'icône active est mise en évidence | La barre reste visible en scrollant",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux me connecter avec mon empreinte digitale ou la reconnaissance faciale afin d'éviter de ressaisir mon mot de passe.",
        "L'authentification biométrique est proposée après la première connexion par mot de passe | Elle utilise les APIs biométriques natives de l'OS (WebAuthn) | Elle peut être désactivée depuis les paramètres de sécurité | Le fallback vers le mot de passe reste toujours disponible",
        4, 4
    ),
    (
        "En tant qu'utilisateur mobile, je veux que les tableaux s'adaptent à l'écran afin de consulter toutes les colonnes sans scroll horizontal excessif.",
        "Les colonnes moins importantes sont masquées sur mobile par défaut | L'utilisateur peut choisir les colonnes visibles | Un mode plein écran est disponible pour les tableaux larges",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux voir le badge de notifications sur l'icône de l'application afin de savoir combien d'alertes m'attendent.",
        "Le badge indique le nombre de notifications non lues | Il se met à jour en temps réel | Le badge disparaît quand toutes les notifications sont lues",
        2, 3
    ),
    (
        "En tant qu'utilisateur mobile, je veux accéder aux données récentes en mode hors ligne afin de consulter des informations sans connexion.",
        "Les 50 derniers éléments consultés sont mis en cache localement | Un indicateur signale clairement le mode hors ligne | Les actions non synchronisées sont envoyées dès le retour de la connexion",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=2 / I=3  — Collaboration sociale (nouveaux)
# ─────────────────────────────────────────────────
SOCIAL_COLLABORATION = [
    (
        "En tant qu'utilisateur, je veux commenter un enregistrement afin de partager mes observations avec l'équipe.",
        "Les commentaires supportent le texte riche et les mentions | L'auteur est notifié des réponses à ses commentaires | Les commentaires peuvent être modifiés dans les 15 minutes suivant leur publication",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux réagir à un commentaire avec un emoji afin d'exprimer mon opinion rapidement.",
        "6 réactions de base sont disponibles (pouce, cœur, applaudissements, surprise, tristesse, rire) | Le nombre de réactions par type est affiché | L'utilisateur peut retirer sa réaction en cliquant à nouveau",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux mentionner un collègue dans un commentaire afin de l'alerter directement.",
        "La mention se déclenche en tapant @ suivi du début du nom | L'utilisateur mentionné reçoit une notification | La mention est cliquable et ouvre le profil",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux suivre un collègue afin de voir ses activités dans mon fil d'actualité.",
        "Le suivi est activé en un clic depuis le profil | Le fil d'actualité affiche les actions du suivi dans l'ordre chronologique | L'utilisateur peut se désabonner à tout moment",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux étiqueter des enregistrements avec des labels afin de les regrouper par thème.",
        "Les labels sont créables librement ou depuis une liste prédéfinie | Plusieurs labels peuvent être appliqués à un même enregistrement | La recherche peut filtrer par label",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux sauvegarder en favoris des éléments afin de les retrouver rapidement.",
        "Un élément peut être mis en favori d'un simple clic sur une étoile | La liste des favoris est accessible depuis le menu principal | Les favoris sont personnels et non visibles par les autres",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux envoyer un message direct à un collègue afin de communiquer sans sortir de l'application.",
        "La messagerie directe est accessible depuis n'importe quelle page | Les messages sont chiffrés en transit | Un compteur de messages non lus est affiché dans la barre de navigation",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir le fil d'actualité de l'équipe afin de rester informé des actions récentes.",
        "Le fil affiche les créations, modifications et commentaires des membres de l'équipe | Il est filtrable par type d'action et par membre | Les événements antérieurs à 30 jours sont archivés",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux partager un lien vers un enregistrement afin de le communiquer à un collègue.",
        "Chaque enregistrement a un lien direct copiable en un clic | Le lien respecte les permissions (inaccessible sans les droits) | Un message indique si le destinataire n'a pas les droits",
        2, 3
    ),
    (
        "En tant qu'utilisateur, je veux voir le profil public d'un collègue afin de connaître son rôle et ses compétences.",
        "Le profil affiche le nom, le rôle, le département et la photo | Les projets auxquels il contribue sont listés | Un bouton permet d'envoyer un message direct",
        2, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=2  — Email marketing et campagnes (nouveaux)
# ─────────────────────────────────────────────────
EMAIL_CAMPAIGNS = [
    (
        "En tant qu'administrateur, je veux créer des modèles d'email réutilisables afin d'assurer la cohérence des communications.",
        "L'éditeur supporte le glisser-déposer de blocs | Les variables de personnalisation sont insérables depuis un menu | L'aperçu est disponible en version desktop et mobile",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux planifier l'envoi d'une campagne email afin de cibler le bon moment d'envoi.",
        "La planification accepte une date et heure précises | Le fuseau horaire du destinataire peut être respecté | La campagne peut être annulée jusqu'à 30 minutes avant l'envoi prévu",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux tester deux variantes de sujet afin d'optimiser le taux d'ouverture.",
        "La division du groupe de test est configurable de 10% à 50% | La variante gagnante est envoyée automatiquement au reste après 4 heures | Les résultats des deux variantes sont comparés dans un rapport",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux gérer les désabonnements afin de respecter la réglementation anti-spam.",
        "Un lien de désabonnement est obligatoirement présent dans chaque email | Le désabonnement est effectif en moins d'une heure | Les désabonnés sont exclus de toutes les campagnes futures",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux consulter les statistiques de campagne afin de mesurer son efficacité.",
        "Les métriques disponibles sont le taux d'ouverture, de clic, de rebond et de désabonnement | Les statistiques sont disponibles en temps réel | Un graphique montre l'évolution des ouvertures dans le temps",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux segmenter la liste de contacts afin d'envoyer des emails ciblés.",
        "La segmentation supporte des critères combinés comme le pays, le plan et la date d'inscription | La taille du segment est calculée avant l'envoi | Les segments peuvent être sauvegardés et réutilisés",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux personnaliser le contenu email selon le profil du destinataire afin d'améliorer l'engagement.",
        "Les variables de personnalisation couvrent au moins le prénom, l'entreprise et le plan | Un contenu par défaut est affiché si la variable est vide | La prévisualisation montre le rendu pour un contact réel",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux gérer les rebonds email afin de maintenir une liste propre.",
        "Les rebonds durs désactivent automatiquement l'adresse | Les rebonds mous sont réessayés 3 fois avant désactivation | Un rapport mensuel liste les adresses désactivées",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux configurer un double opt-in afin de valider les inscriptions à la newsletter.",
        "Un email de confirmation est envoyé immédiatement après l'inscription | L'abonnement n'est activé qu'après clic sur le lien de confirmation | Le lien expire après 48 heures",
        3, 2
    ),
    (
        "En tant qu'administrateur, je veux prévisualiser un email dans différents clients afin de garantir l'affichage.",
        "La prévisualisation couvre Gmail, Outlook et Apple Mail | Elle inclut la version mobile | Les problèmes détectés sont signalés avec des recommandations",
        3, 2
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=3  — Automatisation des workflows (nouveaux)
# ─────────────────────────────────────────────────
AUTOMATION_WORKFLOW = [
    (
        "En tant qu'administrateur, je veux définir un déclencheur basé sur un événement afin d'automatiser une action.",
        "Les événements disponibles sont la création, la modification et la suppression d'un objet | Le déclencheur peut être filtré selon des conditions sur les champs | Un log d'exécution est disponible pour chaque déclencheur",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux ajouter des branches conditionnelles dans un workflow afin d'adapter les actions selon le contexte.",
        "Les conditions supportent les opérateurs est égal à, contient et est supérieur à | Chaque branche peut avoir ses propres actions | La condition par défaut est appliquée si aucune branche ne correspond",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux planifier l'exécution d'une tâche récurrente afin d'automatiser les opérations périodiques.",
        "La planification supporte les fréquences quotidienne, hebdomadaire et mensuelle | L'heure d'exécution est configurable | Un email d'erreur est envoyé si la tâche échoue",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux créer un workflow d'approbation multi-niveaux afin de valider les demandes importantes.",
        "Les approbateurs sont configurables par niveau | Chaque approbateur reçoit une notification | Le workflow peut être configuré pour rejeter ou escalader en cas de non-réponse dans un délai",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer une règle d'escalade afin de traiter les tâches non prises en charge à temps.",
        "L'escalade se déclenche après un délai configurable sans action | Le responsable hiérarchique est notifié | L'escalade est journalisée dans l'historique du workflow",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux déclencher un webhook vers un système externe afin d'intégrer des actions dans d'autres outils.",
        "L'URL du webhook est configurable par workflow | Le payload JSON est personnalisable avec les champs de l'objet | Les tentatives échouées sont réessayées 3 fois avec un backoff exponentiel",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux sauvegarder un workflow comme modèle afin de le réutiliser pour d'autres processus.",
        "Le modèle est sauvegardé avec ses étapes et conditions | Il est disponible dans une bibliothèque de modèles | Un modèle importé peut être modifié avant activation",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux consulter l'historique des exécutions d'un workflow afin de diagnostiquer les erreurs.",
        "L'historique liste chaque exécution avec son statut réussi, échoué ou en cours | Le détail d'une exécution montre l'étape en erreur | Les logs sont conservés pendant 90 jours",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux mettre en pause un workflow afin de le modifier sans perdre les exécutions en cours.",
        "La mise en pause arrête les nouvelles exécutions immédiatement | Les exécutions en cours se terminent normalement | La reprise est disponible depuis la liste des workflows",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux exécuter des étapes en parallèle dans un workflow afin de réduire le temps de traitement.",
        "Les étapes parallèles démarrent simultanément | Le workflow passe à l'étape suivante quand toutes les branches parallèles sont terminées | Les erreurs dans une branche parallèle sont signalées sans bloquer les autres",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer une alerte en cas d'erreur dans un workflow afin d'agir rapidement.",
        "L'alerte est envoyée par email aux administrateurs désignés | Elle contient le nom du workflow, l'étape en erreur et le message d'erreur | Un lien direct vers le log d'exécution est inclus",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux gérer le respect des SLA dans les workflows afin d'assurer les engagements de service.",
        "Une échéance SLA est configurable par type de demande | Un avertissement est déclenché à 80% de l'échéance | Le dépassement de SLA est enregistré dans les rapports de performance",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux versionner les workflows afin de revenir à une version précédente en cas de problème.",
        "Chaque modification crée une nouvelle version numérotée | L'historique des versions est consultable | La restauration d'une version antérieure est possible en un clic",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux connecter un workflow à un outil externe afin d'automatiser des actions dans cet outil.",
        "Les connecteurs disponibles incluent Jira, Slack et Google Sheets | Les champs de l'objet source sont mappables aux champs de la destination | Les erreurs de connexion sont journalisées et l'administrateur est alerté",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux envoyer une notification par email automatiquement depuis un workflow afin d'informer les parties prenantes.",
        "Le destinataire peut être un champ de l'objet ou une adresse fixe | Le sujet et le corps sont personnalisables avec des variables | Un log confirme l'envoi et le statut de livraison",
        3, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=3  — Chatbot et IA conversationnelle (nouveaux)
# ─────────────────────────────────────────────────
AI_CHATBOT = [
    (
        "En tant qu'utilisateur, je veux poser une question en langage naturel au chatbot afin d'obtenir une réponse sans naviguer dans les menus.",
        "Le chatbot comprend les questions en français et en anglais | Il renvoie une réponse pertinente en moins de 2 secondes | Si la question est hors périmètre, il propose des articles d'aide",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux que le chatbot gère les questions de suivi afin de maintenir le contexte de la conversation.",
        "Le chatbot mémorise les 5 derniers échanges de la session | Les pronoms contextuels comme il ou celui-ci sont correctement interprétés | La session expire après 30 minutes d'inactivité",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux être transféré à un agent humain quand le chatbot ne peut pas répondre afin de résoudre mon problème.",
        "L'escalade vers un humain est proposée après 3 tentatives infructueuses | L'historique de la conversation est transmis à l'agent | Le temps d'attente estimé est affiché",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux ajouter de nouvelles intentions au chatbot afin d'améliorer sa couverture.",
        "L'interface d'administration permet d'ajouter des exemples de phrases par intention | Le modèle est réentraîné automatiquement après ajout | Les nouvelles intentions sont activées sans interruption de service",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux consulter les analyses du chatbot afin d'identifier les questions sans réponse.",
        "Le tableau de bord affiche le taux de résolution, les sujets fréquents et les abandons | Les questions sans réponse sont listées pour enrichir la base de connaissances | Les données sont exportables en CSV",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux accéder à l'historique de mes conversations avec le chatbot afin de retrouver une réponse précédente.",
        "L'historique liste les 30 dernières conversations | Chaque conversation est consultable avec ses messages complets | L'utilisateur peut supprimer une conversation de son historique",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux recevoir des conseils proactifs du chatbot afin d'utiliser des fonctionnalités pertinentes pour mon travail.",
        "Le chatbot propose un conseil personnalisé une fois par session | Les conseils sont basés sur l'activité récente de l'utilisateur | L'utilisateur peut désactiver les conseils proactifs",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux que le chatbot détecte le sentiment négatif afin d'escalader rapidement vers un humain.",
        "Le chatbot détecte les mots exprimant la frustration ou l'urgence | L'escalade automatique est déclenchée si le sentiment est négatif deux fois consécutives | Le client est informé de l'escalade",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux que le chatbot recherche automatiquement dans la base de connaissances afin de fournir une réponse précise.",
        "La base de connaissances est indexée et consultée à chaque question | La réponse cite la source de l'article | L'article source est consultable en un clic",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux noter la qualité de la réponse du chatbot afin d'aider à l'amélioration.",
        "Un formulaire de satisfaction à 5 étoiles apparaît à la fin de chaque conversation | Le score moyen est affiché dans le tableau de bord administrateur | Les notes négatives déclenchent un email de suivi",
        2, 2
    ),
    (
        "En tant qu'utilisateur, je veux que le chatbot propose des produits pertinents afin de faciliter mes décisions d'achat.",
        "Les recommandations sont basées sur l'historique et les préférences | Jusqu'à 3 produits sont proposés avec une brève description | Un lien direct vers la fiche produit est disponible",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer le chatbot en plusieurs langues afin de servir une clientèle internationale.",
        "La langue est détectée automatiquement depuis la langue du navigateur | Les réponses sont disponibles en au moins 3 langues | Le passage d'une langue à l'autre est possible au cours de la conversation",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux intégrer le chatbot dans la page d'aide afin d'avoir une assistance contextuelle.",
        "Le chatbot est accessible via un widget flottant sur toutes les pages | Il s'ouvre avec un message de bienvenue contextualisé selon la page | Il peut être minimisé sans perdre la conversation en cours",
        3, 3
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=4  — Gestion multi-tenant (nouveaux)
# ─────────────────────────────────────────────────
MULTI_TENANCY = [
    (
        "En tant qu'administrateur, je veux que les données de chaque tenant soient isolées afin d'empêcher toute fuite entre clients.",
        "Chaque tenant dispose d'un identifiant unique dans toutes les requêtes | Les requêtes inter-tenants sont bloquées au niveau de la base de données | Des tests d'isolation sont exécutés à chaque déploiement | Une fuite de données entre tenants constitue une violation de données réglementaire",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux activer ou désactiver des fonctionnalités par tenant afin de personnaliser l'offre.",
        "Les feature flags sont configurables par tenant depuis le panneau administrateur | Un changement de flag prend effet en moins de 5 minutes | L'historique des changements de flags est journalisé",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux consulter le tableau de bord de facturation par tenant afin de piloter les revenus.",
        "Le tableau affiche l'usage et le montant facturé par tenant pour le mois en cours | Une comparaison avec le mois précédent est disponible | Les données sont exportables en CSV",
        3, 4
    ),
    (
        "En tant que client, je veux personnaliser l'interface avec ma charte graphique afin d'offrir une expérience de marque cohérente.",
        "Le logo, la couleur principale et la palette secondaire sont configurables | Les changements sont visibles immédiatement dans l'interface | La configuration est appliquée à tous les utilisateurs du tenant",
        3, 4
    ),
    (
        "En tant qu'administrateur tenant, je veux gérer mes propres utilisateurs afin d'être autonome sans dépendre du support.",
        "Le portail self-service permet d'inviter, modifier et désactiver des utilisateurs | Les rôles disponibles sont ceux assignés au tenant | Toutes les actions sont journalisées",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux consulter des rapports agrégés sur tous les tenants afin de mesurer l'usage global de la plateforme.",
        "Les rapports sont agrégés sans exposer les données individuelles des tenants | Les métriques disponibles sont les connexions actives, le stockage et les appels API | Les rapports sont disponibles en temps réel et exportables",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux migrer les données d'un tenant vers un autre environnement afin de changer d'hébergement.",
        "L'outil de migration exporte toutes les données du tenant au format JSON | L'import vérifie l'intégrité des données avant de les appliquer | La migration peut être effectuée sans interruption de service",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux appliquer des limites de ressources par tenant afin de garantir la qualité de service.",
        "Les quotas configurables couvrent les appels API par minute, le stockage et le nombre d'utilisateurs | Le dépassement d'un quota retourne une erreur HTTP 429 | Une alerte est envoyée quand 80% du quota est atteint",
        3, 4
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=4  — Intégrations tierces (nouveaux)
# ─────────────────────────────────────────────────
THIRD_PARTY_INTEGRATIONS = [
    (
        "En tant qu'administrateur, je veux envoyer des notifications dans Slack afin que l'équipe soit alertée sans quitter son outil principal.",
        "La connexion Slack utilise OAuth2 | Le canal de destination est configurable par type d'événement | Les messages Slack incluent un lien direct vers l'objet concerné",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux synchroniser les tickets avec Jira afin de centraliser le suivi des bugs.",
        "La synchronisation est bidirectionnelle | Les modifications dans l'un des systèmes se répercutent dans l'autre en moins de 2 minutes | Les conflits de mise à jour simultanée sont résolus selon une règle de priorité configurable",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux synchroniser les contacts avec Salesforce afin d'éviter la double saisie.",
        "La synchronisation initiale importe tous les contacts existants | Les modifications dans l'un des systèmes se propagent dans l'autre en moins de 5 minutes | Les doublons sont détectés et signalés",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux synchroniser mes événements avec Google Calendar afin de voir tous mes rendez-vous en un seul endroit.",
        "La synchronisation est bidirectionnelle | Les événements créés dans l'application apparaissent dans Google Calendar en moins d'une minute | La déconnexion supprime uniquement les événements créés depuis l'application",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer des webhooks sortants afin d'intégrer l'application dans des outils via Zapier.",
        "Le webhook est déclenché sur les événements configurables | Le payload est au format JSON | Un log des appels avec statut et temps de réponse est disponible",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux archiver les fichiers dans AWS S3 afin de réduire le stockage local.",
        "Les fichiers de plus de 90 jours sont archivés automatiquement | Les fichiers archivés restent accessibles depuis l'interface | Le coût de stockage par tenant est visible dans le tableau de bord",
        3, 4
    ),
    (
        "En tant qu'utilisateur, je veux lier une pull request GitHub à un ticket afin de tracer le code associé.",
        "La liaison se fait en mentionnant l'identifiant du ticket dans la description de la PR | Le statut de la PR est visible sur la fiche du ticket | La fermeture de la PR peut déclencher automatiquement une transition de statut",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux envoyer des alertes dans Microsoft Teams afin d'atteindre les équipes sur site.",
        "La connexion Teams utilise les webhooks entrants | Les alertes respectent le formatage Adaptive Cards | Le canal cible est configurable par type d'alerte",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux synchroniser les deals avec HubSpot afin d'aligner l'équipe commerciale.",
        "Les deals créés dans l'application génèrent un contact HubSpot | Les étapes du pipeline sont mappées entre les deux systèmes | Les erreurs de synchronisation sont journalisées et une alerte est envoyée",
        3, 4
    ),
    (
        "En tant qu'administrateur, je veux envoyer des alertes SMS via Twilio afin d'atteindre les utilisateurs même sans connexion internet.",
        "Les SMS sont envoyés pour les alertes critiques uniquement | Le numéro de téléphone est vérifiable depuis les paramètres utilisateur | Le coût des SMS est visible dans le rapport de facturation",
        3, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=3  — Performance et scalabilité (nouveaux)
# ─────────────────────────────────────────────────
PERFORMANCE_SCALABILITY = [
    (
        "En tant qu'administrateur, je veux configurer un rate limiting par clé API afin d'empêcher les abus.",
        "Le nombre de requêtes par minute est configurable par clé | Les requêtes dépassant la limite reçoivent une erreur HTTP 429 | Le header Retry-After indique le délai avant prochaine tentative",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux implémenter un circuit breaker pour les appels externes afin de protéger le système en cas de panne partenaire.",
        "Le circuit s'ouvre après 5 erreurs consécutives | Les appels sont redirigés vers un fallback pendant l'ouverture | Le circuit se referme automatiquement après 30 secondes",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer un pool de connexions à la base de données afin d'optimiser les performances.",
        "La taille du pool est configurable selon l'environnement | Les connexions inactives depuis plus de 10 minutes sont libérées | Les métriques du pool sont exposées dans le tableau de bord de monitoring",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux distribuer les assets statiques via un CDN afin de réduire la latence pour les utilisateurs distants.",
        "Les assets sont servis depuis le point de présence le plus proche | Les headers de cache sont configurés pour 30 jours | L'invalidation du cache est possible depuis le panneau administrateur",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer l'auto-scaling afin d'adapter les ressources à la charge.",
        "Le scaling horizontal se déclenche quand l'utilisation CPU dépasse 70% pendant 3 minutes | Le scaling se réduit quand l'utilisation est inférieure à 30% pendant 10 minutes | Le minimum et le maximum d'instances sont configurables",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux être alerté quand l'utilisation mémoire dépasse un seuil afin de prévenir les pannes.",
        "L'alerte est configurée à 85% d'utilisation | Elle est envoyée par email et Slack | Le graphique d'utilisation mémoire des dernières 24h est joint à l'alerte",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux détecter les requêtes SQL lentes afin d'optimiser les performances de la base de données.",
        "Les requêtes prenant plus de 500ms sont journalisées | Un rapport hebdomadaire liste les requêtes les plus lentes | Des suggestions d'index sont proposées automatiquement",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux activer la compression HTTP des réponses afin de réduire la bande passante.",
        "La compression gzip et brotli est activée pour les réponses de plus de 1 Ko | Le ratio de compression est visible dans le dashboard de performance | La compression est désactivable par type de contenu",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux définir des quotas de ressources par utilisateur afin d'éviter les monopolisations.",
        "Les quotas couvrent le stockage, le nombre d'exports et les appels API | Le dépassement d'un quota affiche un message explicite | L'administrateur peut augmenter temporairement un quota",
        4, 3
    ),
    (
        "En tant qu'administrateur, je veux vérifier l'état de santé des instances via un endpoint afin de valider les déploiements.",
        "L'endpoint /health retourne le statut de chaque service dépendant | Il retourne HTTP 200 si tout est opérationnel | Il est exclu du rate limiting et accessible sans authentification",
        4, 3
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=4  — Gestion des accès et identité (nouveaux)
# ─────────────────────────────────────────────────
ACCESS_MANAGEMENT = [
    (
        "En tant qu'administrateur, je veux créer et assigner des rôles personnalisés afin de contrôler précisément les accès.",
        "Les rôles sont composables à partir d'une liste de permissions atomiques | Un rôle peut être dupliqué et modifié | L'assignation d'un rôle prend effet immédiatement",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux activer la connexion SSO via SAML 2.0 afin de centraliser l'authentification.",
        "La configuration SAML accepte les IdP Okta, Azure AD et Google Workspace | Le provisionnement automatique des utilisateurs est supporté | La déconnexion globale déconnecte simultanément de l'IdP et de l'application",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux restreindre l'accès par liste blanche d'adresses IP afin de limiter les connexions aux réseaux autorisés.",
        "La liste blanche accepte des adresses IP et des plages CIDR | L'accès depuis une IP non autorisée retourne HTTP 403 | Une alerte est envoyée pour chaque tentative bloquée",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer les sessions actives des utilisateurs afin de révoquer les accès suspects.",
        "La liste des sessions actives affiche l'IP, le navigateur et la date de connexion | Une session peut être révoquée en un clic | L'utilisateur est déconnecté immédiatement après révocation",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux consulter le journal d'audit des changements d'accès afin de tracer les modifications.",
        "Le journal enregistre qui a modifié quoi et quand | Il est filtrable par utilisateur, action et période | Il est exportable en CSV pour audit externe",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux accorder un accès temporaire à un prestataire afin de lui donner les droits nécessaires pour une intervention.",
        "L'accès temporaire a une date d'expiration obligatoire | Il est révocable à tout moment avant l'expiration | Le prestataire est notifié par email de l'accès et de sa durée",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer une politique de complexité de mot de passe afin de renforcer la sécurité.",
        "La politique est configurable en termes de longueur minimale, majuscules, chiffres et caractères spéciaux | Le non-respect de la politique est signalé en temps réel lors de la saisie | L'ancienneté minimale du mot de passe est configurable",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer le verrouillage de compte après N tentatives échouées afin de prévenir les attaques brute force.",
        "Le nombre de tentatives est configurable de 3 à 10 | Le compte est verrouillé pour une durée configurable | Un email de déverrouillage est envoyé à l'utilisateur",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer le cycle de vie des clés API afin de contrôler les accès programmatiques.",
        "Chaque clé a un nom, une description et une portée | La clé est affichée une seule fois à la création | La révocation est immédiate et irréversible",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux définir les scopes OAuth2 exposés afin de contrôler les données accessibles par les applications tierces.",
        "Chaque scope couvre un périmètre de données clairement défini | L'utilisateur est informé des scopes demandés avant d'autoriser une application | Les scopes peuvent être révoqués individuellement par l'utilisateur",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux déléguer certaines tâches administratives à un responsable d'équipe afin de décentraliser la gestion.",
        "La délégation est limitée aux utilisateurs du groupe du délégué | Les actions du délégué sont tracées séparément dans le journal d'audit | La délégation peut être révoquée à tout moment",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer un accès zero-trust afin que chaque requête soit vérifiée même depuis le réseau interne.",
        "Chaque requête est authentifiée et autorisée indépendamment | Le contexte de l'appareil est vérifié à chaque connexion | Un tableau de bord montre les requêtes bloquées en temps réel",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux configurer le SSO pour plusieurs domaines afin de couvrir toutes les entités du groupe.",
        "Chaque domaine peut être associé à un IdP différent | La résolution du domaine se fait depuis l'email saisi | Les utilisateurs de domaines non configurés reçoivent un message explicite",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux implémenter le contrôle d'accès basé sur les attributs afin d'affiner les permissions.",
        "Les attributs pris en compte sont le département, le pays et le niveau hiérarchique | Les règles d'accès sont exprimables en logique booléenne | Les règles sont testables en simulation avant activation",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux surveiller les comportements anormaux d'accès afin de détecter les compromissions de compte.",
        "Un score de risque est calculé pour chaque session selon la localisation, l'heure et le volume d'actions | Un score élevé déclenche une vérification supplémentaire | L'administrateur est alerté pour les sessions à haut risque",
        4, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=4  — DevOps et déploiement continu (nouveaux)
# ─────────────────────────────────────────────────
DEVOPS_DEPLOYMENT = [
    (
        "En tant que développeur, je veux configurer un pipeline CI automatisé afin de valider chaque commit avant intégration.",
        "Le pipeline s'exécute à chaque push sur une branche | Il inclut les étapes de build, de lint et de tests unitaires | Le résultat est visible directement dans la pull request",
        4, 4
    ),
    (
        "En tant que développeur, je veux exécuter les tests automatisés dans le pipeline CI afin de détecter les régressions tôt.",
        "Les tests unitaires et d'intégration sont exécutés dans des conteneurs isolés | Le rapport de tests est publié comme artefact du pipeline | Un échec de test bloque le merge de la pull request",
        4, 4
    ),
    (
        "En tant que développeur, je veux déployer automatiquement en staging après un merge afin de valider en conditions réelles.",
        "Le déploiement en staging est déclenché automatiquement après le merge sur la branche développement | Des tests de fumée sont exécutés après le déploiement | Le lien vers l'environnement staging est posté dans la pull request",
        4, 4
    ),
    (
        "En tant que développeur, je veux déployer une fonctionnalité derrière un feature flag afin de la tester en production avec un sous-ensemble d'utilisateurs.",
        "Le feature flag est configurable depuis le panneau administrateur sans redéploiement | L'activation peut être progressive de 0% à 100% | Les métriques sont séparées entre utilisateurs avec et sans le flag",
        4, 4
    ),
    (
        "En tant que développeur, je veux pouvoir revenir à la version précédente en un clic afin de réduire l'impact d'un problème en production.",
        "Le rollback cible la version immédiatement précédente | Il s'exécute en moins de 5 minutes | Une notification est envoyée à l'équipe après le rollback",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer un registre d'images de conteneurs afin de contrôler les versions déployées.",
        "Chaque image est taguée avec le hash du commit et la version sémantique | Les images non utilisées depuis 90 jours sont supprimées automatiquement | Un scan de vulnérabilités est exécuté à chaque push",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer l'infrastructure via du code versionné afin d'assurer la reproductibilité des environnements.",
        "L'infrastructure est définie dans des fichiers Terraform ou Pulumi | Les changements d'infrastructure passent par une pull request | Un plan d'exécution est présenté avant l'application",
        4, 4
    ),
    (
        "En tant que développeur, je veux exécuter des vérifications de santé post-déploiement afin de valider que le déploiement est réussi.",
        "Des tests de fumée sont lancés automatiquement après chaque déploiement | Le déploiement est considéré en échec si les tests de fumée échouent | Un rollback automatique est déclenché en cas d'échec",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux effectuer la rotation automatique des secrets dans le pipeline afin d'éliminer les secrets statiques.",
        "Les secrets sont récupérés depuis un vault à chaque exécution du pipeline | La rotation est planifiée selon une fréquence configurable | Les pipelines dont les secrets ont expiré sont notifiés",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux gérer des configurations différentes par environnement afin d'isoler les paramètres de développement, staging et production.",
        "Les configurations sont stockées séparément par environnement | Les variables sensibles sont chiffrées | Un diff entre deux environnements est disponible depuis la console",
        4, 4
    ),
    (
        "En tant que développeur, je veux déployer avec la stratégie blue-green afin de supprimer les interruptions de service.",
        "Deux environnements identiques sont maintenus en parallèle | Le routage du trafic est basculé instantanément | L'environnement précédent reste disponible pendant 1 heure pour rollback",
        4, 4
    ),
    (
        "En tant de développeur, je veux effectuer un déploiement canary afin de tester graduellement une nouvelle version.",
        "Le pourcentage de trafic canary est configurable | Les métriques d'erreur et de latence sont comparées entre les deux versions | Le déploiement complet est déclenché manuellement après validation",
        4, 4
    ),
    (
        "En tant qu'administrateur, je veux scanner les dépendances pour les vulnérabilités connues afin de maintenir la sécurité.",
        "Le scan est exécuté à chaque build du pipeline | Les vulnérabilités critiques bloquent le déploiement | Un rapport est envoyé hebdomadairement avec les vulnérabilités par niveau",
        4, 4
    ),
    (
        "En tant que développeur, je veux configurer des portes de qualité de code afin de maintenir les standards du projet.",
        "La couverture de tests minimale est configurable | La duplication de code est limitée à 3% | Le merge est bloqué si les portes de qualité ne sont pas franchies",
        4, 4
    ),
    (
        "En tant que développeur, je veux générer automatiquement les notes de version afin de documenter chaque release.",
        "Les notes sont générées depuis les messages de commit et les labels des pull requests | Elles sont organisées par catégorie correctif, fonctionnalité et amélioration | Elles sont publiées automatiquement dans GitHub Releases",
        4, 4
    ),
]

# ─────────────────────────────────────────────────
# P=4 / I=5  — Conformité réglementaire industrielle (nouveaux)
# ─────────────────────────────────────────────────
INDUSTRY_COMPLIANCE = [
    (
        "En tant qu'administrateur, je veux journaliser tous les événements de sécurité pour la conformité SOC2 afin de prouver la traçabilité.",
        "Tous les accès, modifications et suppressions sont enregistrés avec l'utilisateur, l'heure et l'IP | Les logs sont immuables et conservés pendant 12 mois minimum | Ils sont exportables pour les auditeurs en format JSON ou CSV",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux gérer les données de santé conformément à HIPAA afin de protéger les informations médicales.",
        "Les données PHI sont chiffrées en transit et au repos avec AES-256 | L'accès aux PHI est limité aux utilisateurs avec un rôle médical | Un registre des accès PHI est maintenu et révisé trimestriellement",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux isoler les données de carte de paiement afin de réduire le périmètre PCI-DSS.",
        "Les numéros de carte ne sont jamais stockés en clair dans notre système | Le périmètre PCI est clairement délimité dans la documentation | La conformité est attestée par un QSA annuellement",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux configurer des politiques de rétention des données afin de respecter les obligations légales.",
        "La durée de rétention est configurable par type de données | Les données expirées sont supprimées automatiquement ou archivées | Un rapport de conformité liste les données supprimées",
        4, 5
    ),
    (
        "En tant qu'utilisateur, je veux exercer mon droit à l'effacement afin que mes données soient supprimées conformément au RGPD.",
        "La demande d'effacement est disponible depuis les paramètres du compte | Elle est traitée dans les 30 jours conformément à l'article 17 du RGPD | Une confirmation écrite est envoyée à l'utilisateur",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux configurer la résidence des données par région afin de respecter la souveraineté des données.",
        "La région de stockage est sélectionnable à la création du tenant | Les données ne quittent jamais la région configurée | La conformité est vérifiable via un rapport de localisation des données",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux générer un rapport de conformité exportable afin de préparer les audits.",
        "Le rapport couvre les contrôles de sécurité, les accès et les incidents | Il est disponible au format PDF et Excel | Il peut être planifié pour génération automatique mensuelle",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux évaluer les risques des prestataires tiers afin de valider leur conformité avant intégration.",
        "Un formulaire d'évaluation structuré est disponible par prestataire | Les résultats sont classés par niveau de risque faible, moyen, élevé | Les évaluations sont revisitées annuellement",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux chiffrer toutes les données au repos afin de les protéger en cas de vol de support.",
        "Le chiffrement est AES-256 sur tous les volumes de stockage | Les clés de chiffrement sont gérées dans un HSM | La rotation des clés est planifiée annuellement",
        4, 5
    ),
    (
        "En tant qu'administrateur, je veux contrôler les transferts de données hors de l'UE afin de respecter le chapitre V du RGPD.",
        "Tout transfert hors UE requiert une base légale documentée | Les pays de destination approuvés sont listés et vérifiés | Un registre des transferts est disponible pour les autorités de contrôle",
        4, 5
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=4  — Reprise après sinistre (nouveaux)
# ─────────────────────────────────────────────────
DISASTER_RECOVERY = [
    (
        "En tant qu'administrateur, je veux automatiser les sauvegardes nocturnes de la base de données afin de garantir la récupération des données.",
        "La sauvegarde est déclenchée chaque nuit à 2h00 UTC | Elle couvre toutes les bases de données de production | Un test de restauration automatique est exécuté chaque semaine",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux pouvoir restaurer la base de données à un point précis dans le temps afin de récupérer après une corruption.",
        "La restauration point-in-time est possible sur les 30 derniers jours | La procédure est documentée et testée mensuellement | La durée maximale de restauration est de 4 heures",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux que le basculement vers le site de secours soit automatique afin de minimiser l'interruption de service.",
        "Le basculement se déclenche si le site primaire est indisponible plus de 5 minutes | L'objectif de temps de basculement est inférieur à 15 minutes | Les utilisateurs sont notifiés du basculement par email",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux tester le RTO et le RPO afin de valider les engagements contractuels.",
        "Les tests sont planifiés semestriellement | Les résultats sont documentés dans un rapport | Les écarts par rapport aux objectifs déclenchent un plan d'action",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux simuler des pannes de composants afin de valider la résilience du système.",
        "Les simulations de panne couvrent la base de données, le serveur applicatif et le réseau | Chaque simulation est documentée avec les résultats | Les faiblesses identifiées sont traitées dans un backlog",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux déployer l'application dans plusieurs régions simultanément afin d'éliminer les points de défaillance uniques.",
        "Le trafic est réparti entre les régions via un répartiteur de charge global | La perte d'une région ne dégrade pas les performances de plus de 20% | La synchronisation des données entre régions est inférieure à 1 seconde",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux répliquer les données en temps réel afin de garantir la disponibilité en cas de panne.",
        "La réplication est synchrone pour les données critiques | Le lag de réplication est surveillé et alerté si supérieur à 500ms | Un basculement automatique vers le réplica est possible",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux vérifier l'intégrité des sauvegardes afin de m'assurer qu'elles sont restaurables.",
        "Chaque sauvegarde est vérifiée par un hash SHA-256 | Un test de restauration complet est réalisé mensuellement | Les sauvegardes corrompues déclenchent une alerte immédiate",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux documenter et tester les procédures de reprise afin que l'équipe soit prête en cas de sinistre.",
        "Les procédures sont documentées dans un runbook accessible en ligne et hors ligne | Un exercice grandeur nature est organisé semestriellement | Les participants signent un rapport de participation",
        5, 4
    ),
    (
        "En tant qu'administrateur, je veux automatiser les actions de réponse aux incidents afin de réduire le temps de résolution.",
        "Les runbooks d'incident sont exécutables en un clic | Les actions automatisées incluent le redémarrage de service et la purge de cache | Un rapport post-incident est généré automatiquement",
        5, 4
    ),
]

# ─────────────────────────────────────────────────
# P=5 / I=5  — Opérations financières critiques (nouveaux)
# ─────────────────────────────────────────────────
FINANCIAL_OPERATIONS = [
    (
        "En tant qu'administrateur, je veux réconcilier les transactions en temps réel afin de détecter toute anomalie comptable immédiatement.",
        "Chaque transaction est réconciliée dans les 30 secondes | Les anomalies sont signalées immédiatement avec le montant et la cause | Un rapport de réconciliation journalier est envoyé à l'équipe comptable",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux déployer un modèle de détection de fraude afin de bloquer les transactions suspectes avant exécution.",
        "Le modèle évalue chaque transaction en moins de 200ms | Les transactions avec un score de risque supérieur à 0.85 sont bloquées | Un analyste est notifié pour revue des transactions bloquées",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux surveiller les transactions pour la lutte contre le blanchiment d'argent afin de respecter les obligations AML.",
        "Les transactions dépassant 10 000 euros sont signalées automatiquement | Les schémas de transactions fractionnées sont détectés | Un rapport déclaratif est généré pour Tracfin",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux calculer et reporter le capital réglementaire afin de respecter les exigences prudentielles.",
        "Le calcul respecte les règles de Bâle III | Le rapport est généré au format réglementaire requis | Un audit trail complet du calcul est disponible",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux voir l'exposition au risque en temps réel afin d'agir avant d'atteindre les limites réglementaires.",
        "Le tableau de bord affiche l'exposition par contrepartie, produit et région | Des alertes sont déclenchées à 80% et 95% des limites | Les limites sont configurables par régulateur désigné",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux traiter les règlements de titres afin de finaliser les transactions dans les délais réglementaires T+2.",
        "Chaque règlement est confirmé dans le délai T+2 | Les échecs de règlement sont signalés et réessayés automatiquement | Un rapport de taux d'échec est envoyé quotidiennement",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux automatiser les déclarations réglementaires périodiques afin de respecter les délais de reporting.",
        "Les déclarations sont générées automatiquement selon le calendrier réglementaire | Elles sont soumises électroniquement au régulateur | Un accusé de réception est conservé dans le système",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux garantir l'intégrité du grand livre comptable afin d'assurer l'exactitude des états financiers.",
        "Chaque écriture suit le principe de la comptabilité en partie double | Les déséquilibres sont détectés en temps réel | Un audit du grand livre est disponible par période et par compte",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux gérer les conversions multi-devises afin de traiter des transactions internationales.",
        "Les taux de change sont mis à jour en temps réel depuis une source BCE | La conversion utilise le taux du moment de la transaction | Un rapport des gains et pertes de change est disponible",
        5, 5
    ),
    (
        "En tant qu'administrateur, je veux assurer la conformité PSD2 afin de proposer des services bancaires ouverts en toute légalité.",
        "L'authentification forte (SCA) est requise pour chaque paiement | Les APIs ouvertes respectent le standard Berlin Group NextGenPSD2 | Les accès tiers sont révocables à tout moment par l'utilisateur",
        5, 5
    ),
]

# ─────────────────────────────────────────────────
# P=3 / I=3  — Processus métier moyennement complexes (nouveaux, distinctifs)
# ─────────────────────────────────────────────────
MEDIUM_BUSINESS_PROCESS = [
    (
        "En tant que responsable, je veux configurer un processus d'onboarding automatisé pour les nouveaux employés afin de standardiser l'intégration.",
        "Le workflow déclenche automatiquement la création de compte, l'assignation des formations et l'envoi du kit de bienvenue | Chaque étape peut être validée ou bloquée selon des conditions métier | Un tableau de bord de suivi affiche l'avancement de chaque nouvel arrivant",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux configurer des règles de routage automatique des tickets afin d'assigner les demandes au bon agent.",
        "Les règles portent sur la catégorie, la priorité et la charge de travail des agents | Un ticket non routé après 5 minutes est escaladé au superviseur | Les règles de routage sont testables en simulation avant activation",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux mettre en place un processus de validation des factures fournisseurs afin d'éviter les erreurs de paiement.",
        "La facture passe par trois niveaux de validation : comptable, responsable et directeur financier | Chaque valideur reçoit une notification avec un lien direct vers la facture | Un rejet entraîne une notification au fournisseur avec le motif détaillé",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux automatiser la génération des bons de commande à partir des demandes d'achat afin de réduire les saisies manuelles.",
        "Le bon de commande est généré en PDF avec les informations du fournisseur et les lignes d'achat | Les données sont récupérées automatiquement depuis le catalogue fournisseur | Un numéro de commande unique est attribué séquentiellement",
        3, 3
    ),
    (
        "En tant que responsable RH, je veux configurer les règles de calcul des congés afin d'automatiser leur gestion.",
        "Les règles tiennent compte du type de contrat, de l'ancienneté et des jours fériés | Le solde est recalculé automatiquement après chaque validation de congé | Un rapport mensuel liste les soldes et les mouvements par employé",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux que le système détecte automatiquement les doublons lors de l'import de contacts afin d'éviter la duplication.",
        "La détection compare le nom, l'email et le numéro de téléphone | Les doublons potentiels sont présentés avec un score de similarité | L'utilisateur choisit de fusionner, ignorer ou créer un nouveau contact",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer des quotas d'utilisation par département afin de contrôler la consommation des ressources.",
        "Les quotas sont configurables en volume de stockage, nombre d'exports et appels API par mois | Un avertissement est envoyé au responsable à 80% du quota | Le dépassement bloque les nouvelles actions et déclenche une alerte",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux créer des rapports planifiés afin de recevoir des analyses régulières sans intervention manuelle.",
        "Le rapport est généré selon une fréquence configurable (quotidienne, hebdomadaire, mensuelle) | Les destinataires sont configurables par rapport | Le rapport inclut une comparaison avec la période précédente",
        3, 3
    ),
    (
        "En tant que gestionnaire, je veux configurer des alertes de dépassement de budget afin d'anticiper les dérives financières.",
        "L'alerte est déclenchée quand 75% et 100% du budget est consommé | Elle est envoyée par email au responsable de budget et à son manager | Un tableau récapitulatif des dépenses par catégorie est joint",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux suivre le cycle de vie complet d'une demande afin de savoir où elle en est.",
        "Le statut de la demande est visible à chaque étape : soumise, en cours d'analyse, approuvée, en traitement, clôturée | Chaque changement de statut est notifié aux parties concernées | Un historique complet des actions est consultable",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer des SLA par type de ticket afin d'assurer les engagements de service.",
        "Chaque type de ticket a une priorité et un SLA associé (réponse initiale et résolution) | Un code couleur signale les tickets proches ou dépassant leur SLA | Un rapport hebdomadaire compare le taux de respect des SLA par agent",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux fusionner deux enregistrements en double afin d'assainir les données.",
        "L'outil de fusion affiche les deux enregistrements côte à côte | L'utilisateur choisit quelle valeur conserver champ par champ | L'enregistrement source est supprimé après fusion et ses relations sont transférées",
        3, 3
    ),
    (
        "En tant que responsable, je veux configurer un tableau de bord de KPIs afin de piloter la performance de l'équipe.",
        "Les KPIs disponibles sont configurables depuis une bibliothèque de métriques | Chaque KPI affiche la valeur courante, l'objectif et la tendance | Le tableau de bord peut être partagé en lecture seule avec des parties prenantes",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux configurer des rappels automatiques pour les tâches récurrentes afin de ne pas les oublier.",
        "La récurrence est configurable en jours, semaines ou mois | Le rappel est envoyé N jours avant l'échéance configurable | La tâche est recréée automatiquement après clôture selon la récurrence définie",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux importer une arborescence de catégories depuis un fichier Excel afin d'alimenter le référentiel.",
        "Le fichier Excel définit les niveaux hiérarchiques par indentation | Les catégories existantes sont mises à jour, les nouvelles sont créées | Un rapport d'import liste les catégories ajoutées, modifiées et ignorées",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux configurer des notifications d'événements métier afin de rester informé en temps réel.",
        "Les événements configurables sont la création, la modification et le changement de statut d'objets | Le canal de notification est configurable par événement (email, push, SMS) | Les notifications peuvent être regroupées pour éviter le spam",
        3, 3
    ),
    (
        "En tant que responsable, je veux configurer les étapes d'un pipeline de vente afin d'adapter le processus commercial.",
        "Les étapes sont personnalisables en nom, couleur et probabilité de conversion associée | Un deal peut être déplacé entre les étapes par glisser-déposer | Les prévisions de chiffre d'affaires sont calculées automatiquement depuis la probabilité",
        3, 3
    ),
    (
        "En tant qu'administrateur, je veux configurer un système de points de fidélité afin de récompenser les clients réguliers.",
        "Les règles d'attribution des points sont configurables par type d'achat | Le solde de points est visible sur le compte client | Les points expirés sont annulés et le client est notifié 30 jours avant",
        3, 3
    ),
    (
        "En tant qu'utilisateur, je veux annoter des enregistrements avec des commentaires internes afin de partager des observations avec l'équipe.",
        "Les annotations internes ne sont pas visibles par les clients | Elles supportent le texte riche, les mentions et les pièces jointes | L'historique des annotations est conservé même après modification ou suppression",
        3, 3
    ),
    (
        "En tant que responsable, je veux comparer les performances de deux périodes afin de mesurer l'impact des actions menées.",
        "La comparaison affiche les métriques clés côte à côte pour les deux périodes | Les variations sont affichées en valeur absolue et en pourcentage | Le rapport de comparaison est exportable en PDF avec les graphiques",
        3, 3
    ),
]

# ─────────────────────────────────────────────────
# Assembler toutes les listes
# ─────────────────────────────────────────────────
ALL_POOLS = (
    UI_COSMETIC +
    UI_FUNCTIONAL_LOW +
    CRUD_SIMPLE +
    SEARCH_FILTER +
    FUNCTIONAL_MEDIUM_LOW +
    WORKFLOW_MEDIUM +
    ROLES_MEDIUM_HIGH +
    API_INTEGRATION +
    AUTH_COMPLEX +
    GDPR_SENSITIVE +
    PAYMENT_HIGH +
    PAYMENT_CRITICAL +
    LOW_IMPACT +
    SECURITY_HIGH +
    VALIDATION_UPLOAD +
    REGISTRATION +
    CART +
    INVENTORY +
    ORDER_MANAGEMENT +
    I18N +
    CRITICAL_DATA +
    ACCESSIBILITY_COSMETIC +
    UX_USEFUL +
    MINOR_ACTIONS +
    CRUD_EXTENDED +
    COLLABORATION_LIGHT +
    NOTIFICATION_EXTRA +
    COLLAB_WORKFLOW_EXTRA +
    DOCUMENT_MGMT +
    VALIDATION_EXTRA +
    API_PERFORMANCE +
    SUBSCRIPTION +
    PRIVACY_COMPLIANCE +
    SECURITY_CRITICAL +
    PAYMENT_ADVANCED +
    CRITICAL_COMPLIANCE +
    HELP_SUPPORT +
    USER_ONBOARDING +
    USER_SETTINGS +
    DASHBOARD_WIDGETS +
    MOBILE_APP +
    SOCIAL_COLLABORATION +
    EMAIL_CAMPAIGNS +
    AUTOMATION_WORKFLOW +
    AI_CHATBOT +
    MULTI_TENANCY +
    THIRD_PARTY_INTEGRATIONS +
    PERFORMANCE_SCALABILITY +
    ACCESS_MANAGEMENT +
    DEVOPS_DEPLOYMENT +
    INDUSTRY_COMPLIANCE +
    DISASTER_RECOVERY +
    FINANCIAL_OPERATIONS +
    MEDIUM_BUSINESS_PROCESS
)

# ============================================================
# CORRECTION DES SCORES P/I
# Objectif : rendre les classes plus cohérentes et séparables.
# On ne rajoute aucune user story. On modifie uniquement probabilite/impact.
# ============================================================

# Mets 300 si tu veux absolument générer 300 lignes.
# Mets None pour garder toutes les user stories disponibles.
TARGET_ROWS = None


def _contains(text: str, words: list[str]) -> bool:
    text = text.lower()
    return any(w in text for w in words)


def corriger_pi(user_story: str, criteres: str, p_initial: int, i_initial: int) -> tuple[int, int]:
    """
    Corrige P et I à partir du contenu fonctionnel.

    Règle de lecture :
    - P = probabilité de complexité / risque technique.
    - I = impact métier / sécurité / financier en cas d'échec.

    Cette correction évite les incohérences du type :
    - notification simple notée comme workflow critique ;
    - paiement ou fraude pas toujours en impact maximal ;
    - UI cosmétique mélangée avec CRUD utile.
    """
    t = f"{user_story} {criteres}".lower()

    # Très faible risque : cosmétique, texte, affichage simple.
    if _contains(t, [
        "couleur", "icône", "faute de frappe", "libellé", "placeholder",
        "logo", "pied de page", "infobulle", "taille de la police",
        "astérisque", "spinner", "animation de chargement", "retour en haut"
    ]):
        return 1, 1

    # Paiement, banque, fraude : risque technique et impact très élevés.
    if _contains(t, [
        "paiement", "payer", "carte bancaire", "paypal", "apple pay",
        "3d secure", "3ds", "sca", "dsp2", "sepa", "virement",
        "remboursement", "fraude", "transaction", "réconciliation bancaire",
        "pci-dss", "abonnement soit renouvelé automatiquement", "mandat"
    ]):
        return 5, 5

    # Données personnelles / conformité critique : impact maximal.
    if _contains(t, [
        "rgpd", "droit à l'oubli", "données personnelles", "consentement",
        "anonymiser", "portabilité", "journaliser tous les accès", "audit rgpd",
        "conformité réglementaire", "conservation légale"
    ]):
        return 4, 5

    # Sécurité critique et identité forte.
    if _contains(t, [
        "sso", "saml", "oauth", "webauthn", "totp", "otp", "2fa",
        "authentification à deux facteurs", "politique de mot de passe",
        "réinitialiser mon mot de passe", "sessions actives", "nouvel appareil",
        "force brute", "waf", "injections", "sqli", "xss", "chiffrer",
        "tls", "rate limiting", "malwares", "pare-feu", "clé api"
    ]):
        # Sécurité pure : P élevé ; I élevé mais pas toujours 5 si pas financier/RGPD.
        return 4, 4

    # Administration des accès et rôles : impact élevé.
    if _contains(t, [
        "rôle", "permission", "permissions", "groupe d'utilisateurs",
        "suspendre", "désactiver un compte", "restriction d'accès", "adresse ip",
        "journal d'audit", "super-administrateur", "accès"
    ]):
        return 4, 4

    # API, intégration, performance, infrastructure : P élevé, impact moyen.
    if _contains(t, [
        "api", "webhook", "erp", "slack", "service externe", "synchroniser",
        "cache", "pagination côté serveur", "file d'attente", "retry",
        "backoff", "circuit breaker", "pool de connexions", "cdn",
        "auto-scaling", "endpoint /health", "compression http", "quota",
        "déploiement", "backup", "restauration", "monitoring"
    ]):
        return 4, 3

    # Upload / validation avancée : risque technique moyen-haut, impact limité à moyen.
    if _contains(t, [
        "upload", "fichier", "pièce jointe", "mime", "extension", "siret",
        "dns mx", "rfc 5322", "recadrage", "compression", "path traversal",
        "importer un fichier", "csv", "xlsx"
    ]):
        return 3, 3

    # Workflow métier, approbation, automatisation, notification structurée.
    if _contains(t, [
        "approuver", "rejeter", "workflow", "pipeline", "automatique",
        "rapport hebdomadaire", "résumé quotidien", "planifier", "assignée",
        "alerte", "notification", "calendrier", "dépendance", "modèle de document",
        "état d'avancement", "commentaire", "mentionner", "collègue"
    ]):
        return 3, 3

    # Recherche, filtre, tri, export simple : risque faible/moyen, impact moyen.
    if _contains(t, [
        "rechercher", "filtrer", "trier", "exporter", "rapport en pdf",
        "csv", "pagination", "résultats", "plage de dates", "catégorie",
        "statut", "priorité", "filtre personnalisé"
    ]):
        return 2, 3

    # CRUD simple / profil / préférences / favoris : faible-moyen.
    if _contains(t, [
        "modifier", "supprimer", "créer", "ajouter", "archiver", "dupliquer",
        "profil", "adresse", "note", "tag", "favoris", "préférences",
        "liste de souhaits", "commentaire public", "photo de profil", "biographie"
    ]):
        return 2, 2

    # Par défaut : on garde le score initial, mais on évite les extrêmes non justifiés.
    p = min(max(int(p_initial), 1), 5)
    i = min(max(int(i_initial), 1), 5)
    return p, i


print(f"Total user stories disponibles : {len(ALL_POOLS)}")

# Construire le DataFrame avec correction P/I
rows = []
for us, ac, p, i in ALL_POOLS:
    p_corrige, i_corrige = corriger_pi(us, ac, p, i)
    rows.append({
        "user_story": us.strip(),
        "criteres_acceptation": ac.strip(),
        "probabilite": p_corrige,
        "impact": i_corrige,
    })

df = pd.DataFrame(rows)

# Supprimer les doublons exacts, sans ajouter de nouvelles lignes.
df = df.drop_duplicates(subset=["user_story", "criteres_acceptation"]).reset_index(drop=True)

# Option : revenir à 300 lignes sans ajouter de données.
# On fait un échantillonnage stratifié par couple P/I pour garder une distribution stable.
if TARGET_ROWS is not None and len(df) > TARGET_ROWS:
    df = (
        df.groupby(["probabilite", "impact"], group_keys=False)
          .apply(lambda x: x.sample(
              n=max(1, round(len(x) / len(df) * TARGET_ROWS)),
              random_state=42
          ))
          .sample(frac=1, random_state=42)
          .head(TARGET_ROWS)
          .reset_index(drop=True)
    )
else:
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)

# Vérifications utiles avant entraînement
print("\nDistribution probabilite :")
print(df["probabilite"].value_counts().sort_index())

print("\nDistribution impact :")
print(df["impact"].value_counts().sort_index())

print("\nCrosstab P x I :")
print(pd.crosstab(df["probabilite"], df["impact"]))

print(f"\nCritères uniques : {df['criteres_acceptation'].nunique()} / {len(df)}")
print(f"User stories uniques : {df['user_story'].nunique()} / {len(df)}")

# Sauvegarder
import tempfile, shutil, os

output_path = "data/risk_dataset.xlsx"
os.makedirs(os.path.dirname(output_path), exist_ok=True)
tmp_path = output_path + ".tmp.xlsx"

df.to_excel(tmp_path, index=False)
if os.path.exists(output_path):
    os.remove(output_path)
shutil.move(tmp_path, output_path)

print(f"\nDataset sauvegardé : {output_path}  ({len(df)} lignes)")

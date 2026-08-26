# TestForge AI

Plateforme de génération et d'exécution de tests assistée par IA. Le projet est composé de trois parties :

- **backend/** — API FastAPI (Python)
- **frontend/** — application Angular
- **Serveur MCP Playwright** — utilisé par le backend pour exécuter les tests dans un navigateur

## Prérequis

- Python 3.11+ et pip
- Node.js 22+ et npm
- PostgreSQL (une base de données locale)
- PowerShell (pour le script de lancement automatique, Windows uniquement)

## 1. Configuration des variables d'environnement

Le backend a besoin d'un fichier `backend/.env` qui n'est pas versionné sur Git (il contient des clés secrètes).

1. Copier le modèle fourni :
   ```
   cd backend
   copy .env.example .env
   ```
2. Ouvrir `backend/.env` et remplacer chaque valeur entre `<...>` par la vraie valeur (clés API, identifiants de base de données, etc.). Ces valeurs doivent être transmises séparément par la personne qui gère le projet — jamais via GitHub.
3. Adapter en particulier `DATABASE_URL` avec les identifiants de votre PostgreSQL local :
   ```
   DATABASE_URL=postgresql+asyncpg://<utilisateur>:<mot_de_passe>@localhost:5432/<nom_de_la_base>
   ```
   La base `<nom_de_la_base>` doit exister au préalable dans PostgreSQL.

## 2. Installation du backend

```
cd backend
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Appliquer les migrations de base de données :

```
alembic upgrade head
```

## 3. Installation du frontend

```
cd frontend
npm install
```

## 4. Serveur MCP Playwright

Le backend pilote les navigateurs de test via un serveur MCP Playwright. Il n'a pas besoin d'installation préalable, `npx` le télécharge automatiquement au premier lancement.

## Lancer la solution

### Option A — Tout lancer en une seule commande (Windows)

Depuis la racine du projet, exécuter le script PowerShell :

```
./start-all.ps1
```

Ce script vérifie que le venv backend, le fichier `.env` et les `node_modules` du frontend sont présents, puis ouvre trois fenêtres PowerShell :

- Backend FastAPI sur http://localhost:8000
- Serveur MCP Playwright sur http://localhost:8931
- Frontend Angular sur http://localhost:4200

Laisser les trois fenêtres ouvertes pendant l'utilisation de l'application. Pour tout arrêter, fermer les trois fenêtres.

### Option B — Lancer chaque service séparément

**Terminal 1 — Backend**
```
cd backend
venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

**Terminal 2 — Serveur MCP Playwright**
```
npx @playwright/mcp@latest --port 8931
```

**Terminal 3 — Frontend**
```
cd frontend
npm start
```

L'application est ensuite accessible sur http://localhost:4200, l'API backend sur http://localhost:8000.

## Dépannage

- **`venv introuvable`** : créer l'environnement virtuel avec `python -m venv venv` dans `backend/`, puis installer les dépendances.
- **`backend\.env` absent** : voir la section Configuration ci-dessus.
- **`node_modules` absent** : lancer `npm install` dans `frontend/`.
- **Erreur de connexion à la base de données** : vérifier que PostgreSQL est démarré et que `DATABASE_URL` dans `backend/.env` correspond aux identifiants réels, puis lancer `alembic upgrade head`.

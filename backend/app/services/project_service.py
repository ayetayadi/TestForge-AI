from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
from typing import List, Dict, Any, Optional

from app.models.user import User
from app.models.user_story import UserStory as UserStoryModel

from app.repositories.project_repository import (
    create_project,
    delete_project_by_id,
    get_project_by_key,
    get_projects_with_story_count,
)

from app.services.jira_session_manager import JiraSessionManager
from app.services.user_story_service import import_project_stories
from app.services.notification_service import NotificationService, JiraChangeDetector as StoryChangeDetector

async def get_all_projects(db: AsyncSession, user_id: Optional[str] = None):
    """Récupère les projets de l'utilisateur avec leur nombre de stories"""
    projects = await get_projects_with_story_count(db, user_id=user_id)
    projects.sort(key=lambda p: p.story_count, reverse=True)
    return [
        {
            "id": p.id,
            "project_key": p.project_key,
            "project_name": p.project_name,
            "story_count": p.story_count,
        }
        for p in projects
    ]


async def import_project_by_key(
    db: AsyncSession,
    project_key: str,
    current_user: User,
    epic_key: Optional[str] = None,
    sprint_name: Optional[str] = None,
    notify_changes: bool = True,
    use_or: bool = False,
) -> dict:
    """
    Importe un projet Jira avec détection des changements et notifications
    
    Args:
        db: Session database
        project_key: Clé du projet Jira (ex: "PROJ")
        current_user: Utilisateur courant
        epic_key: Filtrer par epic (optionnel)
        sprint_name: Filtrer par sprint (optionnel)
        notify_changes: Activer/désactiver les notifications
        use_or: Mode UNION (OU) au lieu de INTERSECTION (ET)
    
    Returns:
        Dictionnaire avec les résultats de l'import
    """
    
    print(f"\n[IMPORT] 📥 Début de l'import du projet {project_key}")
    
    try:
        manager = JiraSessionManager(db)
        conn = await manager.get_connection(current_user.id)
        client = await manager.get_client(conn)
        
        print(f"[IMPORT] ✅ Connexion Jira établie")

        # =========================
        # FETCH PROJECTS
        # =========================
        print(f"[IMPORT] 🔍 Recherche du projet {project_key} dans Jira...")
        jira_projects = await client.get_projects()
        jira_project = {p["key"]: p for p in jira_projects}.get(project_key)

        if not jira_project:
            raise HTTPException(404, f"Project {project_key} not found in Jira")
        
        print(f"[IMPORT] ✅ Projet trouvé: {jira_project['name']}")

        # =========================
        # CREATE OR GET PROJECT
        # =========================
        project = await get_project_by_key(db, project_key)

        if not project:
            print(f"[IMPORT] 📝 Création du projet dans la base de données...")
            project = await create_project(
                db,
                jira_connection_id=conn.id,
                project_key=jira_project["key"],
                project_name=jira_project["name"],
            )
            print(f"[IMPORT] ✅ Projet créé (ID: {project.id})")
        else:
            print(f"[IMPORT] ✅ Projet existant trouvé (ID: {project.id})")

        # =========================
        # FETCH STORIES (with optional filters)
        # =========================
        print(f"[IMPORT] 📡 Récupération des stories depuis Jira...")
        if epic_key:
            print(f"[IMPORT]   • Filtre epic: {epic_key}")
        if sprint_name:
            print(f"[IMPORT]   • Filtre sprint: {sprint_name}")
            
        jira_issues = await client.get_stories(
            project_key,
            epic_key=epic_key,
            sprint_name=sprint_name,
            use_or=use_or,
        )
        
        print(f"[IMPORT] ✅ {len(jira_issues)} stories récupérées de Jira")
        
        # =========================
        # DÉTECTER LES CHANGEMENTS
        # =========================
        print(f"\n[IMPORT] 🔄 Détection des changements...")
        detector = StoryChangeDetector(db)
        changes = await detector.detect(project_key, jira_issues)
        
        print(f"[IMPORT] 📊 Changements détectés:")
        print(f"[IMPORT]   • Ajoutées: {len(changes['added'])}")
        print(f"[IMPORT]   • Modifiées: {len(changes['updated'])}")
        print(f"[IMPORT]   • Supprimées: {len(changes['deleted'])}")
        
        # Afficher les détails des changements
        if changes['added']:
            print(f"[IMPORT]   ✨ Nouvelles stories:")
            for story in changes['added']:
                print(f"[IMPORT]      → {story['key']}: {story.get('summary', '')[:50]}...")
        
        if changes['updated']:
            print(f"[IMPORT]   📝 Stories modifiées:")
            for story in changes['updated']:
                print(f"[IMPORT]      → {story['key']}: {story.get('summary', '')[:50]}...")
        
        if changes['deleted']:
            print(f"[IMPORT]   🗑️ Stories supprimées:")
            for story in changes['deleted']:
                print(f"[IMPORT]      → {story.issue_key}")
        
        # =========================
        # IMPORTER LES STORIES
        # =========================
        print(f"\n[IMPORT] 💾 Import des stories dans la base de données...")
        import_result = await import_project_stories(db, project, jira_issues)
        print(f"[IMPORT] ✅ Import terminé: {import_result}")
        
        # =========================
        # ENVOYER LES NOTIFICATIONS
        # =========================
        if notify_changes and (changes["added"] or changes["updated"] or changes["deleted"]):
            print(f"\n[IMPORT] 📢 Envoi des notifications...")
            notification_service = NotificationService(db, client)
            await notification_service.notify_jira_changes(project_key, changes)
            print(f"[IMPORT] ✅ Notifications envoyées")
        else:
            print(f"[IMPORT] ⏭️ Aucune notification envoyée (notify_changes=False ou aucun changement)")
        
        await db.commit()
        
        print(f"\n[IMPORT] ✅ Import terminé avec succès!")
        
        return {
            "message": "Import successful",
            "project": {
                "key": project.project_key,
                "name": project.project_name,
            },
            "changes": {
                "added_count": len(changes["added"]),
                "updated_count": len(changes["updated"]),
                "deleted_count": len(changes["deleted"]),
                "added": [s["key"] for s in changes["added"]],
                "updated": [s["key"] for s in changes["updated"]],
                "deleted": [s.issue_key for s in changes["deleted"]],
            },
            "result": import_result,
        }
        
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        print(f"[IMPORT] ❌ Erreur fatale: {str(e)}")
        raise HTTPException(500, f"Import failed: {str(e)}")


async def delete_project(db: AsyncSession, project_id: str):
    """Supprime un projet et toutes ses stories associées"""
    
    print(f"\n[DELETE] 🗑️ Suppression du projet {project_id}")
    
    deleted = await delete_project_by_id(db, project_id)

    if not deleted:
        print(f"[DELETE] ❌ Projet {project_id} non trouvé")
        raise ValueError("Project not found")

    await db.commit()
    
    print(f"[DELETE] ✅ Projet {project_id} supprimé avec succès")

    return {"message": "Project deleted successfully"}
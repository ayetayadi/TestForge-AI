import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { InAppNotificationService, AppNotification } from 'src/app/services/in-app-notification.service';

@Component({
  selector: 'app-notification-bell',
  standalone: true,
  imports: [CommonModule, MaterialModule],
  templateUrl: './notification-bell.component.html',
  styleUrl: './notification-bell.component.scss',
})
export class NotificationBellComponent {
  readonly notifService = inject(InAppNotificationService);

  get notifications() { return this.notifService.notifications; }
  get unreadCount()   { return this.notifService.unreadCount; }
  get loading()       { return this.notifService.loading; }
  get syncing()       { return this.notifService.syncing; }
  get projectKey()    { return this.notifService.projectKey; }

  markRead(notif: AppNotification, event: Event): void {
    event.stopPropagation();
    if (!notif.is_read) this.notifService.markRead(notif.id);
  }

  markAllRead(event: Event): void {
    event.stopPropagation();
    this.notifService.markAllRead();
  }

  syncJira(event: Event): void {
    event.stopPropagation();
    this.notifService.syncJira();
  }

  getIcon(type: string): string {
    const map: Record<string, string> = {
      story_added:     'add_circle_outline',
      story_updated:   'edit_note',
      story_deleted:   'delete_outline',
      quality_issue:   'warning_amber',
      ambiguous_story: 'help_outline',
      story_approved:  'check_circle_outline',
      story_refined:   'auto_fix_high',
      jira_sync:       'sync',
    };
    return map[type] ?? 'notifications';
  }

  getSeverityClass(severity: string): string {
    return `sev-${severity}`;
  }

  getRelativeTime(isoDate: string): string {
    const diffMs = Date.now() - new Date(isoDate).getTime();
    const minutes = Math.floor(diffMs / 60_000);
    if (minutes < 1)  return "à l'instant";
    if (minutes < 60) return `il y a ${minutes} min`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24)   return `il y a ${hours}h`;
    const days = Math.floor(hours / 24);
    return `il y a ${days}j`;
  }

  /** Extract Ajoutées / Modifiées / Supprimées lines from the notification body. */
  getChangedLines(notif: AppNotification): string[] {
    if (!notif.body) return [];
    return notif.body
      .split('\n')
      .filter(line => /^(Ajoutées?|Modifiées?|Supprimées?)\s*:/i.test(line.trim()));
  }
}

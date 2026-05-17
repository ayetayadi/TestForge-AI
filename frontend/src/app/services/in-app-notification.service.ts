import { Injectable, NgZone, signal, computed, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom, Subject } from 'rxjs';
import { environment } from 'src/environments/environment';
import { ToastService } from './toast.service';

export interface AppNotification {
  id: string;
  type: 'story_added' | 'story_updated' | 'story_deleted' | 'quality_issue' | 'ambiguous_story' | 'story_approved' | 'story_refined';
  title: string;
  body: string;
  severity: 'info' | 'warning' | 'error';
  issue_key: string | null;
  is_read: boolean;
  jira_comment_posted: boolean;
  created_at: string;
}

const SSE_EVENTS = ['jira_sync', 'quality_issue', 'ambiguous_story', 'story_approved', 'ping'];
const MAX_RECONNECT = 5;
const RECONNECT_BASE_MS = 3000;
const POLL_INTERVAL_MS = 1 * 60 * 1000; // check Jira for changes every 1 minute

@Injectable({ providedIn: 'root' })
export class InAppNotificationService {
  private http = inject(HttpClient);
  private toast = inject(ToastService);
  private zone = inject(NgZone);

  // ─── State ───────────────────────────────────────────────────────────────
  readonly projectKey = signal<string | null>(null);
  readonly notifications = signal<AppNotification[]>([]);
  readonly loading = signal(false);
  readonly syncing = signal(false);

  readonly unreadCount = computed(() =>
    this.notifications().filter(n => !n.is_read).length
  );

  /** Emits after a successful Jira sync so subscribers can reload data. */
  readonly syncCompleted$ = new Subject<void>();

  // ─── Private ─────────────────────────────────────────────────────────────
  private eventSource: EventSource | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pollTimer: ReturnType<typeof setInterval> | null = null;

  // ─── Public API ──────────────────────────────────────────────────────────

  /** Call this when the user selects a project (from the projects page). */
  connect(projectKey: string): void {
    if (this.projectKey() === projectKey) return;

    this.projectKey.set(projectKey);
    this._disconnectSSE();
    this._stopPolling();
    this.notifications.set([]);
    this._connectSSE();
    this._startPolling();
  }

  disconnect(): void {
    this._disconnectSSE();
    this._stopPolling();
    this.projectKey.set(null);
    this.notifications.set([]);
  }

  async markRead(id: string): Promise<void> {
    this.notifications.update(list =>
      list.map(n => n.id === id ? { ...n, is_read: true } : n)
    );
    try {
      await firstValueFrom(
        this.http.post(`${environment.apiUrl}/notifications/${id}/read`, {})
      );
    } catch {
      // Silent — optimistic update already applied
    }
  }

  async markAllRead(): Promise<void> {
    const key = this.projectKey();
    if (!key) return;
    this.notifications.update(list => list.map(n => ({ ...n, is_read: true })));
    try {
      await firstValueFrom(
        this.http.post(`${environment.apiUrl}/notifications/${key}/read-all`, {})
      );
    } catch {
      // Silent
    }
  }

  async syncJira(): Promise<void> {
    const key = this.projectKey();
    if (!key || this.syncing()) return;

    this.syncing.set(true);
    try {
      await firstValueFrom(
        this.http.post<any>(`${environment.apiUrl}/sync/jira/${key}`, {})
      );
      this.toast.success('Synchronisation terminée', `Projet ${key} synchronisé avec Jira`);
      this.syncCompleted$.next();
    } catch {
      this.toast.error('Erreur de synchronisation', 'Impossible de synchroniser avec Jira');
    } finally {
      this.syncing.set(false);
    }
  }

  // ─── REST ────────────────────────────────────────────────────────────────

  // private async _fetchNotifications(): Promise<void> {
  //   const key = this.projectKey();
  //   if (!key) return;

  //   this.loading.set(true);
  //   try {
  //     const list = await firstValueFrom(
  //       this.http.get<AppNotification[]>(`${environment.apiUrl}/notifications/${key}?limit=30`)
  //     );
  //     this.notifications.set(list);
  //   } catch {
  //     // Silent — will be populated via SSE anyway
  //   } finally {
  //     this.loading.set(false);
  //   }
  // }

  // ─── SSE ─────────────────────────────────────────────────────────────────

  private _connectSSE(): void {
    const key = this.projectKey();
    if (!key) return;

    const token = localStorage.getItem('access_token') ?? '';
    const url = `${environment.apiUrl}/notifications/stream/${key}?token=${encodeURIComponent(token)}`;

    this.eventSource = new EventSource(url);
    this.reconnectAttempts = 0;
    let everOpened = false;

    this.eventSource.onopen = () => { everOpened = true; };

    SSE_EVENTS.forEach(eventType => {
      this.eventSource!.addEventListener(eventType, (ev: MessageEvent) => {
        this.zone.run(() => {
          if (eventType === 'ping') return;
          try {
            const data = JSON.parse(ev.data);
            this._handleSSEEvent(eventType, data);
          } catch {
            // malformed event — ignore
          }
        });
      });
    });

    this.eventSource.onerror = () => {
      this.zone.run(() => {
        // If the connection never opened, it's a permanent failure (401, 403, wrong URL).
        // Don't retry — it would loop forever.
        if (!everOpened && this.eventSource?.readyState === EventSource.CLOSED) {
          console.warn('[SSE] Permanent connection failure — not retrying');
          this._disconnectSSE();
          return;
        }
        this._scheduleReconnect();
      });
    };
  }

  private _handleSSEEvent(type: string, data: any): void {
    const incoming: AppNotification = {
      id: data.id ?? crypto.randomUUID(),
      type: data.type ?? type as any,
      title: data.title ?? '',
      body: data.body ?? '',
      severity: data.severity ?? 'info',
      issue_key: data.issue_key ?? null,
      is_read: false,
      jira_comment_posted: false,
      created_at: data.timestamp ?? new Date().toISOString(),
    };
    this.notifications.update(list => [incoming, ...list]);

    // Show a toast for immediate feedback
    const toastMap: Record<string, () => void> = {
      jira_sync:       () => this.toast.info(data.title ?? 'Synchronisation Jira', ''),
      quality_issue:   () => this.toast.warning(data.title ?? 'Alerte qualité', data.issue_key ?? ''),
      ambiguous_story: () => this.toast.error(data.title ?? 'User Story ambiguë', `Action requise — ${data.issue_key ?? ''}`),
      story_approved:  () => this.toast.success(data.title ?? 'User Story approuvée', ''),
    };
    toastMap[type]?.();
  }

  private _startPolling(): void {
    this._stopPolling();
    this.pollTimer = setInterval(async () => {
      const key = this.projectKey();
      if (!key || this.syncing()) return;
      try {
        const result = await firstValueFrom(
          this.http.get<{ has_changes: boolean }>(`${environment.apiUrl}/sync/jira/${key}/check`)
        );
        if (result.has_changes) {
          await this.syncJira();
        }
      } catch {
        // Silent — polling failure should not surface to the user
      }
    }, POLL_INTERVAL_MS);
  }

  private _stopPolling(): void {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private _scheduleReconnect(): void {
    if (this.reconnectAttempts >= MAX_RECONNECT) return;

    this._disconnectSSE();
    const delay = RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      if (this.projectKey()) this._connectSSE();
    }, delay);
  }

  private _disconnectSSE(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }
}

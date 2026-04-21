// services/sse.service.ts
import { Injectable, NgZone } from '@angular/core';
import { Observable, Observer } from 'rxjs';
import { SSEEvent } from '../models/user_story.model';

@Injectable({
  providedIn: 'root'
})
export class SseService {
  private eventSources = new Map<string, EventSource>();
  private reconnectAttempts = new Map<string, number>();
  private readonly MAX_RECONNECT_ATTEMPTS = 3;
  private readonly RECONNECT_DELAY = 3000;

  constructor(private zone: NgZone) {}

  /**
   * Connecte à une version via SSE
   * @param url - URL du stream (ex: /versions/{version_id}/stream)
   * @param versionId - ID de la version
   */
  connectToVersion(url: string, versionId: string): Observable<SSEEvent> {
    return new Observable((observer: Observer<SSEEvent>) => {
      // Si une connexion existe déjà, la fermer
      if (this.eventSources.has(versionId)) {
        this.disconnect(versionId);
      }

      console.log(`[SSE] Connecting to version ${versionId}...`);
      
      const eventSource = new EventSource(url);
      this.eventSources.set(versionId, eventSource);
      this.reconnectAttempts.set(versionId, 0);

      // Gestion de l'ouverture
      eventSource.onopen = () => {
        this.zone.run(() => {
          console.log(`[SSE] Connected to version ${versionId}`);
          this.reconnectAttempts.set(versionId, 0);
        });
      };

      // Types d'événements à écouter (simplifiés pour versions)
      const eventTypes: string[] = ['processing', 'completed', 'failed', 'ping', 'phase', 'version_created'];

      // Ajouter les listeners pour chaque type d'événement
      eventTypes.forEach(eventType => {
        eventSource.addEventListener(eventType, (event: MessageEvent) => {
          this.zone.run(() => {
            try {
              const data = event.data ? JSON.parse(event.data) : {};

              console.log("[SSE RECEIVED]", eventType, data);
              
              // Si c'est un événement terminal, on peut fermer la connexion
              if (eventType === 'completed' || eventType === 'failed') {
                console.log(`[SSE] Terminal event ${eventType} for version ${versionId}`);
                observer.next({
                  type: eventType as any,
                  data: data,
                  timestamp: new Date().toISOString()
                });
                observer.complete();
                this.disconnect(versionId);
                return;
              }

              observer.next({
                type: eventType as any,
                data: data,
                timestamp: new Date().toISOString()
              });

            } catch (e) {
              console.error(`[SSE] Parse error for version ${versionId}:`, e);
            }
          });
        });
      });

      // Gestion des erreurs de connexion
      eventSource.onerror = (error) => {
        this.zone.run(() => {
          console.error(`[SSE] Error for version ${versionId}:`, error);
          
          const attempts = this.reconnectAttempts.get(versionId) || 0;
          
          if (eventSource.readyState === EventSource.CLOSED && 
              attempts < this.MAX_RECONNECT_ATTEMPTS) {
            
            const newAttempts = attempts + 1;
            this.reconnectAttempts.set(versionId, newAttempts);
            console.log(`[SSE] Reconnecting to version ${versionId} (attempt ${newAttempts}/${this.MAX_RECONNECT_ATTEMPTS})...`);
            
            setTimeout(() => {
              if (this.eventSources.has(versionId)) {
                this.disconnect(versionId);
                observer.error(new Error(`Connection lost, attempt ${newAttempts}/${this.MAX_RECONNECT_ATTEMPTS}`));
              }
            }, this.RECONNECT_DELAY);
            
          } else if (attempts >= this.MAX_RECONNECT_ATTEMPTS) {
            console.error(`[SSE] Max reconnect attempts reached for version ${versionId}`);
            observer.error(new Error('Max reconnect attempts reached'));
          }
        });
      };

      // Nettoyage
      return () => {
        this.disconnect(versionId);
      };
    });
  }

  /**
   * Connecte à un stream SSE générique avec des types d'événements personnalisés.
   * Terminal events: 'completed' et 'failed' ferment automatiquement la connexion.
   */
  connectToStream<T extends { type: string; data: any; timestamp: string }>(
    url: string,
    streamId: string,
    eventTypes: string[]
  ): Observable<T> {
    return new Observable((observer) => {
      if (this.eventSources.has(streamId)) {
        this.disconnect(streamId);
      }

      const eventSource = new EventSource(url);
      this.eventSources.set(streamId, eventSource);
      this.reconnectAttempts.set(streamId, 0);

      eventSource.onopen = () => {
        this.zone.run(() => {
          this.reconnectAttempts.set(streamId, 0);
        });
      };

      eventTypes.forEach(eventType => {
        eventSource.addEventListener(eventType, (event: MessageEvent) => {
          this.zone.run(() => {
            try {
              const data = event.data ? JSON.parse(event.data) : {};
              const sseEvent = { type: eventType, data, timestamp: new Date().toISOString() } as T;

              if (eventType === 'completed' || eventType === 'failed') {
                observer.next(sseEvent);
                observer.complete();
                this.disconnect(streamId);
                return;
              }

              observer.next(sseEvent);
            } catch (e) {
              console.error(`[SSE] Parse error for stream ${streamId}:`, e);
            }
          });
        });
      });

      eventSource.onerror = () => {
        this.zone.run(() => {
          observer.error(new Error(`SSE connection error for ${streamId}`));
          this.disconnect(streamId);
        });
      };

      return () => {
        this.disconnect(streamId);
      };
    });
  }

  /**
   * Vérifie si une connexion SSE existe pour une version
   */
  isConnected(versionId: string): boolean {
    const es = this.eventSources.get(versionId);
    return es !== undefined && es.readyState === EventSource.OPEN;
  }

  /**
   * Récupère l'état de la connexion
   */
  getConnectionState(versionId: string): number | null {
    const es = this.eventSources.get(versionId);
    return es ? es.readyState : null;
  }

  /**
   * Déconnecte une version spécifique
   */
  disconnect(versionId: string): void {
    const es = this.eventSources.get(versionId);
    if (es) {
      console.log(`[SSE] Disconnecting from version ${versionId}`);
      es.close();
      this.eventSources.delete(versionId);
      this.reconnectAttempts.delete(versionId);
    }
  }

  /**
   * Déconnecte toutes les versions
   */
  disconnectAll(): void {
    console.log(`[SSE] Disconnecting all (${this.eventSources.size} connections)`);
    this.eventSources.forEach((_, versionId) => {
      this.disconnect(versionId);
    });
    this.eventSources.clear();
    this.reconnectAttempts.clear();
  }

  /**
   * Récupère les statistiques des connexions
   */
  getStats(): { connected: number; total: number; details: any[] } {
    const details: any[] = [];
    let connected = 0;
    
    this.eventSources.forEach((es, versionId) => {
      const state = es.readyState;
      const stateName = state === EventSource.CONNECTING ? 'connecting' :
                        state === EventSource.OPEN ? 'open' :
                        state === EventSource.CLOSED ? 'closed' : 'unknown';
      
      if (state === EventSource.OPEN) connected++;
      
      details.push({
        versionId,
        state: stateName,
        readyState: state
      });
    });
    
    return {
      connected,
      total: this.eventSources.size,
      details
    };
  }
}
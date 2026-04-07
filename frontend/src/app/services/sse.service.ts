// services/sse.service.ts
import { Injectable, NgZone } from '@angular/core';
import { Observable, Observer, Subject, timer } from 'rxjs';
import { retryWhen, delay, take, tap, catchError } from 'rxjs/operators';
import { SSEEvent, SSEEventType } from '../models';

@Injectable({
  providedIn: 'root'
})
export class SseService {
  private eventSources = new Map<string, EventSource>();
  private reconnectAttempts = new Map<string, number>();
  private readonly MAX_RECONNECT_ATTEMPTS = 3;
  private readonly RECONNECT_DELAY = 3000;

  constructor(private zone: NgZone) {}

  connect(url: string, jobId: string): Observable<SSEEvent> {
    return new Observable((observer: Observer<SSEEvent>) => {
      // Si une connexion existe déjà, la fermer
      if (this.eventSources.has(jobId)) {
        this.disconnect(jobId);
      }

      console.log(`[SSE] Connecting to job ${jobId}...`);
      
      const eventSource = new EventSource(url);
      this.eventSources.set(jobId, eventSource);
      this.reconnectAttempts.set(jobId, 0);

      // Gestion de l'ouverture
      eventSource.onopen = () => {
        this.zone.run(() => {
          console.log(`[SSE] Connected to job ${jobId}`);
          this.reconnectAttempts.set(jobId, 0);
        });
      };

      // Types d'événements à écouter
      const eventTypes: string[] = [
        'analyzing',
        'refining',
        'evaluating',
        'completed',
        'failed',
        'ping'
      ];

      // Ajouter les listeners pour chaque type d'événement
      eventTypes.forEach(eventType => {
        eventSource.addEventListener(eventType, (event: MessageEvent) => {
          this.zone.run(() => {
            try {
              const data = event.data ? JSON.parse(event.data) : {};

              console.log("[SSE RECEIVED]", eventType, data);
              
              // Si c'est un événement terminal, on peut fermer la connexion
              if (eventType === 'completed' || eventType === 'failed') {
                console.log(`[SSE] Terminal event ${eventType} for job ${jobId}`);
                observer.next({
                  type: eventType,
                  data: data,
                  timestamp: new Date().toISOString()
                });
                observer.complete();
                this.disconnect(jobId);
                return;
              }

              observer.next({
                type: eventType as SSEEventType,
                data: data,
                timestamp: new Date().toISOString()
              });

            } catch (e) {
              console.error(`[SSE] Parse error for job ${jobId}:`, e);
            }
          });
        });
      });

      // Gestion des erreurs de connexion
      eventSource.onerror = (error) => {
        this.zone.run(() => {
          console.error(`[SSE] Error for job ${jobId}:`, error);
          
          const attempts = this.reconnectAttempts.get(jobId) || 0;
          
          // Si la connexion est fermée et qu'on n'a pas atteint le max de tentatives
          if (eventSource.readyState === EventSource.CLOSED && 
              attempts < this.MAX_RECONNECT_ATTEMPTS) {
            
            const newAttempts = attempts + 1;
            this.reconnectAttempts.set(jobId, newAttempts);
            console.log(`[SSE] Reconnecting to job ${jobId} (attempt ${newAttempts}/${this.MAX_RECONNECT_ATTEMPTS})...`);
            
            // Réessayer après un délai
            setTimeout(() => {
              if (this.eventSources.has(jobId)) {
                this.disconnect(jobId);
                // La reconnexion se fera via un nouveau subscribe
                // Pour cela, il faudrait émettre un événement de reconnexion
                observer.error(new Error(`Connection lost, attempt ${newAttempts}/${this.MAX_RECONNECT_ATTEMPTS}`));
              }
            }, this.RECONNECT_DELAY);
            
          } else if (attempts >= this.MAX_RECONNECT_ATTEMPTS) {
            console.error(`[SSE] Max reconnect attempts reached for job ${jobId}`);
            observer.error(new Error('Max reconnect attempts reached'));
          }
        });
      };

      // Nettoyage
      return () => {
        this.disconnect(jobId);
      };
    });
  }

  /**
   * Connecte avec retry automatique (utilise les opérateurs RxJS)
   */
  connectWithRetry(url: string, jobId: string): Observable<SSEEvent> {
    return this.connect(url, jobId).pipe(
      retryWhen(errors => 
        errors.pipe(
          tap(err => console.error(`[SSE] Error for ${jobId}, retrying...`, err)),
          delay(this.RECONNECT_DELAY),
          take(this.MAX_RECONNECT_ATTEMPTS)
        )
      ),
      catchError((err) => {
        console.error(`[SSE] Failed after ${this.MAX_RECONNECT_ATTEMPTS} attempts for ${jobId}`);
        throw err;
      })
    );
  }

  /**
   * Vérifie si une connexion SSE existe pour un job
   */
  isConnected(jobId: string): boolean {
    const es = this.eventSources.get(jobId);
    return es !== undefined && es.readyState === EventSource.OPEN;
  }

  /**
   * Récupère l'état de la connexion
   */
  getConnectionState(jobId: string): number | null {
    const es = this.eventSources.get(jobId);
    return es ? es.readyState : null;
  }


  disconnect(jobId: string): void {
    const es = this.eventSources.get(jobId);
    if (es) {
      console.log(`[SSE] Disconnecting from job ${jobId}`);
      es.close();
      this.eventSources.delete(jobId);
      this.reconnectAttempts.delete(jobId);
    }
  }

  disconnectAll(): void {
    console.log(`[SSE] Disconnecting all (${this.eventSources.size} connections)`);
    this.eventSources.forEach((_, jobId) => {
      this.disconnect(jobId);
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
    
    this.eventSources.forEach((es, jobId) => {
      const state = es.readyState;
      const stateName = state === EventSource.CONNECTING ? 'connecting' :
                        state === EventSource.OPEN ? 'open' :
                        state === EventSource.CLOSED ? 'closed' : 'unknown';
      
      if (state === EventSource.OPEN) connected++;
      
      details.push({
        jobId,
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
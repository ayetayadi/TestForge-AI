import { Injectable, NgZone } from '@angular/core';
import { Observable } from 'rxjs';
import { SSEEvent, SSEEventType } from '../models';

@Injectable({
  providedIn: 'root'
})
export class SseService {
  private eventSources = new Map<string, EventSource>();

  constructor(private zone: NgZone) {}

  connect(url: string, jobId: string): Observable<SSEEvent> {
    return new Observable(observer => {
      this.disconnect(jobId);

      const eventSource = new EventSource(url);
      this.eventSources.set(jobId, eventSource);

      const eventTypes: SSEEventType[] = [
        'job_started',
        'analysis_started',
        'analysis_completed',
        'refinement_started',
        'refinement_completed',
        'rescoring',
        'job_completed',
        'job_failed',
        'ping'
      ];

      eventTypes.forEach(eventType => {
        eventSource.addEventListener(eventType, (event: MessageEvent) => {
          this.zone.run(() => {
            try {
              const data = JSON.parse(event.data);

              observer.next({
                type: eventType,
                data: data,
                timestamp: new Date().toISOString()
              });

            } catch (e) {
              console.error('[SSE] Parse error:', e);
            }
          });
        });
      });

      eventSource.onerror = (error) => {
        this.zone.run(() => {
          console.error('[SSE] Error:', error);
          if (eventSource.readyState === EventSource.CLOSED) {
            observer.error(new Error('Connection closed'));
          }
        });
      };

      return () => this.disconnect(jobId);
    });
  }

  mapEventToPhase(event: SSEEventType, data: any): any {
    switch (event) {

      case 'analysis_started':
        return data.reanalysis ? 'reanalyzing' : 'analyzing';

      case 'analysis_completed':
        return 'scoring';

      case 'refinement_started':
        return 'improving';

      case 'refinement_completed':
        return 'improved';

      case 'rescoring':
        return 'rescoring';

      case 'job_completed':
        return 'completed';

      case 'job_failed':
        return 'failed';

      default:
        return 'queued';
    }
  }

  disconnect(jobId: string): void {
    const es = this.eventSources.get(jobId);
    if (es) {
      es.close();
      this.eventSources.delete(jobId);
    }
  }

  disconnectAll(): void {
    this.eventSources.forEach(es => es.close());
    this.eventSources.clear();
  }
}
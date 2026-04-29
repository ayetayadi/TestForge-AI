import { Injectable } from '@angular/core';
import { environment } from 'src/environments/environment';
import { AuthService } from './auth.service';

export type TastyEventType = 'token' | 'tool_start' | 'tool_end' | 'done' | 'error';

export interface TastyEvent {
  type: TastyEventType;
  content?: string;
  tool?: string;
  input?: string;
}

export interface TastyCallbacks {
  onToken: (token: string) => void;
  onToolStart: (tool: string, input: string) => void;
  onToolEnd: (tool: string) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

@Injectable({ providedIn: 'root' })
export class TastyService {
  private readonly apiUrl = environment.apiUrl;
  private currentController: AbortController | null = null;

  constructor(private authService: AuthService) {}

  async sendMessage(
    message: string,
    callbacks: TastyCallbacks,
    context?: Record<string, unknown>
  ): Promise<void> {
    // Cancel any in-flight request
    this.abort();

    const controller = new AbortController();
    this.currentController = controller;

    const token = this.authService.getAccessToken();
    let response: Response;

    try {
      response = await fetch(`${this.apiUrl}/chatbot/message`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ message, context }),
        signal: controller.signal,
      });
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        callbacks.onError('Failed to connect to Tasty. Please try again.');
      }
      return;
    }

    if (!response.ok) {
      callbacks.onError(`Request failed (${response.status}). Please try again.`);
      return;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      callbacks.onError('No response stream available.');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const raw = line.slice(6).trim();
          if (!raw) continue;

          try {
            const event: TastyEvent = JSON.parse(raw);
            switch (event.type) {
              case 'token':
                if (event.content) callbacks.onToken(event.content);
                break;
              case 'tool_start':
                callbacks.onToolStart(event.tool ?? '', event.input ?? '');
                break;
              case 'tool_end':
                callbacks.onToolEnd(event.tool ?? '');
                break;
              case 'done':
                callbacks.onDone();
                break;
              case 'error':
                callbacks.onError(event.content ?? 'An unknown error occurred.');
                break;
            }
          } catch {
            // Ignore malformed SSE lines
          }
        }
      }
    } catch (err: any) {
      if (err?.name !== 'AbortError') {
        callbacks.onError('Connection interrupted. Please try again.');
      }
    } finally {
      reader.releaseLock();
      this.currentController = null;
    }
  }

  abort(): void {
    this.currentController?.abort();
    this.currentController = null;
  }

  readonly suggestions = [
    'Show my projects',
    'What are my test stats?',
    'Search for login test cases',
    'How do I write a good user story?',
  ];
}

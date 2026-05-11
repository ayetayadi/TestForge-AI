import {
  Component,
  ElementRef,
  NgZone,
  OnDestroy,
  ViewChild,
  AfterViewChecked,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';

import { TastyService } from 'src/app/services/tasty.service';
import { marked } from 'marked';
import DOMPurify from 'dompurify';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  isStreaming: boolean;
  toolCalls: { tool: string; status: 'running' | 'done' }[];
  timestamp: Date;
  error?: boolean;
}

@Component({
  selector: 'app-tasty',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatButtonModule,
    MatIconModule,
    MatTooltipModule,
  ],
  templateUrl: './tasty.component.html',
  styleUrls: ['./tasty.component.scss'],
})
export class TastyComponent implements OnDestroy, AfterViewChecked {
  @ViewChild('messagesEnd') messagesEnd!: ElementRef;
  @ViewChild('inputRef') inputRef!: ElementRef<HTMLTextAreaElement>;

  isOpen = false;
  isLoading = false;
  inputText = '';
  messages: ChatMessage[] = [];
  suggestions = this.tastyService.suggestions;

  private shouldScrollToBottom = false;

  constructor(
    private tastyService: TastyService,
    private zone: NgZone
  ) {}

  ngAfterViewChecked(): void {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  ngOnDestroy(): void {
    this.tastyService.abort();
  }

  togglePanel(): void {
    this.isOpen = !this.isOpen;
    if (this.isOpen && this.messages.length === 0) {
      this.addWelcome();
    }
    if (this.isOpen) {
      setTimeout(() => this.inputRef?.nativeElement?.focus(), 150);
      this.shouldScrollToBottom = true;
    }
  }

  async send(text?: string): Promise<void> {
    const message = (text ?? this.inputText).trim();
    if (!message || this.isLoading) return;

    this.inputText = '';
    this.isLoading = true;

    this.addMessage('user', message);

    const assistantMsg = this.addMessage('assistant', '');
    assistantMsg.isStreaming = true;

    await this.tastyService.sendMessage(message, {
      onToken: (token) =>
        this.zone.run(() => {
          assistantMsg.content += token;
          this.shouldScrollToBottom = true;
        }),
      onToolStart: (tool, _input) =>
        this.zone.run(() => {
          assistantMsg.toolCalls.push({ tool, status: 'running' });
          this.shouldScrollToBottom = true;
        }),
      onToolEnd: (tool) =>
        this.zone.run(() => {
          const call = assistantMsg.toolCalls.find(
            (c) => c.tool === tool && c.status === 'running'
          );
          if (call) call.status = 'done';
        }),
      onDone: () =>
        this.zone.run(() => {
          assistantMsg.isStreaming = false;
          this.isLoading = false;
          this.shouldScrollToBottom = true;
        }),
      onError: (err) =>
        this.zone.run(() => {
          if (!assistantMsg.content) {
            assistantMsg.content = err;
            assistantMsg.error = true;
          }
          assistantMsg.isStreaming = false;
          this.isLoading = false;
        }),
    });
  }

  onKeyDown(event: KeyboardEvent): void {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      this.send();
    }
  }

  clearChat(): void {
    this.messages = [];
    this.addWelcome();
  }

  renderMarkdown(content: string): string {
    if (!content) return '';
    const html = marked.parse(content, { async: false }) as string;
    return DOMPurify.sanitize(html);
  }

  toolLabel(tool: string): string {
    const labels: Record<string, string> = {
      get_projects: 'Fetching projects',
      get_user_stories: 'Fetching user stories',
      get_test_cases: 'Fetching test cases',
      get_test_stats: 'Loading stats',
      search_test_cases: 'Searching test cases',
      get_test_suites: 'Fetching test suites',
      get_suite_results: 'Loading execution results',
      generate_test_cases: 'Generating test cases',
      refine_user_story: 'Refining user story',
      generate_playwright_script: 'Generating Playwright script',
      execute_playwright_script: 'Executing script',
      run_test_suite: 'Running test suite',
    };
    return labels[tool] ?? tool.replace(/_/g, ' ');
  }

  private addWelcome(): void {
    this.addMessage(
      'assistant',
      "Hi! I'm **Tasty**, your AI Testing Assistant. Here's what I can do:\n\n" +
      "**Query** — projects, user stories, test cases, test suites, execution results, stats\n" +
      "**Generate** — test cases, Playwright scripts\n" +
      "**Execute** — run a single script or an entire test suite against your app\n" +
      "**Refine** — improve user stories with the AI pipeline\n\n" +
      "What would you like to do?"
    );
  }

  private addMessage(role: ChatMessage['role'], content: string): ChatMessage {
    const msg: ChatMessage = {
      id: crypto.randomUUID(),
      role,
      content,
      isStreaming: false,
      toolCalls: [],
      timestamp: new Date(),
    };
    this.messages.push(msg);
    this.shouldScrollToBottom = true;
    return msg;
  }

  private scrollToBottom(): void {
    try {
      this.messagesEnd?.nativeElement?.scrollIntoView({ behavior: 'smooth' });
    } catch {}
  }
}

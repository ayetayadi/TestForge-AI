import { Component, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { TestomatService, TestomatStatus } from '../../services/testomat.service';
import { ToastService } from '../../services/toast.service';
import { ConfirmDialogComponent } from '../../components/confirm-dialog/confirm-dialog.component';

@Component({
  selector: 'app-testomat',
  standalone: true,
  imports: [CommonModule, FormsModule, ConfirmDialogComponent],
  templateUrl: './testomat.component.html',
  styleUrl: './testomat.component.scss',
})
export class TestomatComponent implements OnInit {
  status = signal<TestomatStatus>({ connected: false });
  apiKeyInput = signal('');
  showKey = signal(false);

  connecting  = signal(false);
  disconnecting = signal(false);

  showConfirmDialog = signal(false);
  confirmDialogData = signal<{
    title: string; message: string; icon: string;
    confirmText: string; cancelText: string;
    variant: 'primary' | 'danger' | 'warning' | 'success';
    onConfirm: () => void;
  }>({
    title: '', message: '', icon: '⚠️',
    confirmText: 'Confirm', cancelText: 'Cancel',
    variant: 'warning', onConfirm: () => {},
  });

  constructor(
    private testomatService: TestomatService,
    private toast: ToastService,
  ) {}

  ngOnInit(): void {
    this.testomatService.getStatus().subscribe({
      next: s => this.status.set(s),
      error: () => {},
    });
  }

  connect(): void {
    const key = this.apiKeyInput().trim();
    if (!key) {
      this.toast.error('API key required', 'Please enter your Testomat.io API key');
      return;
    }
    this.connecting.set(true);
    this.testomatService.connect(key).subscribe({
      next: s => {
        this.status.set(s);
        this.apiKeyInput.set('');
        this.connecting.set(false);
        this.toast.success('Connected', 'Testomat.io connected successfully');
      },
      error: err => {
        this.connecting.set(false);
        this.toast.error('Connection failed', err?.error?.detail || 'Invalid API key');
      },
    });
  }

  disconnect(): void {
    this.confirmDialogData.set({
      title: 'Disconnect Testomat',
      message: 'Remove your Testomat.io connection? You can reconnect at any time.',
      icon: '🔌',
      confirmText: 'Disconnect',
      cancelText: 'Cancel',
      variant: 'warning',
      onConfirm: () => {
        this.disconnecting.set(true);
        this.testomatService.disconnect().subscribe({
          next: () => {
            this.status.set({ connected: false });
            this.disconnecting.set(false);
            this.toast.success('Disconnected', 'Testomat.io disconnected');
          },
          error: () => {
            this.disconnecting.set(false);
            this.toast.error('Error', 'Failed to disconnect');
          },
        });
      },
    });
    this.showConfirmDialog.set(true);
  }

  toggleShowKey(): void {
    this.showKey.update(v => !v);
  }
}

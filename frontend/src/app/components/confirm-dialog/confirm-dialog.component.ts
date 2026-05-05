import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="modal-overlay" *ngIf="visible" (click)="onCancel()">
      <div class="modal-container" (click)="$event.stopPropagation()">
        <!-- Close button -->
        <button class="modal-close" (click)="onCancel()" title="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="18" height="18">
            <path d="M18 6L6 18M6 6l12 12"/>
          </svg>
        </button>

        <!-- Icon + Title -->
        <div class="modal-header">
          <div class="modal-icon-wrap">
            <span class="modal-icon">{{ icon }}</span>
          </div>
          <h3 class="modal-title">{{ title }}</h3>
          <p class="modal-message">{{ message }}</p>
        </div>

        <!-- Footer buttons -->
        <div class="modal-footer">
          <button class="btn btn-cancel" (click)="onCancel()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
            {{ cancelText }}
          </button>
          <button class="btn btn-confirm btn-confirm--{{ variant }}" (click)="onConfirm()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15">
              <path d="M5 13l4 4L19 7"/>
            </svg>
            {{ confirmText }}
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [`
    /* ============================================================
       OVERLAY
    ============================================================ */
    .modal-overlay {
      position: fixed;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      background: rgba(0, 0, 0, 0.45);
      backdrop-filter: blur(4px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      animation: fadeIn 0.2s ease;
      padding: 16px;
    }

    @keyframes fadeIn {
      from { opacity: 0; }
      to   { opacity: 1; }
    }

    /* ============================================================
       CONTAINER
    ============================================================ */
    .modal-container {
      background: #ffffff;
      border-radius: 16px;
      padding: 32px 28px 24px;
      max-width: 440px;
      width: 100%;
      box-shadow:
        0 20px 60px rgba(0, 0, 0, 0.15),
        0 0 0 1px rgba(0, 0, 0, 0.05);
      position: relative;
      animation: slideUp 0.25s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    }

    @keyframes slideUp {
      from { transform: translateY(24px); opacity: 0; }
      to   { transform: translateY(0);    opacity: 1; }
    }

    /* ============================================================
       CLOSE BUTTON
    ============================================================ */
    .modal-close {
      position: absolute;
      top: 12px;
      right: 12px;
      width: 32px;
      height: 32px;
      border-radius: 8px;
      border: none;
      background: transparent;
      color: #9ca3af;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: all 0.15s ease;
    }

    .modal-close:hover {
      background: #f3f4f6;
      color: #374151;
    }

    /* ============================================================
       HEADER
    ============================================================ */
    .modal-header {
      text-align: center;
      margin-bottom: 28px;
    }

    .modal-icon-wrap {
      width: 56px;
      height: 56px;
      border-radius: 14px;
      background: #eef2ff;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 16px;
    }

    .modal-icon {
      font-size: 28px;
      line-height: 1;
    }

    .modal-title {
      font-size: 18px;
      font-weight: 700;
      color: #111827;
      margin: 0 0 8px;
      letter-spacing: -0.01em;
    }

    .modal-message {
      font-size: 14px;
      color: #6b7280;
      line-height: 1.6;
      margin: 0;
      white-space: pre-wrap;
    }

    /* ============================================================
       FOOTER
    ============================================================ */
    .modal-footer {
      display: flex;
      gap: 10px;
      justify-content: flex-end;
    }

    /* ============================================================
       BUTTONS — Base
    ============================================================ */
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 10px 18px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
      border: none;
      outline: none;
      letter-spacing: -0.005em;
    }

    .btn:active {
      transform: scale(0.97);
    }

    /* ============================================================
       CANCEL BUTTON
    ============================================================ */
    .btn-cancel {
      background: #f3f4f6;
      color: #374151;
    }

    .btn-cancel:hover {
      background: #e5e7eb;
    }

    /* ============================================================
       CONFIRM BUTTON — Variants
    ============================================================ */
    .btn-confirm {
      color: #ffffff;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
    }

    /* Default / Primary */
    .btn-confirm--primary,
    .btn-confirm--default {
      background: #6366f1;
    }
    .btn-confirm--primary:hover,
    .btn-confirm--default:hover {
      background: #4f46e5;
    }

    /* Danger / Delete */
    .btn-confirm--danger {
      background: #dc2626;
    }
    .btn-confirm--danger:hover {
      background: #b91c1c;
    }

    /* Warning */
    .btn-confirm--warning {
      background: #ea580c;
    }
    .btn-confirm--warning:hover {
      background: #c2410c;
    }

    /* Success */
    .btn-confirm--success {
      background: #059669;
    }
    .btn-confirm--success:hover {
      background: #047857;
    }

    /* ============================================================
       RESPONSIVE
    ============================================================ */
    @media (max-width: 480px) {
      .modal-container {
        padding: 24px 20px 20px;
      }
      .modal-footer {
        flex-direction: column-reverse;
      }
      .btn {
        justify-content: center;
        width: 100%;
      }
    }
  `]
})
export class ConfirmDialogComponent {
  @Input() visible = false;
  @Input() title = 'Confirmation';
  @Input() message = '';
  @Input() icon = '📊';
  @Input() confirmText = 'Continue';
  @Input() cancelText = 'Cancel';
  @Input() variant: 'primary' | 'danger' | 'warning' | 'success' = 'primary';
  
  @Output() confirmed = new EventEmitter<void>();
  @Output() cancelled = new EventEmitter<void>();

  onConfirm() { 
    this.confirmed.emit(); 
    this.visible = false; 
  }
  
  onCancel() { 
    this.cancelled.emit(); 
    this.visible = false; 
  }
}
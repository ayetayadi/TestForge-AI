// services/toast.service.ts
import { Injectable, signal } from '@angular/core';

export interface Toast {
  id: string;
  type: 'success' | 'error' | 'warning' | 'info';
  title: string;
  message?: string;
  duration?: number;
}

@Injectable({
  providedIn: 'root'
})
export class ToastService {
  private toasts = signal<Toast[]>([]);
  
  // Exposer les toasts comme readonly
  readonly toasts$ = this.toasts.asReadonly();

  show(toast: Omit<Toast, 'id'>): void {
    const id = Date.now().toString();
    const newToast = { ...toast, id, duration: toast.duration || 5000 };
    
    this.toasts.update(current => [...current, newToast]);
    
    // Auto-supprimer après la durée
    setTimeout(() => {
      this.dismiss(id);
    }, newToast.duration);
  }

  success(title: string, message?: string): void {
    this.show({ type: 'success', title, message });
  }

  error(title: string, message?: string): void {
    this.show({ type: 'error', title, message });
  }

  warning(title: string, message?: string): void {
    this.show({ type: 'warning', title, message });
  }

  info(title: string, message?: string): void {
    this.show({ type: 'info', title, message });
  }

  dismiss(id: string): void {
    this.toasts.update(current => current.filter(t => t.id !== id));
  }

  clear(): void {
    this.toasts.set([]);
  }
}
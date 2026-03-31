import { Injectable, signal } from '@angular/core';
import { Toast } from '../models';

@Injectable({
  providedIn: 'root'
})
export class ToastService {
  toasts = signal<Toast[]>([]);

  private show(type: Toast['type'], title: string, message?: string): string {
    const id = crypto.randomUUID();
    const toast: Toast = { id, type, title, message };
    
    this.toasts.update(t => [...t, toast]);
    
    setTimeout(() => this.dismiss(id), 5000);
    
    return id;
  }

  success(title: string, message?: string) {
    return this.show('success', title, message);
  }

  error(title: string, message?: string) {
    return this.show('error', title, message);
  }

  warning(title: string, message?: string) {
    return this.show('warning', title, message);
  }

  info(title: string, message?: string) {
    return this.show('info', title, message);
  }

  dismiss(id: string) {
    this.toasts.update(t => t.filter(toast => toast.id !== id));
  }
}
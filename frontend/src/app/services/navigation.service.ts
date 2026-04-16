// services/navigation.service.ts
import { Injectable } from '@angular/core';

@Injectable({
  providedIn: 'root'
})
export class NavigationService {
  private currentPage = 1;

  setCurrentPage(page: number): void {
    this.currentPage = page;
  }

  getCurrentPage(): number {
    return this.currentPage;
  }
}
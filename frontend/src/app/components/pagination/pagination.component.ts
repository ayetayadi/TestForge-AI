import { Component, input, output, computed, signal, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-pagination',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './pagination.component.html',
  styleUrl: './pagination.component.scss',
})
export class PaginationComponent implements OnInit {

  /** Total number of items */
  totalItems = input.required<number>();

  /** Items per page */
  pageSize = input<number>(10);

  /** Current page (1-based) */
  currentPage = input<number>(1);

  /** Maximum visible page buttons */
  maxVisiblePages = input<number>(5);

  /** Show page size selector */
  showPageSizeSelector = input<boolean>(true);

  /** Available page sizes */
  pageSizeOptions = input<number[]>([10, 15, 20, 25, 50, 100]);

  /** Outputs */
  pageChange = output<number>();
  pageSizeChange = output<number>();

  // =========================
  // LIFECYCLE
  // =========================
  ngOnInit(): void {
    // Ensure current pageSize exists in options
    if (!this.pageSizeOptions().includes(this.pageSize())) {
      this.pageSizeChange.emit(this.pageSizeOptions()[0]);
    }
  }

  // =========================
  // COMPUTED
  // =========================

  totalPages = computed(() =>
    Math.max(1, Math.ceil(this.totalItems() / this.pageSize()))
  );

  rangeLabel = computed(() => {
    const total = this.totalItems();
    if (total === 0) return '0 items';

    const start = (this.currentPage() - 1) * this.pageSize() + 1;
    const end = Math.min(this.currentPage() * this.pageSize(), total);

    return `${start}–${end} of ${total}`;
  });

  pages = computed<(number | '...')[]>(() => {
    const total = this.totalPages();
    const current = this.currentPage();
    const max = this.maxVisiblePages();

    if (total <= max + 2) {
      return Array.from({ length: total }, (_, i) => i + 1);
    }

    const pages: (number | '...')[] = [];
    const half = Math.floor(max / 2);

    let start = Math.max(2, current - half);
    let end = Math.min(total - 1, current + half);

    if (current - half < 2) {
      end = Math.min(total - 1, max + 1);
    }

    if (current + half > total - 1) {
      start = Math.max(2, total - max);
    }

    pages.push(1);

    if (start > 2) pages.push('...');

    for (let i = start; i <= end; i++) {
      pages.push(i);
    }

    if (end < total - 1) pages.push('...');

    if (total > 1) pages.push(total);

    return pages;
  });

  isFirstPage = computed(() => this.currentPage() <= 1);
  isLastPage = computed(() => this.currentPage() >= this.totalPages());

  // =========================
  // ACTIONS
  // =========================

  goToPage(page: number | '...'): void {
    if (page === '...') return;

    const clamped = Math.max(1, Math.min(page, this.totalPages()));

    if (clamped !== this.currentPage()) {
      this.pageChange.emit(clamped);
    }
  }

  prev(): void {
    if (!this.isFirstPage()) {
      this.pageChange.emit(this.currentPage() - 1);
    }
  }

  next(): void {
    if (!this.isLastPage()) {
      this.pageChange.emit(this.currentPage() + 1);
    }
  }

  onPageSizeChange(event: Event): void {
    const value = +(event.target as HTMLSelectElement).value;

    this.pageSizeChange.emit(value);
    this.pageChange.emit(1);
  }
}
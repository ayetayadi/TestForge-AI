import { Component, input, output, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface FilterOption {
  /** Unique value passed back on selection */
  value: string;
  /** Display label */
  label: string;
  /** Optional count badge */
  count?: number;
  /** Optional icon (SVG path d attribute for a 20x20 viewBox) */
  icon?: string;
}

export interface FilterGroup {
  /** Unique key for this filter group */
  key: string;
  /** Display label */
  label: string;
  /** Available options */
  options: FilterOption[];
  /** Allow multiple selection */
  multiple?: boolean;
}

export interface ActiveFilters {
  [groupKey: string]: string[];
}

@Component({
  selector: 'app-filter-bar',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './filter-bar.component.html',
  styleUrl: './filter-bar.component.scss',
})
export class FilterBarComponent {
  /** Filter groups to render */
  groups = input.required<FilterGroup[]>();

  /** Currently active filters */
  activeFilters = input<ActiveFilters>({});

  /** Emitted whenever any filter changes */
  filtersChange = output<ActiveFilters>();

  /** Track which dropdown is open */
  openDropdown = signal<string | null>(null);

  /** Total active filter count */
  activeCount = computed(() => {
    const filters = this.activeFilters();
    return Object.values(filters).reduce((sum, arr) => sum + arr.length, 0);
  });

  isActive(groupKey: string, value: string): boolean {
    const filters = this.activeFilters();
    return filters[groupKey]?.includes(value) ?? false;
  }

  getGroupLabel(group: FilterGroup): string {
    const active = this.activeFilters()[group.key];
    if (!active || active.length === 0) return group.label;
    if (active.length === 1) {
      const opt = group.options.find((o) => o.value === active[0]);
      return opt?.label ?? group.label;
    }
    return `${group.label} (${active.length})`;
  }

  toggleDropdown(key: string): void {
    this.openDropdown.update((current) => (current === key ? null : key));
  }

  closeDropdowns(): void {
    this.openDropdown.set(null);
  }

  selectOption(group: FilterGroup, value: string): void {
    const current = { ...this.activeFilters() };
    const groupValues = [...(current[group.key] || [])];

    if (group.multiple) {
      const idx = groupValues.indexOf(value);
      if (idx >= 0) {
        groupValues.splice(idx, 1);
      } else {
        groupValues.push(value);
      }
    } else {
      // Single-select: toggle off if already selected, else set
      if (groupValues.includes(value)) {
        groupValues.length = 0;
      } else {
        groupValues.length = 0;
        groupValues.push(value);
      }
      this.openDropdown.set(null);
    }

    if (groupValues.length > 0) {
      current[group.key] = groupValues;
    } else {
      delete current[group.key];
    }

    this.filtersChange.emit(current);
  }

  clearGroup(groupKey: string, event: Event): void {
    event.stopPropagation();
    const current = { ...this.activeFilters() };
    delete current[groupKey];
    this.filtersChange.emit(current);
  }

  clearAll(): void {
    this.filtersChange.emit({});
    this.openDropdown.set(null);
  }
}
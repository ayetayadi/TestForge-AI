import {
  Component,
  input,
  output,
  signal,
  OnInit,
  OnDestroy,
  ElementRef,
  ViewChild,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Subject, Subscription, debounceTime, distinctUntilChanged } from 'rxjs';

@Component({
  selector: 'app-search-bar',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './search-bar.component.html',
  styleUrl: './search-bar.component.scss',
})
export class SearchBarComponent implements OnInit, OnDestroy {
  /** Placeholder text */
  placeholder = input<string>('Search...');

  /** Debounce time in ms (0 = no debounce) */
  debounce = input<number>(300);

  /** Initial value */
  value = input<string>('');

  /** Emitted on every (debounced) change */
  searchChange = output<string>();

  /** Emitted when the user presses Enter */
  searchSubmit = output<string>();

  @ViewChild('searchInput') searchInput!: ElementRef<HTMLInputElement>;

  query = signal('');
  focused = signal(false);

  private input$ = new Subject<string>();
  private sub!: Subscription;

  ngOnInit(): void {
    this.query.set(this.value());

    this.sub = this.input$
      .pipe(debounceTime(this.debounce()), distinctUntilChanged())
      .subscribe((q) => this.searchChange.emit(q));
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  onInput(event: Event): void {
    const val = (event.target as HTMLInputElement).value;
    this.query.set(val);
    this.input$.next(val);
  }

  onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Enter') {
      this.searchSubmit.emit(this.query());
    }
    if (event.key === 'Escape') {
      this.clear();
      this.searchInput.nativeElement.blur();
    }
  }

  clear(): void {
    this.query.set('');
    this.input$.next('');
    this.searchChange.emit('');
    this.searchInput.nativeElement.focus();
  }

  focus(): void {
    this.searchInput.nativeElement.focus();
  }
}
import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { ToastContainerComponent } from './shared/toast-container/toast-container.component';
import { TastyComponent } from './components/tasty/tasty.component';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet, ToastContainerComponent, TastyComponent],
  templateUrl: './app.component.html'
})
export class AppComponent {
  title = 'TestForge AI';
}
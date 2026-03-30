import { Component } from '@angular/core';
import { CoreService } from 'src/app/services/core.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-branding',
  standalone: true,
  template: `
    <a (click)="goToDashboard()" style="display:block; text-align:center; cursor:pointer;">
      <img
        src="./assets/images/logos/logo.png"
        alt="TestForge"
        style="
          width: 120%;
          max-width: 200px;
          min-width: 100px;
          height: auto;
          object-fit: contain;
          display: block;
          margin: -12px auto 0 auto;
        "
      />
    </a>
  `,
})
export class BrandingComponent {
  options = this.settings.getOptions();

  constructor(private settings: CoreService, private router: Router) {}

  goToDashboard() {
    const isAdmin = localStorage.getItem('is_admin') === 'true';

    if (isAdmin) {
      this.router.navigate(['/admin-dashboard']);
    } else {
      this.router.navigate(['/user-dashboard']);
    }
  }
}

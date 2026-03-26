import { Component } from '@angular/core';
import { CoreService } from 'src/app/services/core.service';
import { RouterModule } from '@angular/router';

@Component({
  selector: 'app-branding',
  imports: [RouterModule],
  template: `
    <a [routerLink]="['/dashboard']" style="display:block; text-align:center;">
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
  constructor(private settings: CoreService) {}
}

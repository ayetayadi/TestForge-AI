import {
  Component,
  Output,
  EventEmitter,
  Input,
  ViewEncapsulation,
  OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { TablerIconsModule } from 'angular-tabler-icons';
import { MaterialModule } from 'src/app/material.module';
import { RouterModule } from '@angular/router';
import { NgScrollbarModule } from 'ngx-scrollbar';
import { MatBadgeModule } from '@angular/material/badge';
import { AuthService, UserRead } from 'src/app/services/auth.service';
import { UserService } from 'src/app/services/user.service';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    NgScrollbarModule,
    TablerIconsModule,
    MaterialModule,
    MatBadgeModule,
  ],
  templateUrl: './header.component.html',
  encapsulation: ViewEncapsulation.None,
})
export class HeaderComponent implements OnInit {
  @Input() showToggle = true;
  @Input() toggleChecked = false;
  @Output() toggleMobileNav = new EventEmitter<void>();

  username = '';
  role = '';
  loadingProfile = false;

  constructor(private authService: AuthService, private userService: UserService) {}

  ngOnInit(): void {
    this.loadCurrentUser();
  }

  loadCurrentUser(): void {
    this.loadingProfile = true;

    this.userService.getMyProfile().subscribe({
      next: (user: UserRead) => {
        this.username = user.username;
        this.role = user.is_admin ? 'Admin' : 'User';
        this.loadingProfile = false;
      },
      error: (err) => {
        console.error('Failed to load current user', err);
        this.loadingProfile = false;
      }
    });
  }

  logout(): void {
    this.authService.logout();
  }
}

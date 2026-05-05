import {
  Component,
  Output,
  EventEmitter,
  Input,
  OnInit,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { RouterModule } from '@angular/router';
import { AuthService, UserRead } from 'src/app/services/auth.service';
import { UserService } from 'src/app/services/user.service';
import { NotificationBellComponent } from 'src/app/shared/notification-bell/notification-bell.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterModule, MaterialModule, NotificationBellComponent],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss'],
})
export class HeaderComponent implements OnInit {
  @Input() isSidebarCollapsed = false;
  @Output() toggleSidebar = new EventEmitter<void>();

  username = '';
  role = '';

  constructor(
    private authService: AuthService, 
    private userService: UserService
  ) {}

  ngOnInit(): void {
    this.loadCurrentUser();
  }

  loadCurrentUser(): void {
    this.userService.getMyProfile().subscribe({
      next: (user: UserRead) => {
        this.username = user.username;
        this.role = user.is_admin ? 'Admin' : 'User';
      },
      error: (err) => {
        console.error('Failed to load current user', err);
      }
    });
  }

  getInitials(): string {
    if (!this.username) return 'U';
    return this.username.charAt(0).toUpperCase();
  }

  logout(): void {
    this.authService.logout();
  }
}
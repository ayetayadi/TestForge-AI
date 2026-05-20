import {
  Component,
  Output,
  EventEmitter,
  Input,
  OnInit,
  OnDestroy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { RouterModule } from '@angular/router';
import { Subscription } from 'rxjs';
import { AuthService } from 'src/app/services/auth.service';
import { UserService } from 'src/app/services/user.service';
import { NotificationBellComponent } from 'src/app/shared/notification-bell/notification-bell.component';

@Component({
  selector: 'app-header',
  standalone: true,
  imports: [CommonModule, RouterModule, MaterialModule, NotificationBellComponent],
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss'],
})
export class HeaderComponent implements OnInit, OnDestroy {
  @Input() isSidebarCollapsed = false;
  @Output() toggleSidebar = new EventEmitter<void>();

  username = '';
  role = '';

  private sub = new Subscription();

  constructor(
    private authService: AuthService,
    private userService: UserService
  ) {}

  ngOnInit(): void {
    this.sub.add(
      this.userService.profile$.subscribe(profile => {
        if (profile) {
          this.username = profile.username;
          this.role = profile.is_admin ? 'Admin' : 'Tester';
        }
      })
    );
    if (!this.userService.currentProfile) {
      this.userService.getMyProfile().subscribe();
    }
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
  }

  getInitials(): string {
    if (!this.username) return 'U';
    return this.username.charAt(0).toUpperCase();
  }

  logout(): void {
    this.authService.logout();
  }
}
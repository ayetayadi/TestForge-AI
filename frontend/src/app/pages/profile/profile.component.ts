import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MaterialModule } from 'src/app/material.module';
import { UserService, ProfileRead } from '../../services/user.service';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, MaterialModule, RouterModule],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss'
})
export class ProfileComponent implements OnInit {
  user: ProfileRead | null = null;
  loading = true;
  errorMessage = '';

  constructor(private userService: UserService) {}

  ngOnInit(): void {
    this.loadProfile();
  }

  loadProfile(): void {
    this.loading = true;
    this.errorMessage = '';
    
    this.userService.getMyProfile().subscribe({
      next: (data) => {
        this.user = data;
        this.loading = false;
      },
      error: (error) => {
        console.error(error);
        this.errorMessage = 'Failed to load profile';
        this.loading = false;
      }
    });
  }

  getInitials(): string {
    if (!this.user) return 'U';
    return this.user.username.charAt(0).toUpperCase();
  }

  formatDate(dateString: string): string {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric'
    });
  }

  editProfile(): void {
    // Navigate to edit profile page
    // this.router.navigate(['/profile/edit']);
  }

  changePassword(): void {
    // Navigate to change password page
    // this.router.navigate(['/profile/change-password']);
  }
}
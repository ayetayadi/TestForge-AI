import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { MaterialModule } from 'src/app/material.module';
import { UserService, ProfileRead } from '../../services/user.service';

@Component({
  selector: 'app-profile',
  standalone: true,
  imports: [CommonModule, MaterialModule, RouterModule, FormsModule],
  templateUrl: './profile.component.html',
  styleUrl: './profile.component.scss'
})
export class ProfileComponent implements OnInit {
  user: ProfileRead | null = null;
  loading = true;
  errorMessage = '';

  // Edit Profile modal
  showEditModal = false;
  editUsername = '';
  editEmail = '';
  editSubmitting = false;
  editError = '';
  editSuccess = '';

  // Change Password modal
  showPasswordModal = false;
  currentPassword = '';
  newPassword = '';
  confirmPassword = '';
  passwordSubmitting = false;
  passwordError = '';
  passwordSuccess = '';
  showCurrentPwd = false;
  showNewPwd = false;
  showConfirmPwd = false;

  constructor(private userService: UserService) {}

  ngOnInit(): void {
    this.loadProfile();
  }

  loadProfile(): void {
    this.loading = true;
    this.errorMessage = '';
    this.userService.getMyProfile().subscribe({
      next: (data) => { this.user = data; this.loading = false; },
      error: () => { this.errorMessage = 'Failed to load profile'; this.loading = false; }
    });
  }

  getInitials(): string {
    if (!this.user) return 'U';
    return this.user.username.charAt(0).toUpperCase();
  }

  formatDate(dateString: string): string {
    if (!dateString) return 'N/A';
    return new Date(dateString).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  }

  // ── Edit Profile ──────────────────────────────────────────────
  editProfile(): void {
    if (!this.user) return;
    this.editUsername = this.user.username;
    this.editEmail = this.user.email;
    this.editError = '';
    this.editSuccess = '';
    this.showEditModal = true;
  }

  closeEditModal(): void {
    this.showEditModal = false;
  }

  submitEditProfile(): void {
    if (!this.editUsername.trim() || !this.editEmail.trim()) {
      this.editError = 'All fields are required.';
      return;
    }
    this.editSubmitting = true;
    this.editError = '';
    this.userService.updateProfile({ username: this.editUsername.trim(), email: this.editEmail.trim() }).subscribe({
      next: (updated) => {
        this.user = updated;
        this.editSuccess = 'Profile updated successfully.';
        this.editSubmitting = false;
        setTimeout(() => { this.showEditModal = false; this.editSuccess = ''; }, 1200);
      },
      error: (err) => {
        this.editError = err?.error?.detail || 'Failed to update profile.';
        this.editSubmitting = false;
      }
    });
  }

  // ── Change Password ───────────────────────────────────────────
  changePassword(): void {
    this.currentPassword = '';
    this.newPassword = '';
    this.confirmPassword = '';
    this.passwordError = '';
    this.passwordSuccess = '';
    this.showCurrentPwd = false;
    this.showNewPwd = false;
    this.showConfirmPwd = false;
    this.showPasswordModal = true;
  }

  closePasswordModal(): void {
    this.showPasswordModal = false;
  }

  submitChangePassword(): void {
    if (!this.currentPassword || !this.newPassword || !this.confirmPassword) {
      this.passwordError = 'All fields are required.';
      return;
    }
    if (this.newPassword.length < 8) {
      this.passwordError = 'New password must be at least 8 characters.';
      return;
    }
    if (this.newPassword !== this.confirmPassword) {
      this.passwordError = 'New passwords do not match.';
      return;
    }
    this.passwordSubmitting = true;
    this.passwordError = '';
    this.userService.changePassword({ current_password: this.currentPassword, new_password: this.newPassword }).subscribe({
      next: () => {
        this.passwordSuccess = 'Password changed successfully.';
        this.passwordSubmitting = false;
        setTimeout(() => { this.showPasswordModal = false; this.passwordSuccess = ''; }, 1200);
      },
      error: (err) => {
        this.passwordError = err?.error?.detail || 'Failed to change password.';
        this.passwordSubmitting = false;
      }
    });
  }
}

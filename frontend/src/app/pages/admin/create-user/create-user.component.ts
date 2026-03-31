import { Component, OnInit } from '@angular/core';
import { FormGroup, FormControl, Validators, ReactiveFormsModule, FormsModule } from '@angular/forms';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MaterialModule } from 'src/app/material.module';
import { AdminService, UserRead } from '../../../services/admin.service';

@Component({
  selector: 'app-create-user',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, FormsModule, MaterialModule, RouterModule],
  templateUrl: './create-user.component.html',
})
export class CreateUserComponent implements OnInit {
  users: UserRead[] = [];
  loading = false;
  submitting = false;
  successMessage = '';
  errorMessage = '';
  editingUserId: string | null = null;
  isEditMode = false;
  form = new FormGroup({
    email: new FormControl('', [Validators.required, Validators.email]),
    username: new FormControl('', [Validators.required, Validators.minLength(3)]),
    is_admin: new FormControl(false),
    is_active: new FormControl(false),
  });

  constructor(private adminService: AdminService) {}

  get f() { return this.form.controls; }

  ngOnInit() {
    this.loadUsers();
  }

  loadUsers() {
    this.loading = true;
    this.adminService.getUsers().subscribe({
      next: (users) => { this.users = users; this.loading = false; },
      error: () => { this.loading = false; }
    });
  }

  submit(): void {
    if (this.form.invalid) return;

    this.submitting = true;
    this.successMessage = '';
    this.errorMessage = '';

    if (this.isEditMode && this.editingUserId) {
      const payload = {
        email: this.form.get('email')?.value ?? '',
        username: this.form.get('username')?.value ?? '',
        is_admin: this.form.get('is_admin')?.value ?? false,
        is_active: this.form.get('is_active')?.value ?? false
      };

      this.adminService.updateUser(this.editingUserId, payload).subscribe({
        next: () => {
          this.successMessage = 'User updated successfully';
          this.submitting = false;
          this.cancelEdit();
          this.loadUsers();
        },
        error: (err) => {
          this.errorMessage = err?.error?.detail || 'Failed to update user';
          this.submitting = false;
        }
      });
    } else {
      const payload = {
        email: this.form.get('email')?.value ?? '',
        username: this.form.get('username')?.value ?? '',
        is_admin: this.form.get('is_admin')?.value ?? false
      };

      this.adminService.createUser(payload).subscribe({
        next: () => {
          this.successMessage = 'User created successfully';
          this.submitting = false;
          this.form.reset({
            email: '',
            username: '',
            is_admin: false,
            is_active: false
          });
          this.loadUsers();
        },
        error: (err) => {
          this.errorMessage = err?.error?.detail || 'Failed to create user';
          this.submitting = false;
        }
      });
    }
  }

  deleteUser(id: string) {
    if (!confirm('Delete this user?')) return;
    this.adminService.deleteUser(id).subscribe({
      next: () => this.loadUsers()
    });
  }

  editUser(user: UserRead): void {
    this.isEditMode = true;
    this.editingUserId = user.id;

    this.form.patchValue({
      email: user.email,
      username: user.username,
      is_admin: user.is_admin,
      is_active: user.is_active
    });

    this.successMessage = '';
    this.errorMessage = '';
  }

  cancelEdit(): void {
    this.isEditMode = false;
    this.editingUserId = null;
    this.form.reset({
      email: '',
      username: '',
      is_admin: false,
      is_active: false
    });
  }
}

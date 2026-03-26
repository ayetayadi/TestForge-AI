import { Component } from '@angular/core';
import { FormGroup, FormControl, Validators, ReactiveFormsModule, FormsModule, AbstractControl } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { HttpClient } from '@angular/common/http';

function passwordMatchValidator(control: AbstractControl) {
  const newPassword = control.get('new_password');
  const confirm = control.get('confirm_password');
  if (newPassword && confirm && newPassword.value !== confirm.value) {
    confirm.setErrors({ mismatch: true });
  } else {
    confirm?.setErrors(null);
  }
  return null;
}

@Component({
  selector: 'app-change-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, FormsModule, MaterialModule, RouterModule],
  templateUrl: './change-password.component.html',
})
export class ChangePasswordComponent {
  loading = false;
  errorMessage = '';
  successMessage = '';

  form = new FormGroup({
    current_password: new FormControl('', [Validators.required]),
    new_password: new FormControl('', [Validators.required, Validators.minLength(6)]),
    confirm_password: new FormControl('', [Validators.required]),
  }, { validators: passwordMatchValidator });

  get f() { return this.form.controls; }

  constructor(private http: HttpClient, private router: Router) {}

  submit() {
    if (this.form.invalid) return;
    this.loading = true;
    this.errorMessage = '';

    this.http.post('http://localhost:8000/auth/change-password', {
      current_password: this.f['current_password'].value,
      new_password: this.f['new_password'].value,
    }).subscribe({
      next: () => {
        this.loading = false;
        this.successMessage = 'Password changed! Redirecting...';
        setTimeout(() => this.router.navigate(['/dashboard']), 1500);
      },
      error: (err) => {
        this.loading = false;
        this.errorMessage = err.error?.detail || 'Failed to change password';
      }
    });
  }
}

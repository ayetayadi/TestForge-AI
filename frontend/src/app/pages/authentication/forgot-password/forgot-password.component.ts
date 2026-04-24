import { Component } from '@angular/core';
import { FormGroup, FormControl, Validators, ReactiveFormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { AuthService } from 'src/app/services/auth.service';

@Component({
  selector: 'app-forgot-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MaterialModule, RouterModule],
  templateUrl: './forgot-password.component.html',
  styleUrls: ['./forgot-password.component.scss'],
})
export class ForgotPasswordComponent {
  loading      = false;
  errorMessage = '';
  sent         = false;

  form = new FormGroup({
    email: new FormControl('', [Validators.required, Validators.email]),
  });

  get f() { return this.form.controls; }

  constructor(private auth: AuthService) {}

  submit() {
    if (this.form.invalid || this.loading) return;
    this.loading      = true;
    this.errorMessage = '';

    this.auth.forgotPassword({ email: this.f['email'].value! }).subscribe({
      next: () => {
        this.loading = false;
        this.sent    = true;
      },
      error: () => {
        this.loading      = false;
        this.errorMessage = 'Something went wrong. Please try again.';
      }
    });
  }
}

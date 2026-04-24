import { Component, OnInit } from '@angular/core';
import { FormGroup, FormControl, Validators,
  ReactiveFormsModule, AbstractControl } from '@angular/forms';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { CommonModule } from '@angular/common';
import { MaterialModule } from 'src/app/material.module';
import { AuthService } from 'src/app/services/auth.service';

function passwordMatchValidator(control: AbstractControl) {
  const pw  = control.get('new_password');
  const cpw = control.get('confirm_password');
  if (pw && cpw && pw.value !== cpw.value) {
    cpw.setErrors({ mismatch: true });
  } else {
    cpw?.setErrors(null);
  }
  return null;
}

@Component({
  selector: 'app-reset-password',
  standalone: true,
  imports: [CommonModule, ReactiveFormsModule, MaterialModule, RouterModule],
  templateUrl: './reset-password.component.html',
  styleUrls: ['./reset-password.component.scss'],
})
export class ResetPasswordComponent implements OnInit {
  loading        = false;
  errorMessage   = '';
  successMessage = '';
  invalidToken   = false;
  token          = '';

  hideNewPassword = true;
  hideConfirmPassword = true;

  form = new FormGroup({
    new_password:     new FormControl('', [Validators.required, Validators.minLength(6)]),
    confirm_password: new FormControl('', [Validators.required]),
  }, { validators: passwordMatchValidator });

  get f() { return this.form.controls; }

  constructor(
    private auth:   AuthService,
    private router: Router,
    private route:  ActivatedRoute,
  ) {}

  ngOnInit() {
    this.token = this.route.snapshot.queryParamMap.get('token') ?? '';
    if (!this.token) this.invalidToken = true;
  }

  submit() {
    if (this.form.invalid || this.loading) return;
    this.loading      = true;
    this.errorMessage = '';

    this.auth.resetPassword({
      token:            this.token,
      new_password:     this.f['new_password'].value!,
      confirm_password: this.f['confirm_password'].value!,
    }).subscribe({
      next: () => {
        this.loading        = false;
        this.successMessage = 'Password reset! Redirecting…';
        setTimeout(() => this.router.navigate(['/authentication/login']), 1500);
      },
      error: (err) => {
        this.loading      = false;
        this.errorMessage = err.error?.detail ?? 'Reset failed. The link may have expired.';
      }
    });
  }
}
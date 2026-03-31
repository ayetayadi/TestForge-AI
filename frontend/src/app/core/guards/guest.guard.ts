import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from 'src/app/services/auth.service';

export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isLoggedIn()) {
    const isAdmin = localStorage.getItem('is_admin') === 'true';

    if (isAdmin) {
      router.navigate(['/admin-dashboard']);
    } else {
      router.navigate(['/user-dashboard']);
    }

    return false;
  }

  return true;
};

import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from 'src/app/services/auth.service';

export const guestGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  return auth.tryAutoLogin().pipe(
    map(success => {
      if (success) {
        router.navigate([auth.getIsAdmin() ? '/admin-dashboard' : '/user-dashboard']);
        return false;
      }
      return true;
    })
  );
};

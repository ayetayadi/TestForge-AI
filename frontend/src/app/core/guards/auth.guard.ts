import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map } from 'rxjs/operators';
import { AuthService } from 'src/app/services/auth.service';

export const authGuard: CanActivateFn = () => {
  const auth = inject(AuthService);
  const router = inject(Router);

  if (auth.isLoggedIn()) {
    return true;
  }

  return auth.tryAutoLogin().pipe(
    map(success => {
      if (!success) {
        router.navigate(['/authentication/login']);
        return false;
      }
      return true;
    })
  );
};
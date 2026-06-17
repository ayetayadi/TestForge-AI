import { BreakpointObserver } from '@angular/cdk/layout';
import { Component, ViewChild, ViewEncapsulation, OnInit, AfterViewInit, OnDestroy } from '@angular/core';
import { MatSidenav, MatSidenavModule } from '@angular/material/sidenav';
import { NavigationEnd, Router, RouterModule } from '@angular/router';
import { filter } from 'rxjs/operators';
import { CommonModule } from '@angular/common';
import { NgScrollbarModule } from 'ngx-scrollbar';
import { MatListModule } from '@angular/material/list';
import { Subscription } from 'rxjs';

import { navItems } from './sidebar/sidebar-data';
import { NavItem } from './sidebar/nav-item/nav-item';
import { AuthService } from 'src/app/services/auth.service';
import { jwtDecode } from 'jwt-decode';
import { HeaderComponent } from './header/header.component';
import { SidebarComponent } from './sidebar/sidebar.component';
import { AppNavItemComponent } from './sidebar/nav-item/nav-item.component';
import { TastyComponent } from 'src/app/components/tasty/tasty.component';

@Component({
  selector: 'app-full',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatSidenavModule,
    MatListModule,
    NgScrollbarModule,
    HeaderComponent,
    SidebarComponent,
    AppNavItemComponent,
    TastyComponent
  ],
  templateUrl: './full.component.html',
  styleUrls: ['./full.component.scss'],
  encapsulation: ViewEncapsulation.None,
})
export class FullComponent implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('sidenav') sidenav!: MatSidenav;
  
  sidebarOpened = true;
  isMobile = false;
  isCollapsed = false;
  isAdmin = false;
  navItems: NavItem[] = [];

  private readonly COLLAPSED_KEY = 'sidebar_collapsed';
  private subscriptions: Subscription[] = [];

  constructor(
    private router: Router,
    private breakpointObserver: BreakpointObserver,
    private authService: AuthService
  ) {
    const savedState = localStorage.getItem(this.COLLAPSED_KEY);
    if (savedState !== null) {
      this.isCollapsed = savedState === 'true';
    }

    this.breakpointObserver.observe(['(max-width: 768px)']).subscribe(result => {
      this.isMobile = result.matches;
      
      if (this.isMobile) {
        this.sidebarOpened = false;
        this.isCollapsed = false;
        if (this.sidenav) {
          this.sidenav.close();
          this.removeBackdrop();
        }
      } else {
        this.sidebarOpened = !this.isCollapsed;
        if (this.sidenav && this.sidebarOpened) {
          this.sidenav.open();
        }
      }
    });

    this.router.events
      .pipe(filter(event => event instanceof NavigationEnd))
      .subscribe(() => {
        const content = document.querySelector('.mat-sidenav-content');
        content?.scrollTo({ top: 0 });
        if (this.isMobile && this.sidenav) {
          this.sidenav.close();
          this.sidebarOpened = false;
          this.removeBackdrop();
        }
      });
  }

  ngOnInit(): void {
    this.buildNav();
  }

  ngAfterViewInit(): void {
    this.removeBackdrop();
    
    // CORRECTION: Utiliser openedStart et _animationFinished ou simplement setTimeout
    if (this.sidenav) {
      // Écouter l'ouverture
      this.subscriptions.push(
        this.sidenav.openedStart.subscribe(() => {
          setTimeout(() => this.removeBackdrop(), 10);
        })
      );
      
      // Écouter la fermeture via openedChange (false = fermé)
      this.subscriptions.push(
        this.sidenav.openedChange.subscribe((isOpen) => {
          if (!isOpen) {
            setTimeout(() => this.removeBackdrop(), 10);
          }
        })
      );
    }
  }

  ngOnDestroy(): void {
    this.subscriptions.forEach(sub => sub.unsubscribe());
  }

  private removeBackdrop(): void {
    setTimeout(() => {
      const backdrops = document.querySelectorAll('.mat-drawer-backdrop, .cdk-overlay-backdrop');
      backdrops.forEach(backdrop => {
        backdrop.setAttribute('style', 'display: none !important; opacity: 0 !important; background: transparent !important; visibility: hidden !important; pointer-events: none !important;');
      });
    }, 10);
  }

  buildNav(): void {
    const token = this.authService.getAccessToken();
    let isAdmin = false;

    if (token) {
      try {
        const decoded: any = jwtDecode(token);
        isAdmin = decoded.is_admin === true;
      } catch {}
    }

    this.isAdmin = isAdmin;

    this.navItems = navItems.filter(item => {
      if (item.adminOnly && !isAdmin) return false;
      if (item.userOnly && isAdmin) return false;
      return true;
    });
  }

  toggleSidebar(): void {
    this.removeBackdrop();
    
    if (this.isMobile) {
      if (this.sidebarOpened) {
        this.sidenav.close();
        this.sidebarOpened = false;
      } else {
        this.sidenav.open();
        this.sidebarOpened = true;
        setTimeout(() => this.removeBackdrop(), 50);
      }
    } else {
      this.isCollapsed = !this.isCollapsed;
      this.sidebarOpened = !this.isCollapsed;
      localStorage.setItem(this.COLLAPSED_KEY, String(this.isCollapsed));
    }
  }

  closeSidebarOnMobile(): void {
    if (this.isMobile && this.sidebarOpened) {
      this.sidenav.close();
      this.sidebarOpened = false;
      this.removeBackdrop();
    }
  }
}
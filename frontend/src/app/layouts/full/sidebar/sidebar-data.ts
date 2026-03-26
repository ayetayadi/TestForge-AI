import { NavItem } from './nav-item/nav-item';

export const navItems: NavItem[] = [
  {
    navCap: 'Home',
  },
  {
    displayName: 'Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/dashboard',
  },
  {
    navCap: 'Admin',
    divider: true,
    adminOnly: true,        // ← hide cap for non-admins
  },
  {
    displayName: 'Manage Users',
    iconName: 'solar:users-group-rounded-line-duotone',
    route: '/dashboard/admin/users',
    adminOnly: true,        // ← admin only
  },
  {
    navCap: 'Integrations',
    divider: true,
    userOnly: true,         // ← hide cap for admins
  },
  {
    displayName: 'Connect Jira',
    iconName: 'solar:link-circle-line-duotone',
    route: '/dashboard/jira',
    userOnly: true,         // ← regular users only
  },
];

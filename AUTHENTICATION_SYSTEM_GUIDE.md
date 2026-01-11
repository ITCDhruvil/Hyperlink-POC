# Authentication System Guide

Complete user authentication and management system for PDF Automation.

## Overview

The application now has a complete authentication system with:
- Login and signup functionality
- User management (admin only)
- Role-based access control (Admin vs Regular Users)
- Single superuser account

## Quick Start

### 1. Create the Superuser

Run the management command to create the default admin account:

```bash
python manage.py create_superuser
```

This creates:
- **Email**: `hyperlink@itcube.net`
- **Password**: `!TCube@12`
- **Role**: Superuser (full admin access)

### 2. Run Migrations (if needed)

```bash
python manage.py migrate
```

### 3. Start the Server

```bash
python manage.py runserver 8004
```

### 4. Access the Application

Open your browser and navigate to:
- **Login**: http://localhost:8004/login/
- **Signup**: http://localhost:8004/signup/

## User Roles

### Superuser / Admin
- Full access to all features
- Can see "User Management" button in navigation
- Can create, delete, activate/deactivate users
- Can promote users to admin or demote them
- Cannot delete or modify their own account

### Regular Users
- Access to processor and history pages
- Cannot see or access user management
- Can use all document processing features
- Cannot manage other users

## Pages and Features

### Login Page (`/login/`)
- Email-based authentication
- Minimal, clean design
- Redirects to processor UI after successful login
- Shows error messages for invalid credentials or inactive accounts

### Signup Page (`/signup/`)
- Email-based registration
- Password confirmation required
- Minimum 6-character password
- Email validation
- Automatically activates new users

### Processor UI (`/`)
- **Requires login**
- Navigation buttons:
  - View History
  - User Management (admin only)
  - Logout

### Processing History (`/history/`)
- **Requires login**
- Navigation buttons:
  - Back to Processor
  - User Management (admin only)
  - Logout

### User Management (`/users/`)
- **Admin only**
- Shows all users in a table
- Statistics dashboard (Total, Admin, Active users)
- Create new users with email and password
- Delete users (except superuser and self)
- Activate/Deactivate users (except superuser and self)
- Promote to admin / Demote to regular user (except superuser and self)
- Real-time updates with AJAX

## User Management Features

### Creating Users

1. Click "Create User" button
2. Enter email address
3. Enter password (minimum 6 characters)
4. Optionally check "Make this user an admin"
5. Click "Create User"

### Managing Users

**Delete User**:
- Click "Delete" button next to user
- Confirm deletion
- User is permanently removed
- Cannot delete superuser or yourself

**Activate/Deactivate**:
- Click "Activate" or "Deactivate" button
- User status changes immediately
- Inactive users cannot log in
- Cannot deactivate superuser or yourself

**Promote/Demote Admin**:
- Click "Promote" to make user an admin
- Click "Demote" to remove admin privileges
- Admins can see and access user management
- Cannot modify superuser or your own status

## URL Structure

| URL | Description | Access |
|-----|-------------|--------|
| `/login/` | Login page | Public |
| `/signup/` | Signup page | Public |
| `/logout/` | Logout endpoint | Logged in users |
| `/` | Processor UI | Logged in users |
| `/history/` | Processing history | Logged in users |
| `/users/` | User management | Admin only |
| `/users/create/` | Create user API | Admin only |
| `/users/<id>/delete/` | Delete user API | Admin only |
| `/users/<id>/toggle-active/` | Toggle user active status | Admin only |
| `/users/<id>/toggle-admin/` | Toggle admin status | Admin only |

## Security Features

### Authentication
- Session-based authentication using Django's built-in system
- CSRF protection on all forms
- Password hashing with Django's default password hasher
- Login required for all processor endpoints

### Authorization
- Role-based access control (admin vs regular users)
- Superuser cannot be deleted or deactivated
- Users cannot modify their own admin status or active status
- Only admins can access user management

### Password Requirements
- Minimum 6 characters
- No complexity requirements (can be enhanced if needed)
- Passwords are never displayed or transmitted in plain text

### Account Protection
- Inactive accounts cannot log in
- Failed login attempts show generic error message
- Email uniqueness enforced
- Username automatically generated from email

## Navigation Flow

### Regular User Flow
```
Login → Processor UI → History → Logout
```

### Admin User Flow
```
Login → Processor UI → User Management → History → Logout
                  ↓
            Manage Users
            (Create, Delete, Activate, Promote)
```

## API Endpoints (Admin Only)

### Create User
```
POST /users/create/
Body: email, password, is_admin
Returns: {success: true, message: "...", user: {...}}
```

### Delete User
```
POST /users/<user_id>/delete/
Returns: {success: true, message: "..."}
```

### Toggle Active Status
```
POST /users/<user_id>/toggle-active/
Returns: {success: true, message: "...", is_active: true/false}
```

### Toggle Admin Status
```
POST /users/<user_id>/toggle-admin/
Returns: {success: true, message: "...", is_admin: true/false}
```

## Error Messages

### Login Errors
- "Invalid email or password" - Wrong credentials
- "Your account has been deactivated" - Account is inactive

### Signup Errors
- "Please enter a valid email address" - Invalid email format
- "An account with this email already exists" - Duplicate email
- "Passwords do not match" - Password confirmation mismatch
- "Password must be at least 6 characters long" - Short password

### User Management Errors
- "You cannot delete your own account" - Self-deletion attempt
- "Cannot delete superuser account" - Superuser protection
- "You cannot deactivate your own account" - Self-deactivation
- "Cannot deactivate superuser account" - Superuser protection
- "You cannot modify your own admin status" - Self-modification
- "Cannot modify superuser status" - Superuser protection

## Design Consistency

All authentication pages follow the same minimal design:
- Clean white background
- Card-based layout with subtle shadows
- Consistent button styling (dark gray #111827)
- Form inputs with focus states
- Alert messages (green for success, red for errors)
- Responsive design
- Same font family as existing pages

## Files Created/Modified

### New Files
1. `pdfs/views_auth.py` - Authentication and user management views
2. `pdfs/templates/pdfs/login.html` - Login page
3. `pdfs/templates/pdfs/signup.html` - Signup page
4. `pdfs/templates/pdfs/user_management.html` - User management page
5. `pdfs/management/commands/create_superuser.py` - Superuser creation command
6. `AUTHENTICATION_SYSTEM_GUIDE.md` - This documentation

### Modified Files
1. `pdfs/urls.py` - Added authentication and user management URLs
2. `pdfs/views_processor_ui.py` - Added @login_required decorators
3. `pdfs/templates/pdfs/processor_ui.html` - Added navigation for User Management and Logout
4. `pdfs/templates/pdfs/processing_history.html` - Added navigation for User Management and Logout
5. `pdf_automation/settings.py` - Added LOGIN_URL and redirect settings

## Testing the System

### Test Superuser Login
1. Navigate to http://localhost:8004/login/
2. Email: `hyperlink@itcube.net`
3. Password: `!TCube@12`
4. Should redirect to processor UI
5. Should see "User Management" button

### Test Regular User Signup
1. Navigate to http://localhost:8004/signup/
2. Enter email: `user@example.com`
3. Enter password: `testpass123`
4. Confirm password
5. Click "Create Account"
6. Login with new credentials
7. Should NOT see "User Management" button

### Test User Management
1. Login as superuser
2. Click "User Management"
3. Create a new user
4. Toggle admin status
5. Toggle active status
6. Try deleting the user
7. Verify all actions work correctly

## Troubleshooting

### "Page not found" errors
- Make sure you ran migrations: `python manage.py migrate`
- Check that the server is running on port 8004

### Cannot login
- Verify superuser was created: `python manage.py create_superuser`
- Check credentials are correct (email: hyperlink@itcube.net, password: !TCube@12)
- Make sure account is active

### User Management not visible
- Only admin users can see "User Management" button
- Check user has `is_staff=True` in database
- Superuser automatically has admin access

### CSRF token errors
- Make sure `{% csrf_token %}` is in all forms
- Clear browser cache and cookies
- Check CSRF middleware is enabled in settings

## Future Enhancements

Possible improvements:
- Password reset functionality
- Email verification for new signups
- Two-factor authentication (2FA)
- Password complexity requirements
- Account lockout after failed attempts
- User activity logging
- Bulk user operations
- User groups and permissions
- Profile management

---

**Last Updated**: January 2026
**Version**: 1.0.0 (Initial Authentication System)

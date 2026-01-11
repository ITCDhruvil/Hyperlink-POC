"""
Management command to create the default superuser
Email: hyperlink@itcube.net
Password: !TCube@12
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User


class Command(BaseCommand):
    help = 'Creates the default superuser if it does not exist'

    def handle(self, *args, **kwargs):
        email = 'hyperlink@itcube.net'
        password = '!TCube@12'
        username = 'hyperlink_admin'

        # Check if superuser already exists
        if User.objects.filter(email=email).exists():
            self.stdout.write(self.style.WARNING(f'Superuser with email {email} already exists.'))
            return

        # Create superuser
        user = User.objects.create_superuser(
            username=username,
            email=email,
            password=password
        )
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()

        self.stdout.write(self.style.SUCCESS(f'Successfully created superuser:'))
        self.stdout.write(self.style.SUCCESS(f'  Email: {email}'))
        self.stdout.write(self.style.SUCCESS(f'  Password: {password}'))

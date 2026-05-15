import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

from apps.users.models import User
from apps.organizations.models import Organization, Membership

def populate():
    print("Populating database...")
    
    # 1. Create Test Users
    users_data = [
        {"email": "organizer1@test.com", "full_name": "Org One", "role": User.Role.ORGANIZER},
        {"email": "organizer2@test.com", "full_name": "Org Two", "role": User.Role.ORGANIZER},
        {"email": "attendee1@test.com", "full_name": "User One", "role": User.Role.ATTENDEE},
    ]
    
    for u_data in users_data:
        user, created = User.objects.get_or_create(
            email=u_data["email"],
            defaults={
                "full_name": u_data["full_name"],
                "role": u_data["role"],
                "is_verified": True
            }
        )
        if created:
            user.set_password("password123")
            user.save()
            print(f"Created user: {user.email}")
            
            # 2. Create Organizations for Organizers
            if user.role == User.Role.ORGANIZER:
                org = Organization.objects.create(
                    name=f"{user.full_name}'s Events",
                    owner=user
                )
                Membership.objects.create(user=user, org=org, role=Membership.Role.OWNER)
                print(f"Created organization: {org.name}")

    print("Database population complete!")

if __name__ == "__main__":
    populate()

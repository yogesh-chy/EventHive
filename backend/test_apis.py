import os
import django
from django.test import Client
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')
django.setup()

def test_api_health():
    client = Client()
    print("\n--- Testing API Endpoints ---")
    
    # 1. Test Login
    print("Testing Login for organizer1@test.com...")
    login_data = {
        "email": "organizer1@test.com",
        "password": "password123"
    }
    response = client.post('/api/v1/auth/login/', data=json.dumps(login_data), content_type='application/json')
    
    if response.status_code == 200:
        print("[SUCCESS] Login Successful")
        json_data = response.json().get('data', {})
        access_token = json_data.get('access')
        refresh_token = json_data.get('refresh')
        if access_token:
            print("[SUCCESS] JWT Access Token Received")
        
        # 2. Test Logout
        if refresh_token:
            print("\nTesting Logout...")
            logout_data = {"refresh": refresh_token}
            # Add access token to header for authentication
            client.defaults['HTTP_AUTHORIZATION'] = f'Bearer {access_token}'
            logout_response = client.post('/api/v1/auth/logout/', data=json.dumps(logout_data), content_type='application/json')
            if logout_response.status_code == 200:
                print("[SUCCESS] Logout Successful")
            else:
                print(f"[FAILED] Logout Failed: {logout_response.status_code}")
                print(logout_response.content.decode())
    else:
        print(f"[FAILED] Login Failed: {response.status_code}")
        print("Response Content:", response.json())

    # 2. Test Registration (New User)
    print("\nTesting Registration for newuser@test.com...")
    import random
    email = f"newuser{random.randint(1,1000)}@test.com"
    reg_data = {
        "email": email,
        "password": "password123",
        "full_name": "New Test User",
        "role": "ATTENDEE"
    }
    response = client.post('/api/v1/auth/register/', data=json.dumps(reg_data), content_type='application/json')
    
    if response.status_code == 201:
        print(f"[SUCCESS] Registration Successful for {email}")
    else:
        print(f"[FAILED] Registration Failed: {response.status_code}")
        print("Response Content:", response.json())

if __name__ == "__main__":
    test_api_health()

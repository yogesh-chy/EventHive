# EventHive

EventHive is a production-grade, multi-tenant event ticketing and management platform. It is designed to handle high-concurrency ticket sales, real-time seat availability, and complex multi-tenant organization management.

---

## System Architecture

The project follows a **Layered Monolith** pattern with clear separation of concerns:

- **Client Layer**: Web/Mobile consumers interacting via REST and WebSockets.
- **API Gateway (Nginx)**: Handles TLS termination, rate limiting, and static file serving.
- **Application Layer (Django)**: Business logic decoupled into Services and DRF Viewsets.
- **Async Layer (Celery)**: Handles heavy tasks like PDF generation, QR codes, and emails.
- **Real-Time Layer (Channels)**: WebSocket broadcasting for live seat counts.
- **Data Layer (PostgreSQL & Redis)**: Relational storage with Redis-based caching and atomic locking.

---

## User Roles & Permissions

| Role | Permissions |
| :--- | :--- |
| **Admin** | Full platform access. Manages organizations, users, and global audit logs. |
| **Organizer** | Creates and manages events within their organization. Views revenue reports. |
| **Attendee** | Browses events, purchases tickets, and manages their booking history. |

---

## Tech Stack & Role

| Technology | Role |
| :--- | :--- |
| **Django 5.x** | Core framework & ORM. |
| **DRF 3.x** | RESTful API development & Serialization. |
| **Channels 4.x** | WebSocket support for real-time updates. |
| **PostgreSQL 16** | Primary relational store with Full-Text Search. |
| **Redis 7** | Celery broker, caching, and atomic seat locking (WSL2). |
| **Celery 5.x** | Distributed task queue for async processing. |
| **Stripe SDK** | Payment processing and idempotent webhook handling. |
| **WSL2** | Running Redis 7 in a native Linux environment on Windows. |

---

## Project Structure

```text
backend/
├── apps/
│   ├── users/          # Custom User model & JWT Authentication
│   ├── organizations/  # Multi-tenancy & Membership management
│   ├── events/         # Event CRUD & Full-Text Search
│   ├── orders/         # Atomic purchase flow & Stripe integration
│   ├── tickets/        # QR Code & PDF Ticket generation
│   ├── notifications/  # Email, SMS, and Push dispatch
│   └── audit/          # Immutable system-wide audit trail
├── config/             # Root configuration & split settings
├── core/               # Shared BaseModel, Permissions, & Middleware
├── services/           # Business logic (Payment, SeatLock, RealTime)
├── tasks/              # Celery task definitions
└── websockets/         # Django Channels consumers & routing
```

---

## Getting Started

### Prerequisites
- **Python 3.12+**
- **PostgreSQL 16** (Running locally)
- **Redis 7** (Running via WSL2 on Windows)

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/yogesh-chy/eventhive.git
   cd eventhive/backend
   ```

2. **Setup Virtual Environment**:
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize Environment**:
   ```bash
   cp .env.example .env
   # Update .env with your local DB and Redis credentials
   ```

5. **Initialize Database**:
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   python manage.py createsuperuser
   ```

6. **Start Services**:
   - Ensure Redis is running in WSL: `sudo service redis-server start`
   - Start Django: `python manage.py runserver` (or `make run`)
   - Start Celery: `celery -A config worker -l info --pool=solo` (or `make worker`)

---

## Key Backend Concepts Applied

- **Atomic Ticket Purchase**: Uses Redis `SETNX` for seat locking + DB transactions + Stripe idempotency.
- **Multi-Tenancy**: Organization-based data isolation via custom QuerySets and Middleware.
- **Soft Deletes**: All models inherit from `BaseModel` to prevent accidental data loss.
- **N+1 Prevention**: Strict use of `select_related` and `prefetch_related` across all endpoints.
- **Immutable Audit Trail**: Append-only log of every state change in the system.

---

## API Documentation

- **Admin Panel**: `http://localhost:8000/admin/`
- **Swagger UI**: `http://localhost:8000/api/v1/schema/swagger-ui/`
- **Redoc**: `http://localhost:8000/api/v1/schema/redoc/`

---

## Environment Configuration (.env)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `DJANGO_SECRET_KEY` | Secure key for Django. | `dev-key` |
| `DEBUG` | Toggle debug mode. | `True` |
| `DATABASE_URL` | PostgreSQL connection string. | `postgres://...` |
| `REDIS_URL` | Redis connection for cache. | `redis://...` |
| `CELERY_BROKER_URL` | Redis connection for tasks. | `redis://...` |
| `STRIPE_SECRET_KEY` | Stripe API private key. | `sk_test_...` |

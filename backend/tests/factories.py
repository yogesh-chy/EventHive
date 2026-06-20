import factory
from factory.django import DjangoModelFactory
from faker import Faker

from django.utils import timezone
from apps.organizations.models import Membership, Organization
from apps.users.models import User
from apps.events.models import Event, TicketTier
from apps.orders.models import Order, OrderItem, Ticket, OrderStatus, TicketStatus

fake = Faker()


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True   # avoid double save after set_password

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    full_name = factory.LazyFunction(fake.name)
    role = User.Role.ATTENDEE
    is_active = True
    is_verified = True   # verified by default so tests can log in

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        raw = extracted or "Testpass123!"
        self.set_password(raw)
        if create:
            self.save(update_fields=["password"])


class UnverifiedUserFactory(UserFactory):
    is_verified = False


class OrganizerFactory(UserFactory):
    role = User.Role.ORGANIZER
    email = factory.Sequence(lambda n: f"organizer{n}@example.com")


class AdminFactory(UserFactory):
    role = User.Role.ADMIN
    is_staff = True
    email = factory.Sequence(lambda n: f"admin{n}@example.com")


class OrganizationFactory(DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.LazyFunction(lambda: fake.company()[:100])
    owner = factory.SubFactory(OrganizerFactory)
    is_active = True

    @factory.post_generation
    def with_owner_membership(self, create, extracted, **kwargs):
        """Auto-create OWNER membership unless caller opts out."""
        if not create:
            return
        if extracted is False:
            return
        Membership.objects.get_or_create(
            user=self.owner,
            org=self,
            defaults={"role": Membership.Role.OWNER},
        )


class MembershipFactory(DjangoModelFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(UserFactory)
    org = factory.SubFactory(OrganizationFactory)
    role = Membership.Role.MEMBER


class EventFactory(DjangoModelFactory):
    class Meta:
        model = Event

    title = factory.Sequence(lambda n: f"Event {n}")
    slug = factory.Sequence(lambda n: f"event-{n}")
    org = factory.SubFactory(OrganizationFactory)
    description = factory.LazyAttribute(lambda o: f"Description for {o.title}")
    venue = "Main Hall"
    city = "San Francisco"
    country = "US"
    start_datetime = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=2))
    end_datetime = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(days=3))
    status = "PUBLISHED"
    total_capacity = 100
    tickets_sold = 0


class TicketTierFactory(DjangoModelFactory):
    class Meta:
        model = TicketTier

    event = factory.SubFactory(EventFactory)
    name = factory.Sequence(lambda n: f"Tier {n}")
    price = 20.00
    quantity = 50
    quantity_sold = 0
    is_active = True


class OrderFactory(DjangoModelFactory):
    class Meta:
        model = Order

    attendee = factory.SubFactory(UserFactory)
    event = factory.SubFactory(EventFactory)
    reference = factory.Sequence(lambda n: "".join(
        "ABCDEFGHJKMNPQRSTUVWXYZ23456789"[(n + i) % 31] for i in range(8)
    ))
    idempotency_key = factory.Sequence(lambda n: f"idem{n:028d}")
    status = OrderStatus.PENDING
    total_amount = 20.00
    currency = "USD"
    expires_at = factory.LazyFunction(lambda: timezone.now() + timezone.timedelta(minutes=10))


class OrderItemFactory(DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    tier = factory.SubFactory(TicketTierFactory)
    quantity = 1
    unit_price = 20.00


class TicketFactory(DjangoModelFactory):
    class Meta:
        model = Ticket

    order_item = factory.SubFactory(OrderItemFactory)
    attendee = factory.SubFactory(UserFactory)
    event = factory.SubFactory(EventFactory)
    tier = factory.SubFactory(TicketTierFactory)
    status = TicketStatus.VALID
    qr_code = factory.Sequence(lambda n: f"qrcode{n}")


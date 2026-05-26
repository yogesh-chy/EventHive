import factory
from factory.django import DjangoModelFactory
from faker import Faker

from apps.organizations.models import Membership, Organization
from apps.users.models import User

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

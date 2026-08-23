from decimal import Decimal

from django.db import migrations


def create_initial_plans(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')
    SubscriptionPlan.objects.bulk_create([
        SubscriptionPlan(
            name='Premium Weekly',
            slug='premium-weekly',
            description='Weekly premium access to all AI learning tools.',
            price=Decimal('0.00'),
            duration_days=7,
            is_active=True,
        ),
        SubscriptionPlan(
            name='Premium Monthly',
            slug='premium-monthly',
            description='Monthly premium access to all AI learning tools.',
            price=Decimal('0.00'),
            duration_days=30,
            is_active=True,
        ),
    ])


class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_initial_plans, reverse_code=migrations.RunPython.noop),
    ]

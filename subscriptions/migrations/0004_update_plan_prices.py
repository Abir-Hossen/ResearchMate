from decimal import Decimal

from django.db import migrations


def update_subscription_plan_prices(apps, schema_editor):
    SubscriptionPlan = apps.get_model('subscriptions', 'SubscriptionPlan')

    weekly = SubscriptionPlan.objects.filter(slug='premium-weekly').first()
    if weekly is not None:
        weekly.price = Decimal('99.00')
        weekly.duration_days = 7
        weekly.is_active = True
        weekly.save(update_fields=['price', 'duration_days', 'is_active'])

    monthly = SubscriptionPlan.objects.filter(slug='premium-monthly').first()
    if monthly is not None:
        monthly.price = Decimal('299.00')
        monthly.duration_days = 30
        monthly.is_active = True
        monthly.save(update_fields=['price', 'duration_days', 'is_active'])


class Migration(migrations.Migration):
    dependencies = [
        ('subscriptions', '0003_paymenttransaction'),
    ]

    operations = [
        migrations.RunPython(update_subscription_plan_prices, reverse_code=migrations.RunPython.noop),
    ]

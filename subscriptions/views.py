from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import SubscriptionPlan
from .services import get_current_subscription_status


@login_required(login_url='login')
def pricing_view(request):
    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('duration_days')
    subscription_status = get_current_subscription_status(request.user)
    return render(request, 'subscriptions/pricing.html', {
        'plans': plans,
        'subscription_status': subscription_status,
    })

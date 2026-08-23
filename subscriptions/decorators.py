from urllib.parse import urlencode

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

from .services import user_has_premium_access


def premium_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if not user_has_premium_access(request.user):
            messages.error(
                request,
                'This feature is available with Premium access. Upgrade to unlock all AI learning tools.',
            )
            next_url = request.get_full_path()
            query = urlencode({'next': next_url})
            return redirect(f"{reverse('subscriptions:pricing')}?{query}")
        return view_func(request, *args, **kwargs)
    return _wrapped_view

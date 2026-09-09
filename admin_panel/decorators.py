from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse


def staff_required(view_func):
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('admin_panel:login')}?next={request.path}")
        if not request.user.is_staff:
            return HttpResponseForbidden("Access denied. Staff membership is required.")
        return view_func(request, *args, **kwargs)
    return _wrapped_view

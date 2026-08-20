from django.urls import path

from .views import pricing_view

app_name = 'subscriptions'

urlpatterns = [
    path('pricing/', pricing_view, name='pricing'),
]
